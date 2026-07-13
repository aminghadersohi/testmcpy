"""Integration tests for the WebSocket dispatcher's attach / supersede /
stop / survive-disconnect semantics.

We don't spin up a real FastAPI server — instead a ``_FakeWebSocket``
implements the receive_json / send_json contract ``handle_test_websocket``
expects, and the run-command function is stubbed to a controllable
coroutine that emits a known sequence of logs / events / sleeps. That lets
us pin the four invariants that matter:

1. Disconnect mid-run does NOT cancel the registered task.
2. A fresh WS can ``attach`` to an in-flight run, replay buffered logs,
   and receive subsequent live events.
3. An explicit ``stop`` cancels the task and detaches.
4. A second ``attach`` while another client is watching supersedes the
   first attachment cleanly.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest
import pytest_asyncio
from fastapi import WebSocketDisconnect

from testmcpy.server import run_registry
from testmcpy.server import websocket as ws_module


class _FakeWebSocket:
    """Minimal WebSocket double for the dispatcher.

    Tests push inbound messages via ``inbound.put(...)``; the dispatcher
    pulls them with ``receive_json``. ``send_json`` records outbound
    messages onto ``outbound`` so tests can assert on them.
    """

    def __init__(self):
        self.inbound: asyncio.Queue = asyncio.Queue()
        self.outbound: list[dict] = []
        self.client_state = "CONNECTED"

    async def accept(self) -> None:
        pass

    async def receive_json(self) -> dict:
        msg = await self.inbound.get()
        if msg is None:
            self.client_state = "DISCONNECTED"
            raise WebSocketDisconnect(code=1000)
        return msg

    async def send_json(self, message: dict) -> None:
        if self.client_state != "CONNECTED":
            raise RuntimeError("websocket closed")
        self.outbound.append(message)

    async def disconnect(self) -> None:
        """Simulate a browser reload / network drop."""
        await self.inbound.put(None)


@pytest_asyncio.fixture(autouse=True)
async def _isolated_registry():
    await run_registry.reset_for_tests()
    yield
    await run_registry.reset_for_tests()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Point get_storage() at a temp DB — attach falls back to the
    results DB on a registry miss, and must never touch the developer's
    real .testmcpy/storage.db."""
    import testmcpy.storage as storage_module
    from testmcpy.storage import TestStorage

    storage = TestStorage(db_path=tmp_path / "ws_attach.db")
    monkeypatch.setattr(storage_module, "_storage", storage)
    yield storage
    monkeypatch.setattr(storage_module, "_storage", None)


async def _slow_run_command_factory(steps: int, step_delay: float = 0.05):
    """Build a fake run-command coroutine that streams N log lines and a
    terminal all_complete event, sleeping ``step_delay`` between each.

    Returns ``(coro_fn, started_event, finished_event)`` so tests can
    synchronise around the run's lifecycle without sleeping.
    """
    started = asyncio.Event()
    finished = asyncio.Event()

    async def _command(handle, data, config) -> None:
        started.set()
        try:
            for i in range(steps):
                ws_module._emit_log(handle, f"step {i}")
                await asyncio.sleep(step_delay)
            ws_module._emit_event(handle, {"type": "all_complete", "summary": {"ok": True}})
        finally:
            finished.set()

    return _command, started, finished


async def _wait(event: asyncio.Event, timeout: float = 2.0) -> None:
    await asyncio.wait_for(event.wait(), timeout=timeout)


@pytest.mark.asyncio
async def test_run_test_uses_profile_selection_when_provider_and_model_are_omitted(
    tmp_path, monkeypatch
):
    """A profile-only WS request must not be paired with global LLM defaults."""
    test_path = tmp_path / "profile-only.yaml"
    test_path.write_text("name: profile-only\nprompt: hello\n")
    resolver_calls = []
    runner_kwargs = {}

    def resolve_selection(provider, model, profile_id, **fallbacks):
        resolver_calls.append((provider, model, profile_id, fallbacks))
        return "openai", "profile-model", {"api_key": "profile-secret"}

    class CapturingRunner:
        def __init__(self, **kwargs):
            runner_kwargs.update(kwargs)

        async def initialize(self):
            raise RuntimeError("stop after construction")

        async def cleanup(self):
            return None

    class FakeMCPClient:
        def __init__(self, base_url, auth=None):
            self.base_url = base_url
            self.auth_config = auth

        async def initialize(self):
            return None

        async def close(self):
            return None

    class Config:
        default_provider = "anthropic"
        default_model = "global-model"

        @staticmethod
        def get_mcp_url():
            return "http://127.0.0.1:8084/mcp"

    import testmcpy.llm_profiles as profile_module
    import testmcpy.src.mcp_client as mcp_client_module

    monkeypatch.setattr(profile_module, "resolve_llm_provider_selection", resolve_selection)
    monkeypatch.setattr(mcp_client_module, "MCPClient", FakeMCPClient)
    monkeypatch.setattr(ws_module, "TestRunner", CapturingRunner)
    handle = await run_registry.create_run(kind="single", meta={})

    await ws_module._run_test_command(
        handle,
        {
            "test_path": str(test_path),
            "llm_profile": "profile-only",
            "mcp_url": "http://127.0.0.1:8084/mcp",
        },
        Config(),
    )

    assert resolver_calls == [
        (
            None,
            None,
            "profile-only",
            {"fallback_provider": "anthropic", "fallback_model": "global-model"},
        )
    ]
    assert runner_kwargs["provider"] == "openai"
    assert runner_kwargs["model"] == "profile-model"
    assert runner_kwargs["provider_config"] == {"api_key": "profile-secret"}
    assert runner_kwargs["llm_profile"] == "profile-only"


@pytest.mark.asyncio
async def test_disconnect_does_not_cancel_the_running_task(monkeypatch):
    """Browser reload mid-run must leave the asyncio.Task alive. Before
    the run-registry refactor (SC-108184) the WS dispatcher's
    `_watch_for_stop` would observe the disconnect and immediately
    `run_task.cancel()`."""
    command, started, finished = await _slow_run_command_factory(steps=8, step_delay=0.02)
    monkeypatch.setattr(ws_module, "_run_test_command", command)

    ws = _FakeWebSocket()
    dispatcher_task = asyncio.create_task(ws_module.handle_test_websocket(ws))
    await ws.inbound.put({"type": "run_test", "test_path": "/whatever.yaml"})

    # Wait for the command to actually start before disconnecting; otherwise
    # we'd be testing "cancel before start" which isn't the regression.
    await _wait(started)
    # Drop the connection — simulates the user reloading the browser.
    await ws.disconnect()
    # The dispatcher should exit cleanly, but the run task survives.
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(dispatcher_task, timeout=1.0)

    # Run finishes on its own schedule, NOT cancelled by the disconnect.
    await _wait(finished, timeout=2.0)


@pytest.mark.asyncio
async def test_reattach_replays_buffered_logs_then_streams_live(monkeypatch):
    """Reattach delivers the buffered backlog as `log_replay` events and
    then continues with live `log` events from the still-running task.
    Pins the core UX: reload mid-run shows recent history + keeps going."""
    command, started, finished = await _slow_run_command_factory(steps=6, step_delay=0.05)
    monkeypatch.setattr(ws_module, "_run_test_command", command)

    ws1 = _FakeWebSocket()
    dispatcher1 = asyncio.create_task(ws_module.handle_test_websocket(ws1))
    await ws1.inbound.put({"type": "run_test", "test_path": "/x.yaml"})
    await _wait(started)

    # Wait until at least 2 steps have streamed to ws1.
    async def _ws1_has_n_logs(n):
        while True:
            log_count = sum(1 for m in ws1.outbound if m.get("type") == "log")
            if log_count >= n:
                return
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_ws1_has_n_logs(2), timeout=1.0)

    # Pull the run_id off ws1's outbound stream so ws2 can attach to it.
    run_started = next(m for m in ws1.outbound if m.get("type") == "run_started")
    run_id = run_started["run_id"]
    assert isinstance(run_id, str) and len(run_id) > 0

    # Disconnect ws1. Task continues; logs go to the registry buffer.
    await ws1.disconnect()
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(dispatcher1, timeout=1.0)

    # ws2 attaches by run_id.
    ws2 = _FakeWebSocket()
    dispatcher2 = asyncio.create_task(ws_module.handle_test_websocket(ws2))
    await ws2.inbound.put({"type": "attach", "run_id": run_id})

    # Wait for the run to finish so we can assert on the full transcript.
    await _wait(finished, timeout=3.0)
    # Give the dispatcher a moment to drain the queue after finish.
    await asyncio.sleep(0.1)

    replay_logs = [m for m in ws2.outbound if m.get("type") == "log_replay"]
    live_logs = [m for m in ws2.outbound if m.get("type") == "log"]
    all_completes = [m for m in ws2.outbound if m.get("type") == "all_complete"]

    # Replay must contain at least one entry from before ws2 connected.
    assert len(replay_logs) >= 1, ws2.outbound
    # Together replay + live cover every emitted step.
    total_messages = replay_logs + live_logs
    assert len(total_messages) == 6, total_messages
    # The all_complete event landed on ws2 (replayed if it arrived while
    # we were buffering, live otherwise).
    assert len(all_completes) == 1, ws2.outbound
    # ws2 sees an explicit re-attached signal so the UI can render its
    # banner exactly once.
    reattach_marker = next(m for m in ws2.outbound if m.get("type") == "run_started")
    assert reattach_marker.get("reattached") is True

    # Clean up
    await ws2.disconnect()
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(dispatcher2, timeout=1.0)


@pytest.mark.asyncio
async def test_explicit_stop_cancels_the_task(monkeypatch):
    """An explicit `{type: 'stop'}` message must actually cancel the
    registered task, even though disconnect does not. The asymmetry is
    the whole point — only the user's explicit intent kills a run."""
    # Long-running so the cancel actually has work to interrupt.
    command, started, finished = await _slow_run_command_factory(steps=200, step_delay=0.05)
    monkeypatch.setattr(ws_module, "_run_test_command", command)

    ws = _FakeWebSocket()
    dispatcher = asyncio.create_task(ws_module.handle_test_websocket(ws))
    await ws.inbound.put({"type": "run_test", "test_path": "/x.yaml"})
    await _wait(started)

    # Stop the run.
    await ws.inbound.put({"type": "stop"})

    # Task should resolve quickly via cancellation, not by streaming 200 logs.
    await asyncio.wait_for(finished.wait(), timeout=2.0)

    # Registry handle is marked stopped.
    run_started = next(m for m in ws.outbound if m.get("type") == "run_started")
    handle = await run_registry.get_run(run_started["run_id"])
    assert handle is not None
    assert handle.status == "stopped"

    await ws.disconnect()
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(dispatcher, timeout=1.0)


@pytest.mark.asyncio
async def test_second_attach_supersedes_first_with_marker(monkeypatch):
    """A second client attaching to the same run supersedes the first;
    the first receives a 'superseded' marker so its drain loop exits."""
    command, started, finished = await _slow_run_command_factory(steps=10, step_delay=0.05)
    monkeypatch.setattr(ws_module, "_run_test_command", command)

    ws1 = _FakeWebSocket()
    dispatcher1 = asyncio.create_task(ws_module.handle_test_websocket(ws1))
    await ws1.inbound.put({"type": "run_test", "test_path": "/x.yaml"})
    await _wait(started)
    run_started = next(m for m in ws1.outbound if m.get("type") == "run_started")
    run_id = run_started["run_id"]

    ws2 = _FakeWebSocket()
    dispatcher2 = asyncio.create_task(ws_module.handle_test_websocket(ws2))
    await ws2.inbound.put({"type": "attach", "run_id": run_id})

    # Wait for the run to complete so the dispatchers drain cleanly.
    await _wait(finished, timeout=3.0)
    await asyncio.sleep(0.1)

    # ws1 received a 'superseded' marker; the drain loop will exit.
    assert any(m.get("type") == "superseded" for m in ws1.outbound), ws1.outbound
    # ws2 received the all_complete (it's the live attachment).
    assert any(m.get("type") == "all_complete" for m in ws2.outbound), ws2.outbound

    await ws1.disconnect()
    await ws2.disconnect()
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(dispatcher1, timeout=1.0)
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(dispatcher2, timeout=1.0)


@pytest.mark.asyncio
async def test_directory_batch_emits_one_terminal_all_complete(monkeypatch):
    """A run_directory batch must emit EXACTLY ONE terminal `all_complete`
    — the per-file save runs but the per-file `all_complete` event is
    suppressed via the `_in_batch` flag. Without this, the FIRST file's
    `all_complete` would terminate the client (setRunning=false, close
    WS) before files 2..N could run (Copilot review on PR #76).

    Drives _run_directory_command directly so we don't have to stand up
    a real TestRunner; the per-file delegate is stubbed to a coroutine
    that emits a small fake all_complete IF it isn't told to suppress.
    """
    per_file_all_completes: list[int] = []

    async def _fake_run_test_command(handle, data, config):
        # Emit one log + one test_complete per file so the batch loop
        # has something to slice into `file_complete`.
        ws_module._emit_log(handle, f"running {data.get('name')}")
        ws_module._emit_event(
            handle,
            {
                "type": "test_complete",
                "test_name": f"t_{data.get('name')}",
                "result": {"passed": True, "cost": 0.0, "test_name": f"t_{data.get('name')}"},
            },
        )
        handle.results.append({"passed": True, "cost": 0.0, "test_name": f"t_{data.get('name')}"})
        # Mimic the real function's `_in_batch` gate. If the parent
        # batch loop forgot to set it, this would emit a per-file
        # all_complete and the test would catch it via the counter.
        if not data.get("_in_batch"):
            per_file_all_completes.append(1)
            ws_module._emit_event(
                handle,
                {"type": "all_complete", "summary": {"total": 1, "passed": 1, "failed": 0}},
            )

    monkeypatch.setattr(ws_module, "_run_test_command", _fake_run_test_command)

    handle = await run_registry.create_run(kind="directory", meta={})
    queue, _token = await run_registry.attach(handle)
    await ws_module._run_directory_command(
        handle,
        {
            "files": [
                {"test_path": "/a.yaml", "name": "a.yaml"},
                {"test_path": "/b.yaml", "name": "b.yaml"},
                {"test_path": "/c.yaml", "name": "c.yaml"},
            ],
        },
        config=None,
    )

    # Drain everything the batch emitted into the queue.
    emitted: list[dict] = []
    while not queue.empty():
        emitted.append(queue.get_nowait())

    all_completes = [m for m in emitted if m.get("type") == "all_complete"]
    file_starts = [m for m in emitted if m.get("type") == "file_start"]
    file_completes = [m for m in emitted if m.get("type") == "file_complete"]

    assert len(all_completes) == 1, (
        f"expected exactly 1 terminal all_complete; got {len(all_completes)} "
        f"(per_file_unsuppressed={per_file_all_completes})"
    )
    assert per_file_all_completes == [], (
        "the _in_batch flag should suppress every per-file all_complete; "
        f"got {len(per_file_all_completes)} leaked through"
    )
    assert len(file_starts) == 3
    assert len(file_completes) == 3
    # Terminal summary aggregates across all 3 files.
    assert all_completes[0]["summary"]["total"] == 3
    assert all_completes[0]["summary"]["passed"] == 3


@pytest.mark.asyncio
async def test_in_batch_error_emits_file_error_not_terminal_error(monkeypatch):
    """Pre-fix, when `_run_test_command` was invoked as `_in_batch=True`
    inside a directory batch and the per-file MCP init crashed, it
    emitted `{type: "error"}` — which the client treated as terminal
    (running=false, close WS). The directory batch kept iterating on
    the server but the user couldn't see files 2..N and couldn't stop
    the batch (SC-108217).

    The fix routes per-file errors through `_emit_run_error`, which
    emits `file_error` when `_in_batch=True` so the batch loop and the
    client UI both keep going.
    """
    handle = await run_registry.create_run(kind="directory", meta={})
    queue, _token = await run_registry.attach(handle)
    ws_module._emit_run_error(
        handle,
        {"_in_batch": True, "test_path": "/foo.yaml"},
        "MCP connection failed",
    )
    msg = queue.get_nowait()
    assert msg["type"] == "file_error", msg
    assert msg["message"] == "MCP connection failed"
    assert msg["test_path"] == "/foo.yaml"

    # Single-file path still emits terminal `error`.
    ws_module._emit_run_error(handle, {}, "fatal init error")
    msg2 = queue.get_nowait()
    assert msg2["type"] == "error"
    assert msg2["message"] == "fatal init error"


@pytest.mark.asyncio
async def test_stop_emits_stopping_ack_then_all_complete_with_stopped_status(monkeypatch):
    """SC-108217: when the client sends `{type: "stop"}`, the server now
    emits a `stopping` ack immediately AND a terminal
    `all_complete{status: "stopped"}` once the cancellation finalises.
    Pre-fix the client never saw a terminal event and couldn't tell
    whether the run actually stopped — it just had to optimistically
    set running=false and hope.
    """
    command, started, finished = await _slow_run_command_factory(steps=200, step_delay=0.02)
    monkeypatch.setattr(ws_module, "_run_test_command", command)

    ws = _FakeWebSocket()
    dispatcher = asyncio.create_task(ws_module.handle_test_websocket(ws))
    await ws.inbound.put({"type": "run_test", "test_path": "/x.yaml"})
    await _wait(started)

    # Stop and wait for the task to terminate.
    await ws.inbound.put({"type": "stop"})
    await _wait(finished, timeout=2.0)
    # Give the dispatcher a tick to drain the post-cancel events.
    await asyncio.sleep(0.1)

    stopping_events = [m for m in ws.outbound if m.get("type") == "stopping"]
    all_completes = [m for m in ws.outbound if m.get("type") == "all_complete"]

    assert len(stopping_events) == 1, ws.outbound
    assert len(all_completes) == 1, ws.outbound
    assert all_completes[0]["status"] == "stopped"
    assert all_completes[0]["summary"]["status"] == "stopped"

    await ws.disconnect()
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(dispatcher, timeout=1.0)


@pytest.mark.asyncio
async def test_attach_unknown_run_id_returns_error_and_continues():
    """Attaching to a nonexistent run_id replies with an error and the
    dispatcher stays alive for the next message — the user's WS is not
    closed on a single bad attach attempt."""
    ws = _FakeWebSocket()
    dispatcher = asyncio.create_task(ws_module.handle_test_websocket(ws))
    await ws.inbound.put({"type": "attach", "run_id": "nope"})

    async def _wait_for_error():
        while True:
            if any(m.get("type") == "error" for m in ws.outbound):
                return
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_wait_for_error(), timeout=1.0)
    err = next(m for m in ws.outbound if m.get("type") == "error")
    assert "not found" in err["message"]

    await ws.disconnect()
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(dispatcher, timeout=1.0)


# ---------------------------------------------------------------------------
# Concurrency slots (TESTMCPY_MAX_CONCURRENT_RUNS)
# ---------------------------------------------------------------------------


def _gated_command(started_run_ids: list, release: asyncio.Event):
    """A run command that records execution start order and parks until
    ``release`` is set — lets tests hold a slot open deliberately."""

    async def _command(handle, data, config) -> None:
        started_run_ids.append(handle.run_id)
        await release.wait()
        ws_module._emit_event(handle, {"type": "all_complete", "summary": {}})

    return _command


async def _run_id_from(ws: _FakeWebSocket) -> str:
    while True:
        for m in ws.outbound:
            if m.get("type") == "run_started":
                return m["run_id"]
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_second_run_queues_until_slot_frees(monkeypatch):
    """With one slot, a second run must sit at status=queued (visible to
    /api/runs polling) and start only after the first finishes."""
    monkeypatch.setenv("TESTMCPY_MAX_CONCURRENT_RUNS", "1")
    started: list[str] = []
    release = asyncio.Event()
    monkeypatch.setattr(ws_module, "_run_test_command", _gated_command(started, release))

    ws1, ws2 = _FakeWebSocket(), _FakeWebSocket()
    d1 = asyncio.create_task(ws_module.handle_test_websocket(ws1))
    d2 = asyncio.create_task(ws_module.handle_test_websocket(ws2))
    await ws1.inbound.put({"type": "run_test", "test_path": "/a.yaml"})
    rid1 = await asyncio.wait_for(_run_id_from(ws1), timeout=2.0)
    await ws2.inbound.put({"type": "run_test", "test_path": "/b.yaml"})
    rid2 = await asyncio.wait_for(_run_id_from(ws2), timeout=2.0)

    # Let the second spawn reach the semaphore.
    await asyncio.sleep(0.05)
    h1 = await run_registry.get_run(rid1)
    h2 = await run_registry.get_run(rid2)
    assert h1.status == "running"
    assert h2.status == "queued"
    assert started == [rid1]
    # Queued runs count as active for the background-runs indicator.
    active_ids = {h.run_id for h in await run_registry.list_active()}
    assert {rid1, rid2} <= active_ids

    release.set()

    # First finishes, slot frees, second starts and runs straight through.
    async def _both_started():
        while len(started) < 2:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_both_started(), timeout=2.0)
    assert started == [rid1, rid2]

    for ws, d in ((ws1, d1), (ws2, d2)):
        await ws.disconnect()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(d, timeout=1.0)


@pytest.mark.asyncio
async def test_stop_while_queued_finalizes_as_stopped(monkeypatch):
    """Cancelling a queued run interrupts the semaphore wait: it must
    finalize as stopped and never execute."""
    monkeypatch.setenv("TESTMCPY_MAX_CONCURRENT_RUNS", "1")
    started: list[str] = []
    release = asyncio.Event()
    monkeypatch.setattr(ws_module, "_run_test_command", _gated_command(started, release))

    ws1, ws2 = _FakeWebSocket(), _FakeWebSocket()
    d1 = asyncio.create_task(ws_module.handle_test_websocket(ws1))
    d2 = asyncio.create_task(ws_module.handle_test_websocket(ws2))
    await ws1.inbound.put({"type": "run_test", "test_path": "/a.yaml"})
    rid1 = await asyncio.wait_for(_run_id_from(ws1), timeout=2.0)
    await ws2.inbound.put({"type": "run_test", "test_path": "/b.yaml"})
    rid2 = await asyncio.wait_for(_run_id_from(ws2), timeout=2.0)
    await asyncio.sleep(0.05)

    h2 = await run_registry.get_run(rid2)
    assert h2.status == "queued"
    h2.task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await h2.task
    assert h2.status == "stopped"
    assert rid2 not in started

    # The held slot was never disturbed; releasing finishes run 1 normally.
    release.set()
    h1 = await run_registry.get_run(rid1)
    await asyncio.wait_for(asyncio.shield(h1.task), timeout=2.0)
    assert h1.status == "completed"

    for ws, d in ((ws1, d1), (ws2, d2)):
        await ws.disconnect()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(d, timeout=1.0)


# ---------------------------------------------------------------------------
# Attach fallback to DB history (registry miss)
# ---------------------------------------------------------------------------


def _seed_db_run(storage, run_id, status="completed", n_results=2):
    from datetime import datetime, timezone

    storage.save_suite(suite_id="suite.yaml", name="suite.yaml", questions=[])
    storage.save_run(
        run_id=run_id,
        test_id="suite.yaml",
        test_version=1,
        model="m1",
        provider="p1",
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    for i in range(n_results):
        storage.save_question_result(
            run_id=run_id, question_id=f"t{i}", passed=i % 2 == 0, score=1.0, cost_usd=0.01
        )
    if status != "running":
        storage.finish_run(run_id, status=status)


async def _drive_attach(run_id: str) -> list[dict]:
    ws = _FakeWebSocket()
    dispatcher = asyncio.create_task(ws_module.handle_test_websocket(ws))
    await ws.inbound.put({"type": "attach", "run_id": run_id})

    async def _wait_terminal():
        while True:
            if any(m.get("type") in ("all_complete", "error") for m in ws.outbound):
                return
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_wait_terminal(), timeout=2.0)
    await ws.disconnect()
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(dispatcher, timeout=1.0)
    return ws.outbound


@pytest.mark.asyncio
async def test_attach_after_registry_gc_replays_from_db(isolated_storage):
    """Attaching to a run that was GC'd from the registry (e.g. a tab
    reopened after CLEANUP_TTL) replays the finished record from the DB
    instead of erroring."""
    _seed_db_run(isolated_storage, "gone_but_saved", status="completed")
    outbound = await _drive_attach("gone_but_saved")

    started = next(m for m in outbound if m.get("type") == "run_started")
    assert started["reattached"] is True
    assert started["source"] == "history"
    assert started["status"] == "completed"

    completes = [m for m in outbound if m.get("type") == "test_complete"]
    assert [m["test_name"] for m in completes] == ["t0", "t1"]

    terminal = next(m for m in outbound if m.get("type") == "all_complete")
    assert terminal["status"] == "completed"
    assert terminal["summary"]["total"] == 2
    assert terminal["summary"]["passed"] == 1


@pytest.mark.asyncio
async def test_attach_to_crashed_run_reports_interrupted_with_partial_results(isolated_storage):
    """A DB row stuck at status=running with no registry handle means the
    server died mid-run. The client must get the partial results and an
    interrupted terminal status — not a spinner that never resolves."""
    _seed_db_run(isolated_storage, "crashed_mid_run", status="running", n_results=1)
    outbound = await _drive_attach("crashed_mid_run")

    terminal = next(m for m in outbound if m.get("type") == "all_complete")
    assert terminal["status"] == "interrupted"
    assert len(terminal["results"]) == 1
    assert not any(m.get("type") == "error" for m in outbound)
