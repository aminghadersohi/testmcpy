"""
Unit tests for the AssistantProvider multi-turn completion loop.

The Preset chatbot backend (`/api/v1/copilot/completions`) executes
tools server-side and emits ``tool_call`` + ``tool_result`` events on
the FIRST SSE stream then closes WITHOUT a ``final`` or ``token``
event. The generated answer arrives only on a SECOND POST that reuses
the same conversation_id. Before SC-108177, ``generate_with_tools``
only made one POST and the test always failed with an empty response.

These tests drive a fake SSE stream that mimics the two-turn protocol
and verify that generate_with_tools:
  - issues a second POST when the first turn ended with tool_results
    but no response text and no final/error/abort,
  - returns the second turn's text in the final LLMResult,
  - preserves the tool_calls + tool_results accumulated across turns,
  - caps at MAX_COMPLETION_TURNS so a misbehaving backend can't pin a
    runner indefinitely,
  - DOES NOT issue a second POST when the first turn already produced
    a response (the backwards-compatible single-shot path).
"""

import pytest

from testmcpy.src.llm_integration import AssistantProvider, LLMResult


class _ScriptedStreamResponse:
    """SSE response that emits one scripted batch of lines per `aiter_lines`
    call. Each `AssistantProvider` follow-up POST opens a new stream context
    and gets the next batch from the script."""

    def __init__(self, batch_lines: list[str]):
        self._lines = batch_lines
        self.status_code = 200

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return b""


class _ScriptedStreamCM:
    def __init__(self, response: _ScriptedStreamResponse):
        self._response = response

    async def __aenter__(self) -> _ScriptedStreamResponse:
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _ScriptedAsyncClient:
    """Fake httpx client that hands out a different response per stream call.

    Each `stream()` call records the JSON body it received so tests can
    inspect what the provider sent on each turn.
    """

    def __init__(self, batches: list[list[str]]):
        self._batches = list(batches)
        self.posts: list[dict] = []

    def stream(self, method, url, *, headers=None, json=None, timeout=None):
        self.posts.append({"method": method, "url": url, "json": dict(json or {})})
        if self._batches:
            batch = self._batches.pop(0)
        else:
            batch = []  # empty → next stream just closes immediately
        return _ScriptedStreamCM(_ScriptedStreamResponse(batch))

    async def aclose(self):
        pass


def _provider(client: _ScriptedAsyncClient) -> AssistantProvider:
    p = AssistantProvider(
        workspace_hash="ws-mt",
        domain="example.test",
        conversations_path="/api/v1/copilot/conversations",
        completions_path="/api/v1/copilot/completions",
    )
    # Bypass auth / conversation creation — generate_with_tools just needs
    # these three values to be truthy to proceed past the init check.
    p._client = client  # type: ignore[assignment]
    p._session_token = "jwt-test"
    p._conversation_id = "conv-test"
    # Shrink the timing thresholds so unit tests finish in well under a
    # second; the multi-turn behaviour we're testing is independent of
    # them but we don't want a wall-clock or idle abort racing with the
    # test logic.
    p.SSE_IDLE_ABORT_SECONDS = 5.0
    p.PER_CALL_WALL_CLOCK_SECONDS = 5.0
    p.HEARTBEAT_SECONDS = 5.0
    return p


# SSE batches written in the on-wire line-by-line shape AssistantProvider
# consumes via httpx.aiter_lines().
_FIRST_TURN_TOOLS_THEN_CLOSE = [
    "event: tool_call",
    'data: {"tool_call_id": "tc-1", "tool_name": "get_instance_info", "input": {}}',
    "",
    "event: tool_result",
    'data: {"tool_call_id": "tc-1", "tool_name": "get_instance_info", "result": {"ok": true}}',
    "",
    "event: tool_call",
    'data: {"tool_call_id": "tc-2", "tool_name": "search_tools", "input": {"q": "chart"}}',
    "",
    "event: tool_result",
    'data: {"tool_call_id": "tc-2", "tool_name": "search_tools", "result": {"hits": 3}}',
    "",
]

_SECOND_TURN_ANSWER = [
    "event: token",
    'data: {"chunk": "I found"}',
    "",
    "event: token",
    'data: {"chunk": " 3 chart-related tools."}',
    "",
    "event: final",
    'data: {"answer": "I found 3 chart-related tools."}',
    "",
]

_SECOND_TURN_MORE_TOOLS = [
    "event: tool_call",
    'data: {"tool_call_id": "tc-3", "tool_name": "deeper_search", "input": {}}',
    "",
    "event: tool_result",
    'data: {"tool_call_id": "tc-3", "tool_name": "deeper_search", "result": {"hits": 0}}',
    "",
]

_THIRD_TURN_ANSWER = [
    "event: token",
    'data: {"chunk": "Done."}',
    "",
    "event: final",
    'data: {"answer": "Done."}',
    "",
]


@pytest.mark.asyncio
async def test_followup_post_when_first_turn_only_returns_tool_results():
    """Reproduces the original bug from SC-108177: first turn has tools
    but no response text, second turn returns the answer. Before the fix
    this test would assert `result.response == ""` — now it must surface
    the second turn's text."""
    client = _ScriptedAsyncClient([_FIRST_TURN_TOOLS_THEN_CLOSE, _SECOND_TURN_ANSWER])
    p = _provider(client)

    result: LLMResult = await p.generate_with_tools(prompt="show me chart tools", timeout=30.0)

    assert len(client.posts) == 2, "expected a follow-up POST after first turn had tools only"
    # Both POSTs hit the completions endpoint with the same conversation_id.
    assert all(post["json"]["conversation_id"] == "conv-test" for post in client.posts)
    assert result.response == "I found 3 chart-related tools."
    # Accumulated tool state across both turns.
    assert [tc["name"] for tc in result.tool_calls] == ["get_instance_info", "search_tools"]
    assert len(result.tool_results) == 2
    # Logs contain the follow-up marker so a human reading the eval can
    # tell why a second POST happened.
    assert any("Follow-up POST 2/" in line for line in result.logs), result.logs


@pytest.mark.asyncio
async def test_single_turn_when_first_response_has_text():
    """Backwards-compat: if the first turn already returned text, we
    MUST NOT issue a second POST. Pre-existing single-shot behaviour
    must keep working unchanged."""
    one_shot = [
        "event: token",
        'data: {"chunk": "hello there"}',
        "",
        "event: final",
        'data: {"answer": "hello there"}',
        "",
    ]
    client = _ScriptedAsyncClient([one_shot])
    p = _provider(client)

    result = await p.generate_with_tools(prompt="hi", timeout=30.0)

    assert len(client.posts) == 1, "single-shot path must not issue a follow-up POST"
    assert result.response == "hello there"
    assert not any("Follow-up POST" in line for line in result.logs), result.logs


@pytest.mark.asyncio
async def test_stops_after_max_turns_even_if_backend_keeps_returning_tools():
    """Cap protects against a backend that keeps reporting tool calls
    without ever returning text — the runner must NOT loop forever."""
    # Three batches in a row that each emit a fresh tool result. With
    # MAX_COMPLETION_TURNS=3 this exhausts the budget without ever
    # getting an answer, and the provider must give up cleanly.
    client = _ScriptedAsyncClient(
        [
            _FIRST_TURN_TOOLS_THEN_CLOSE,
            _SECOND_TURN_MORE_TOOLS,
            [
                "event: tool_call",
                'data: {"tool_call_id": "tc-4", "tool_name": "x", "input": {}}',
                "",
                "event: tool_result",
                'data: {"tool_call_id": "tc-4", "tool_name": "x", "result": {}}',
                "",
            ],
        ]
    )
    p = _provider(client)

    result = await p.generate_with_tools(prompt="loop forever pls", timeout=30.0)

    assert len(client.posts) == p.MAX_COMPLETION_TURNS, (
        f"expected exactly {p.MAX_COMPLETION_TURNS} POSTs, got {len(client.posts)}"
    )
    # No answer reached — empty response is acceptable here; the cap
    # fired before completion.
    assert result.response == ""
    # All four tool calls across the three turns were captured.
    assert len(result.tool_calls) == 4
    assert len(result.tool_results) == 4


@pytest.mark.asyncio
async def test_no_followup_when_first_turn_emits_no_tool_results():
    """If the backend's first turn returned NOTHING (no tools, no text,
    no final, no error — e.g. an immediate close), follow-up POSTs would
    be useless. We stop after the first turn rather than spinning."""
    client = _ScriptedAsyncClient([[]])  # empty SSE stream
    p = _provider(client)

    result = await p.generate_with_tools(prompt="nothing", timeout=30.0)

    assert len(client.posts) == 1
    assert result.response == ""
    assert any(
        "No new tool_results this turn and no answer text" in line for line in result.logs
    ), result.logs


@pytest.mark.asyncio
async def test_three_turn_flow_text_in_final_turn():
    """Some backends do tool calls across more than one turn before
    finally returning the answer. The loop should keep going until either
    text arrives, the cap fires, or no new tool_results are produced."""
    client = _ScriptedAsyncClient(
        [
            _FIRST_TURN_TOOLS_THEN_CLOSE,
            _SECOND_TURN_MORE_TOOLS,
            _THIRD_TURN_ANSWER,
        ]
    )
    p = _provider(client)

    result = await p.generate_with_tools(prompt="long chain", timeout=30.0)

    assert len(client.posts) == 3
    assert result.response == "Done."
    assert len(result.tool_calls) == 3
    assert len(result.tool_results) == 3


@pytest.mark.asyncio
async def test_followup_payload_matches_first_payload():
    """The follow-up POST should reuse the SAME payload (same prompt,
    same conversation_id) — the backend threads context via
    conversation_id, not via a `query` continuation marker."""
    client = _ScriptedAsyncClient([_FIRST_TURN_TOOLS_THEN_CLOSE, _SECOND_TURN_ANSWER])
    p = _provider(client)

    await p.generate_with_tools(prompt="same prompt", timeout=30.0)

    assert len(client.posts) == 2
    first_body = client.posts[0]["json"]
    second_body = client.posts[1]["json"]
    assert first_body == second_body
    assert first_body["conversation_id"] == "conv-test"
    assert first_body["messages"] == [{"role": "user", "content": "same prompt"}]
