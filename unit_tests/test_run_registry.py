"""Unit tests for the in-flight run registry.

Pins the contract the WebSocket handler relies on: id minting, log-buffer
bounded growth, supersession + detach semantics, and TTL-based GC.
"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio

from testmcpy.server import run_registry


@pytest_asyncio.fixture(autouse=True)
async def _isolated_registry():
    """Each test starts with an empty registry — module-level state would
    otherwise leak across tests."""
    await run_registry.reset_for_tests()
    yield
    await run_registry.reset_for_tests()


@pytest.mark.asyncio
async def test_create_run_mints_distinct_ids():
    """Two consecutive create_run calls produce two distinct ids and
    two independent handles. Catches a bug where a future refactor
    might accidentally key on something coarser than time-of-day."""
    a = await run_registry.create_run(kind="single", meta={"test_path": "/a"})
    b = await run_registry.create_run(kind="single", meta={"test_path": "/b"})
    assert a.run_id != b.run_id
    assert a is not b
    assert a.meta["test_path"] == "/a"
    assert b.meta["test_path"] == "/b"


@pytest.mark.asyncio
async def test_get_run_returns_handle_or_none():
    handle = await run_registry.create_run(kind="single", meta={})
    assert await run_registry.get_run(handle.run_id) is handle
    assert await run_registry.get_run("does-not-exist") is None


@pytest.mark.asyncio
async def test_log_buffer_is_bounded():
    """Producer that emits more lines than LOG_BUFFER_MAX must NOT pin
    arbitrary memory — older lines evict FIFO. Reload-after-eviction
    sees only the tail; the UI banner is allowed to hint at this."""
    handle = await run_registry.create_run(kind="single", meta={})
    overflow = run_registry.LOG_BUFFER_MAX + 100
    for i in range(overflow):
        run_registry.log(handle, f"line {i}")
    assert len(handle.log_buffer) == run_registry.LOG_BUFFER_MAX
    # First 100 lines evicted; tail starts at line 100.
    assert handle.log_buffer[0] == "line 100"
    assert handle.log_buffer[-1] == f"line {overflow - 1}"


@pytest.mark.asyncio
async def test_log_without_attachment_buffers_but_doesnt_raise():
    """A run with no client currently attached still records logs.
    This is the whole point of the registry — runs survive disconnect."""
    handle = await run_registry.create_run(kind="single", meta={})
    assert handle.attached_queue is None
    run_registry.log(handle, "first")
    run_registry.log(handle, "second")
    assert list(handle.log_buffer) == ["first", "second"]


@pytest.mark.asyncio
async def test_attach_returns_queue_and_routes_subsequent_logs():
    """After attach(), new log lines reach the returned queue (live
    stream), but the historical buffer must be replayed separately
    via buffered_replay — attach itself does not redeliver backlog."""
    handle = await run_registry.create_run(kind="single", meta={})
    run_registry.log(handle, "before-attach")
    queue, token = await run_registry.attach(handle)
    assert token == 1
    assert handle.attached_queue is queue
    # Nothing replayed onto the queue automatically; caller drives replay.
    assert queue.empty()
    # Now live lines flow through.
    run_registry.log(handle, "after-attach")
    msg = await queue.get()
    assert msg == {"type": "log", "message": "after-attach"}


@pytest.mark.asyncio
async def test_second_attach_supersedes_first_with_marker():
    """When a second client attaches, the previous attachment receives a
    `superseded` marker so it can exit cleanly, and the new attachment
    is the one that receives subsequent live events."""
    handle = await run_registry.create_run(kind="single", meta={})
    first_queue, first_token = await run_registry.attach(handle)
    second_queue, second_token = await run_registry.attach(handle)
    assert second_token == first_token + 1
    assert handle.attached_queue is second_queue
    # First queue got a 'superseded' marker so the old listener wakes up.
    superseded = first_queue.get_nowait()
    assert superseded["type"] == "superseded"
    assert superseded["by_token"] == second_token
    # New live events ONLY go to the second queue.
    run_registry.log(handle, "new live")
    assert first_queue.empty()
    msg = second_queue.get_nowait()
    assert msg == {"type": "log", "message": "new live"}


@pytest.mark.asyncio
async def test_detach_only_clears_when_token_matches():
    """A stale detach call (e.g. a slow disconnect handler running after
    a newer client already took over) must NOT clear the active
    attachment. Token-keyed detach makes this safe."""
    handle = await run_registry.create_run(kind="single", meta={})
    first_queue, first_token = await run_registry.attach(handle)
    second_queue, second_token = await run_registry.attach(handle)
    # Stale detach from the FIRST attachment — must be a no-op.
    await run_registry.detach(handle, first_token)
    assert handle.attached_queue is second_queue
    # Proper detach from the current attachment clears it.
    await run_registry.detach(handle, second_token)
    assert handle.attached_queue is None


@pytest.mark.asyncio
async def test_buffered_replay_returns_logs_then_structured_events():
    """Replay order must be: log lines (rendered as backlog), then the
    structured progress / completion events (so the UI rebuilds its
    panels). Out-of-order replay would leave the UI thinking a test is
    still running when its completion event is buried in the log
    backlog."""
    handle = await run_registry.create_run(kind="single", meta={})
    run_registry.log(handle, "log one")
    run_registry.event(handle, {"type": "test_start", "test_name": "t1"})
    run_registry.log(handle, "log two")
    run_registry.event(handle, {"type": "test_complete", "test_name": "t1"})

    replay = run_registry.buffered_replay(handle)
    types = [m["type"] for m in replay]
    # 2 log_replay lines then 2 structured events — chronological within
    # each kind, log-then-structured at the boundary.
    assert types == ["log_replay", "log_replay", "test_start", "test_complete"]
    assert replay[0]["message"] == "log one"
    assert replay[1]["message"] == "log two"


@pytest.mark.asyncio
async def test_finalize_marks_status_and_finished_at():
    handle = await run_registry.create_run(kind="single", meta={})
    # Fresh handles are queued until acquire_slot grants a concurrency
    # slot; both queued and running count as active (not finished).
    assert handle.status == "queued"
    assert not handle.is_finished
    assert handle.finished_at is None

    summary = {"total": 1, "passed": 1, "failed": 0}
    await run_registry.finalize(handle.run_id, status="completed", summary=summary)

    assert handle.status == "completed"
    assert handle.summary == summary
    assert handle.finished_at is not None
    assert handle.is_finished


@pytest.mark.asyncio
async def test_finalize_is_idempotent():
    """A duplicate finalize (e.g. completion-then-error race) leaves the
    first-write status in place — the run's first terminal state wins."""
    handle = await run_registry.create_run(kind="single", meta={})
    await run_registry.finalize(handle.run_id, status="completed")
    first_finished_at = handle.finished_at
    await run_registry.finalize(handle.run_id, status="error")
    assert handle.status == "completed"
    assert handle.finished_at == first_finished_at


@pytest.mark.asyncio
async def test_finalize_missing_run_is_a_noop():
    # No exception; idempotent absence handling.
    await run_registry.finalize("does-not-exist", status="completed")


@pytest.mark.asyncio
async def test_cleanup_gcs_finished_runs_past_ttl():
    """Finished handles older than CLEANUP_TTL are GC'd by the next
    create_run call. Still-running handles and recently-finished ones
    are preserved."""
    old_finished = await run_registry.create_run(kind="single", meta={"label": "old"})
    recent_finished = await run_registry.create_run(kind="single", meta={"label": "recent"})
    still_running = await run_registry.create_run(kind="single", meta={"label": "live"})

    await run_registry.finalize(old_finished.run_id, status="completed")
    await run_registry.finalize(recent_finished.run_id, status="completed")
    # Backdate the old one past the TTL.
    old_finished.finished_at = datetime.now() - run_registry.CLEANUP_TTL - timedelta(seconds=1)

    # Triggers _gc_finished_unlocked.
    await run_registry.create_run(kind="single", meta={})

    assert await run_registry.get_run(old_finished.run_id) is None
    assert await run_registry.get_run(recent_finished.run_id) is recent_finished
    assert await run_registry.get_run(still_running.run_id) is still_running


@pytest.mark.asyncio
async def test_list_active_excludes_finished():
    a = await run_registry.create_run(kind="single", meta={})
    b = await run_registry.create_run(kind="directory", meta={})
    await run_registry.finalize(b.run_id, status="completed")

    active = await run_registry.list_active()
    assert a in active
    assert b not in active
