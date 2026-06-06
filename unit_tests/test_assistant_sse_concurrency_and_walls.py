"""
Unit tests for the SSE per-call wall-clock + heartbeat + concurrency cap
added to AssistantProvider in v0.7.3 (SC-106138).

Three independent guards on the SSE consumption:
  1. PER_CALL_WALL_CLOCK_SECONDS — fires when total time on a call
     exceeds the budget, regardless of progress.
  2. HEARTBEAT_SECONDS — emits a "still streaming" log line every N
     seconds. Lets a parent harness distinguish slow-but-progressing
     from wedged.
  3. configure_concurrency_limit(N) — process-wide semaphore caps
     concurrent SSE streams.
"""

import asyncio
import time

import pytest

from testmcpy.src.llm_integration import AssistantProvider, LLMResult


class _SlowChattyStream:
    """SSE stream that emits an event every ``event_interval`` seconds
    forever (or up to ``max_events``). Mimics a chatty backend that's
    making real progress but too slowly — exactly the pattern that
    PER_CALL_WALL_CLOCK is supposed to catch (idle-abort would NOT
    fire here because each event resets the idle timer).
    """

    def __init__(self, event_interval: float = 0.05, max_events: int = 1000):
        self._event_interval = event_interval
        self._max_events = max_events
        self.status_code = 200

    async def aiter_lines(self):
        for i in range(self._max_events):
            await asyncio.sleep(self._event_interval)
            yield "event: token"
            yield f'data: {{"chunk": "{i} "}}'
            yield ""

    async def aread(self) -> bytes:
        return b""


class _FakeStreamCM:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeAsyncClient:
    def __init__(self, response):
        self._response = response

    def stream(self, *args, **kwargs):
        return _FakeStreamCM(self._response)

    async def aclose(self):
        pass


def _provider(
    *,
    wall_clock: float,
    idle: float,
    heartbeat: float,
    response,
) -> AssistantProvider:
    p = AssistantProvider(
        workspace_hash="ws-t",
        domain="example.com",
        conversations_path="/api/v1/copilot/conversations",
        completions_path="/api/v1/copilot/completions",
    )
    p.PER_CALL_WALL_CLOCK_SECONDS = wall_clock
    p.SSE_IDLE_ABORT_SECONDS = idle
    p.HEARTBEAT_SECONDS = heartbeat
    p._client = _FakeAsyncClient(response)  # type: ignore[assignment]
    p._session_token = "jwt"
    p._conversation_id = "conv"
    return p


@pytest.mark.asyncio
async def test_per_call_wall_clock_fires_against_chatty_stream():
    """A stream that keeps emitting events forever must hit the
    per-call wall-clock guard (idle abort would never fire because
    every event resets last_event_at)."""
    response = _SlowChattyStream(event_interval=0.05, max_events=1000)
    p = _provider(wall_clock=0.6, idle=10.0, heartbeat=10.0, response=response)

    start = time.monotonic()
    result: LLMResult = await p.generate_with_tools(prompt="hi", timeout=30.0)
    elapsed = time.monotonic() - start

    # Aborted before exhausting max_events (which would take 50s).
    assert elapsed < 2.0, f"Wall-clock didn't fire — ran {elapsed:.2f}s"
    # The abort fires AFTER the budget; logs carry the abort marker.
    # NB: `result.response` may already contain real tokens (since the
    # stream WAS making progress). Check the abort signal in logs.
    assert any("wall-clock abort" in line for line in result.logs), result.logs
    assert any("[SSE wall-clock aborted]" in line for line in result.logs)


@pytest.mark.asyncio
async def test_heartbeat_emits_progress_lines_during_long_stream():
    """While the stream is still arriving slowly, at least one heartbeat
    line must appear in logs. (Exact count depends on event-interval
    vs heartbeat-cadence interaction; we just verify the mechanism
    fires.)"""
    response = _SlowChattyStream(event_interval=0.05, max_events=1000)
    # Long wall_clock so the loop runs a while; small heartbeat so it
    # has time to fire.
    p = _provider(wall_clock=1.0, idle=10.0, heartbeat=0.1, response=response)

    result = await p.generate_with_tools(prompt="hi", timeout=30.0)

    heartbeats = [line for line in result.logs if "still streaming" in line]
    assert len(heartbeats) >= 1, f"Expected ≥1 heartbeat, got {len(heartbeats)}"
    # The heartbeat line carries useful context (elapsed + event count).
    assert "elapsed" in heartbeats[0]
    assert "events" in heartbeats[0]


@pytest.mark.asyncio
async def test_concurrency_limit_serialises_streams():
    """Two concurrent generate_with_tools calls with a limit of 1
    must run serially (the second waits for the first to release)."""
    AssistantProvider.configure_concurrency_limit(1)
    try:
        response_a = _SlowChattyStream(event_interval=0.05, max_events=1000)
        response_b = _SlowChattyStream(event_interval=0.05, max_events=1000)
        # Each call has 0.4s wall-clock budget. Serialised → ≥ 0.8s total.
        # Concurrent (no limit) → ~0.4s total.
        pa = _provider(wall_clock=0.4, idle=5.0, heartbeat=5.0, response=response_a)
        pb = _provider(wall_clock=0.4, idle=5.0, heartbeat=5.0, response=response_b)

        start = time.monotonic()
        results = await asyncio.gather(
            pa.generate_with_tools(prompt="a", timeout=30.0),
            pb.generate_with_tools(prompt="b", timeout=30.0),
        )
        elapsed = time.monotonic() - start

        assert elapsed >= 0.7, (
            f"Expected serial execution (≥0.7s), got {elapsed:.2f}s — "
            "semaphore not blocking second caller"
        )
        # Both still completed (with wall-clock aborts, but they completed).
        assert all(isinstance(r, LLMResult) for r in results)
    finally:
        AssistantProvider.configure_concurrency_limit(None)


@pytest.mark.asyncio
async def test_concurrency_limit_unbounded_when_unset():
    """With the limit unset, concurrent calls run in parallel — total
    elapsed should be roughly one budget, not two."""
    # Make sure no leftover semaphore from another test.
    AssistantProvider.configure_concurrency_limit(None)

    response_a = _SlowChattyStream(event_interval=0.05, max_events=1000)
    response_b = _SlowChattyStream(event_interval=0.05, max_events=1000)
    pa = _provider(wall_clock=0.4, idle=5.0, heartbeat=5.0, response=response_a)
    pb = _provider(wall_clock=0.4, idle=5.0, heartbeat=5.0, response=response_b)

    start = time.monotonic()
    await asyncio.gather(
        pa.generate_with_tools(prompt="a", timeout=30.0),
        pb.generate_with_tools(prompt="b", timeout=30.0),
    )
    elapsed = time.monotonic() - start

    assert elapsed < 0.7, (
        f"Expected parallel execution (<0.7s), got {elapsed:.2f}s — "
        "calls running serially without an explicit limit"
    )


def test_configure_concurrency_limit_rejects_negative():
    """Passing a negative max_streams should raise — it would otherwise
    blow up later inside asyncio.Semaphore(-1) at acquire time."""
    AssistantProvider.configure_concurrency_limit(None)  # reset
    with pytest.raises(ValueError, match="non-negative"):
        AssistantProvider.configure_concurrency_limit(-1)
    # State unchanged after the rejected call.
    assert AssistantProvider._max_concurrent_streams is None


def test_configure_concurrency_limit_idempotent():
    """Reconfiguring updates the limit and clears any previously-bound
    semaphore (lazy re-creation in the next event loop)."""
    AssistantProvider.configure_concurrency_limit(3)
    assert AssistantProvider._max_concurrent_streams == 3
    assert AssistantProvider._stream_semaphore is None  # lazy
    AssistantProvider.configure_concurrency_limit(5)
    assert AssistantProvider._max_concurrent_streams == 5
    assert AssistantProvider._stream_semaphore is None
    AssistantProvider.configure_concurrency_limit(None)
    assert AssistantProvider._max_concurrent_streams is None
    assert AssistantProvider._stream_semaphore is None
