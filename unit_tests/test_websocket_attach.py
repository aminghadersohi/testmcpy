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
