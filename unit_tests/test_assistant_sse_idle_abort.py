"""
Unit tests for AssistantProvider's SSE idle-abort defense.

The chatbot endpoint's SSE stream can stop emitting events while keeping
the underlying TCP connection open (observed in eval cycle c29 against
the staging chatbot — C00_9, C01_9, C02_7 all hung). The per-test
wall-clock timeout added in v0.7.1 catches these between tests, but a
defense at the provider level lets us free the runner before the wall
clock fires AND surface a clean error message.

These tests drive the SSE loop with a fake stream that sends one event
then goes silent, verifying that:
  - the loop aborts after SSE_IDLE_ABORT_SECONDS rather than hanging,
  - LLMResult.response carries an explanatory error string,
  - a [SSE idle aborted] marker appears in the logs.
"""

import asyncio
import time

import pytest

from testmcpy.src.llm_integration import AssistantProvider, LLMResult, _format_seconds


class _FakeStreamResponse:
    """Mimics the subset of httpx.Response used by AssistantProvider."""

    def __init__(self, lines: list[str], silent_after: float = 60.0):
        self._lines = lines
        self._silent_after = silent_after
        self.status_code = 200

    async def aiter_lines(self):
        for line in self._lines:
            yield line
        # Simulate an open-but-silent SSE stream: never yield again.
        # The provider's wait_for(__anext__) wrapper must abort us.
        await asyncio.sleep(self._silent_after)

    async def aread(self) -> bytes:
        return b""


class _FakeStreamCM:
    def __init__(self, response: _FakeStreamResponse):
        self._response = response

    async def __aenter__(self) -> _FakeStreamResponse:
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeAsyncClient:
    def __init__(self, response: _FakeStreamResponse):
        self._response = response

    def stream(self, *args, **kwargs):
        return _FakeStreamCM(self._response)

    async def aclose(self):
        pass


def _make_provider(idle_seconds: float, lines: list[str]) -> AssistantProvider:
    provider = AssistantProvider(
        workspace_hash="ws-test",
        domain="example.com",
        conversations_path="/api/v1/copilot/conversations",
        completions_path="/api/v1/copilot/completions",
    )
    provider.SSE_IDLE_ABORT_SECONDS = idle_seconds
    provider._client = _FakeAsyncClient(_FakeStreamResponse(lines))  # type: ignore[assignment]
    provider._session_token = "fake-jwt"
    provider._conversation_id = "fake-conv"

    # generate_with_tools now opens a fresh conversation per call (SC-108179).
    # The fake httpx client only fakes .stream(), not .post(), so stub the
    # helper to a no-op that just keeps _conversation_id set.
    async def _fake_open_conversation():
        provider._conversation_id = "fake-conv"

    provider._open_conversation = _fake_open_conversation  # type: ignore[assignment]
    return provider


@pytest.mark.asyncio
async def test_idle_abort_after_no_events():
    """Stream opens, sends NO events, then stays silent → idle-abort."""
    provider = _make_provider(idle_seconds=0.3, lines=[])

    start = time.monotonic()
    result: LLMResult = await provider.generate_with_tools(prompt="hi", timeout=30.0)
    elapsed = time.monotonic() - start

    # Should abort in well under a second, not hang for the full timeout.
    assert elapsed < 2.0, f"Provider hung for {elapsed:.2f}s instead of aborting"
    assert "SSE stream went idle" in result.response
    assert any("SSE idle abort" in line for line in result.logs)
    # Sub-second thresholds must NOT round to "0s" in the diagnostic.
    assert "0s" not in result.response.split("for ")[1].split(" ")[0]


def test_format_seconds_handles_sub_second_overrides():
    """Sub-second budgets (used in tests) must not render as '0s'."""
    assert _format_seconds(0.3) == "300ms"
    assert _format_seconds(0.001) == "1ms"
    assert _format_seconds(1.5) == "1.5s"
    assert _format_seconds(9.9) == "9.9s"
    assert _format_seconds(90.0) == "90s"
    assert _format_seconds(120.5) == "120s"


@pytest.mark.asyncio
async def test_idle_abort_after_partial_stream():
    """Stream sends one event, then stalls → idle-abort still fires."""
    lines = [
        "event: token",
        'data: {"token": "hello"}',
        "",  # blank separator
    ]
    provider = _make_provider(idle_seconds=0.3, lines=lines)

    start = time.monotonic()
    result: LLMResult = await provider.generate_with_tools(prompt="hi", timeout=30.0)
    elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"Provider hung for {elapsed:.2f}s instead of aborting"
    # Partial response was captured before the stall.
    assert "hello" in result.response or "SSE stream went idle" in result.response
    assert any("SSE idle abort" in line for line in result.logs)
    assert any("[SSE idle aborted]" in line for line in result.logs)


@pytest.mark.asyncio
async def test_class_attribute_override_changes_threshold():
    """SSE_IDLE_ABORT_SECONDS is a class attribute and respects subclass / instance overrides."""
    provider = _make_provider(idle_seconds=0.1, lines=[])
    assert provider.SSE_IDLE_ABORT_SECONDS == 0.1
    # Class default is unchanged for other instances.
    other = AssistantProvider(
        workspace_hash="ws-other",
        domain="example.com",
        conversations_path="/api/v1/copilot/conversations",
        completions_path="/api/v1/copilot/completions",
    )
    assert other.SSE_IDLE_ABORT_SECONDS == AssistantProvider.SSE_IDLE_ABORT_SECONDS
    assert AssistantProvider.SSE_IDLE_ABORT_SECONDS == 90.0
