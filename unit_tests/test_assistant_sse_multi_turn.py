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
    # these to be truthy to proceed past the init check. _open_conversation
    # is also now called per-call (SC-108179 — fresh conv per test) so stub
    # it to a no-op that just refreshes the conversation_id; otherwise the
    # fake client (which only fakes `.stream()`) would crash on `.post()`.
    p._client = client  # type: ignore[assignment]
    p._session_token = "jwt-test"
    p._conversation_id = "conv-test"

    _counter = {"n": 0}

    async def _fake_open_conversation():
        _counter["n"] += 1
        p._conversation_id = f"conv-test-{_counter['n']}"

    p._open_conversation = _fake_open_conversation  # type: ignore[assignment]
    p._open_conversation_calls = _counter  # type: ignore[attr-defined]

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

# Real-world Preset chatbot pattern from C01_2_dashboard_drill_down:
# the backend streams a transitional "thinking aloud" sentence ALONGSIDE
# tool calls in the same SSE turn — there is no `final` event yet.
# Earlier code that broke on any text growth would surface this fragment
# as the final answer; the loop must keep going.
_FIRST_TURN_TRANSITIONAL_TEXT_PLUS_TOOLS = [
    "event: token",
    'data: {"chunk": "Let me work through this step by step."}',
    "",
    "event: tool_call",
    'data: {"tool_call_id": "tc-1", "tool_name": "search_tools", "input": {"q": "dashboard"}}',
    "",
    "event: tool_result",
    'data: {"tool_call_id": "tc-1", "tool_name": "search_tools", "result": {"hits": 5}}',
    "",
    "event: tool_call",
    'data: {"tool_call_id": "tc-2", "tool_name": "list_dashboards", "input": {}}',
    "",
    "event: tool_result",
    'data: {"tool_call_id": "tc-2", "tool_name": "list_dashboards", "result": {"items": []}}',
    "",
]

_SECOND_TURN_FINAL_ANALYSIS = [
    "event: token",
    'data: {"chunk": "The Sales Overview dashboard contains 3 charts measuring "}',
    "",
    "event: token",
    'data: {"chunk": "monthly revenue from the orders dataset."}',
    "",
    "event: final",
    'data: {"answer": "The Sales Overview dashboard contains 3 charts measuring monthly revenue from the orders dataset."}',
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
    # Both POSTs in this single generate_with_tools call use the same fresh
    # conversation_id minted at the start of the call (cross-call freshness
    # is asserted by test_fresh_conversation_per_generate_with_tools_call).
    conv_ids = [post["json"]["conversation_id"] for post in client.posts]
    assert len(set(conv_ids)) == 1, conv_ids
    assert conv_ids[0].startswith("conv-test-"), conv_ids[0]
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
    without ever returning text — the runner must NOT loop forever.
    Drives MAX_COMPLETION_TURNS batches, each with a fresh tool_result,
    and verifies the loop stops exactly at the cap regardless of the
    constant's current value (raised 3 → 8 in v0.7.20)."""

    def _one_tool_turn(idx: int) -> list[str]:
        tc_id = f"tc-{idx}"
        return [
            "event: tool_call",
            f'data: {{"tool_call_id": "{tc_id}", "tool_name": "tool_{idx}", "input": {{}}}}',
            "",
            "event: tool_result",
            f'data: {{"tool_call_id": "{tc_id}", "tool_name": "tool_{idx}", "result": {{}}}}',
            "",
        ]

    cap = AssistantProvider.MAX_COMPLETION_TURNS
    # One batch per allowed turn — chatbot keeps emitting fresh tools every
    # turn, never produces text or a final event.
    batches = [_one_tool_turn(i) for i in range(cap)]
    client = _ScriptedAsyncClient(batches)
    p = _provider(client)

    result = await p.generate_with_tools(prompt="loop forever pls", timeout=30.0)

    assert len(client.posts) == p.MAX_COMPLETION_TURNS, (
        f"expected exactly {p.MAX_COMPLETION_TURNS} POSTs, got {len(client.posts)}"
    )
    # No answer reached — empty response is acceptable here; the cap
    # fired before completion.
    assert result.response == ""
    # One tool call per turn → cap-many total.
    assert len(result.tool_calls) == cap
    assert len(result.tool_results) == cap


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
    assert any("No new tool_results and no answer text" in line for line in result.logs), (
        result.logs
    )


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
async def test_followup_post_when_first_turn_has_transitional_text_with_tools():
    """Regression for the C01_2_dashboard_drill_down failure: the backend
    streams a transitional sentence ("Let me work through this step by
    step.") *alongside* tool_call + tool_result events in the same SSE
    turn — and does NOT emit a `final` event yet. The earlier "any text
    arrived → stop" check surfaced that fragment as the answer and never
    issued the follow-up POST. The fix requires text growth AND no new
    tool_results to break, so transitional chatter while tools are still
    in flight keeps the loop going.
    """
    client = _ScriptedAsyncClient(
        [_FIRST_TURN_TRANSITIONAL_TEXT_PLUS_TOOLS, _SECOND_TURN_FINAL_ANALYSIS]
    )
    p = _provider(client)

    result = await p.generate_with_tools(
        prompt="Find any dashboard on this workspace and tell me what it measures.",
        timeout=30.0,
    )

    assert len(client.posts) == 2, (
        "expected a follow-up POST — transitional text + new tool_results must NOT stop the loop"
    )
    # The synthesized answer from the second turn overrides the fragment.
    assert (
        result.response == "Let me work through this step by step."
        "The Sales Overview dashboard contains 3 charts measuring "
        "monthly revenue from the orders dataset."
    )
    # response_includes-style evaluators now have a body that matches.
    for keyword in ("dashboard", "charts", "measuring"):
        assert keyword in result.response, (keyword, result.response)
    # Tool state accumulated from turn 1.
    assert [tc["name"] for tc in result.tool_calls] == [
        "search_tools",
        "list_dashboards",
    ]
    assert len(result.tool_results) == 2


@pytest.mark.asyncio
async def test_loop_stops_when_text_grows_without_new_tool_results():
    """Counterpart to the transitional-text test: if a turn produces
    answer text and NO new tool calls (the backend's "I'm done, here's
    the answer" state), the loop must stop even without an explicit
    `final` event. Otherwise a chatbot that doesn't emit `final` would
    waste the remaining budget on no-op follow-ups."""
    # Turn 1 has the original tools + text. Turn 2 returns ONLY text —
    # no new tool_results, no `final` event. Loop should break after
    # turn 2 and not waste a 3rd POST.
    text_only_no_final = [
        "event: token",
        'data: {"chunk": "Here is the answer."}',
        "",
    ]
    client = _ScriptedAsyncClient([_FIRST_TURN_TRANSITIONAL_TEXT_PLUS_TOOLS, text_only_no_final])
    p = _provider(client)

    result = await p.generate_with_tools(prompt="give me the answer", timeout=30.0)

    assert len(client.posts) == 2, (
        f"expected exactly 2 POSTs, got {len(client.posts)} — loop should "
        "stop once text grows with no new tool_results, even without a final event"
    )
    assert "Here is the answer." in result.response


@pytest.mark.asyncio
async def test_followup_payload_matches_first_payload():
    """Within a single ``generate_with_tools`` invocation, the follow-up
    POST reuses the SAME payload (same prompt, same conversation_id) —
    the backend threads context via conversation_id within a call. (The
    cross-call freshness invariant is asserted separately below.)"""
    client = _ScriptedAsyncClient([_FIRST_TURN_TOOLS_THEN_CLOSE, _SECOND_TURN_ANSWER])
    p = _provider(client)

    await p.generate_with_tools(prompt="same prompt", timeout=30.0)

    assert len(client.posts) == 2
    first_body = client.posts[0]["json"]
    second_body = client.posts[1]["json"]
    assert first_body == second_body
    # The fake _open_conversation we install in `_provider` sets
    # conversation_id to "conv-test-1" on the first generate_with_tools
    # call; what matters here is that BOTH POSTs in this single call use
    # the same one.
    assert first_body["conversation_id"] == "conv-test-1"
    assert first_body["messages"] == [{"role": "user", "content": "same prompt"}]


@pytest.mark.asyncio
async def test_fresh_conversation_per_generate_with_tools_call():
    """SC-108179: each generate_with_tools call must open its own
    conversation. Reusing one across the suite let the backend's
    per-conversation history grow unbounded and later tests silently
    returned empty SSE streams. We assert: (a) the conversation-creation
    helper fires once per generate_with_tools, regardless of how many
    multi-turn follow-up POSTs happen inside it, and (b) each call's
    conversation_id is distinct across calls."""
    client = _ScriptedAsyncClient(
        [
            _SECOND_TURN_ANSWER,  # call 1 → 1 POST
            _FIRST_TURN_TOOLS_THEN_CLOSE,  # call 2 → 2 POSTs (multi-turn)
            _SECOND_TURN_ANSWER,
            _SECOND_TURN_ANSWER,  # call 3 → 1 POST
        ]
    )
    p = _provider(client)

    await p.generate_with_tools(prompt="first", timeout=30.0)
    await p.generate_with_tools(prompt="second", timeout=30.0)
    await p.generate_with_tools(prompt="third", timeout=30.0)

    # _open_conversation fires exactly once per call (even when a call
    # makes multiple internal follow-up POSTs).
    assert p._open_conversation_calls["n"] == 3, p._open_conversation_calls

    # Each call's POSTs use a fresh, distinct conversation_id. Group
    # POSTs into the calls that issued them via _open_conversation
    # counter — turn 1 of each call carries a brand-new id; follow-ups
    # within the same call reuse it.
    conv_ids = [post["json"]["conversation_id"] for post in client.posts]
    # Three unique conversation_ids across three calls — proves we're
    # not silently reusing one.
    distinct_ids = sorted(set(conv_ids))
    assert distinct_ids == ["conv-test-1", "conv-test-2", "conv-test-3"], conv_ids


@pytest.mark.asyncio
async def test_followup_post_when_final_arrives_alongside_new_tool_results():
    """Regression for the C02_1_explore_not_generate failure (SC-108182):
    the Preset chatbot backend emits a `final` event in the SAME SSE turn
    as the tool_call + tool_result events. The earlier "got_final → break"
    check terminated immediately and dropped the follow-up POST that
    carries the actual synthesized answer (the explore URL after
    generate_explore_link ran). With the fix, `got_final` only stops the
    loop when no new tool_results arrived this turn — otherwise we keep
    going so the backend can synthesize the answer in a follow-up POST.
    """
    first_turn_tools_plus_final = [
        "event: token",
        'data: {"chunk": "Sure! I\'ll use Vehicle Sales."}',
        "",
        "event: tool_call",
        'data: {"tool_call_id": "tc-1", "tool_name": "search_tools", "input": {}}',
        "",
        "event: tool_result",
        'data: {"tool_call_id": "tc-1", "tool_name": "search_tools", "result": {}}',
        "",
        "event: tool_call",
        'data: {"tool_call_id": "tc-2", "tool_name": "generate_explore_link", "input": {}}',
        "",
        "event: tool_result",
        'data: {"tool_call_id": "tc-2", "tool_name": "generate_explore_link",'
        ' "result": {"url": "https://example/explore?slice_id=1"}}',
        "",
        # Backend signals `final` AT THE SAME TIME as the tool calls — the
        # synthesized answer comes on the follow-up POST, not in this turn.
        "event: final",
        'data: {"answer": "Sure! I\'ll use Vehicle Sales."}',
        "",
    ]
    second_turn_synthesis = [
        "event: token",
        'data: {"chunk": "Here\'s your explore URL: "}',
        "",
        "event: token",
        'data: {"chunk": "https://example/explore?slice_id=1"}',
        "",
        # NB: this data: line was previously two adjacent string literals
        # which Python concatenated without a separator, producing invalid
        # JSON (`."Here's…`) that SSE parsing silently dropped. Now a single
        # well-formed JSON object.
        "event: final",
        'data: {"answer": "Sure! Here\'s your explore URL: https://example/explore?slice_id=1"}',
        "",
    ]
    client = _ScriptedAsyncClient([first_turn_tools_plus_final, second_turn_synthesis])
    p = _provider(client)

    result = await p.generate_with_tools(
        prompt="Give me an explore URL I can tweak in the browser.", timeout=30.0
    )

    assert len(client.posts) == 2, (
        "expected a follow-up POST — `final` alongside new tool_results must "
        "NOT short-circuit the loop"
    )
    assert "explore?slice_id=1" in result.response, result.response
    assert any(tc["name"] == "generate_explore_link" for tc in result.tool_calls)
    # Directly assert BOTH `final` events were successfully parsed. Without
    # these, a silent JSONDecodeError on the scripted `final` payload would
    # let this test pass purely on the token-chunk assertions while leaving
    # got_final-handling regressions invisible.
    final_log_lines = [line for line in result.logs if "Final event received" in line]
    assert len(final_log_lines) == 2, (
        f"expected 2 `Final event received` log lines (one per turn), got "
        f"{len(final_log_lines)}: {result.logs}"
    )
    assert not any("Failed to parse SSE data" in line for line in result.logs), result.logs


@pytest.mark.asyncio
async def test_got_final_alone_still_stops_when_no_new_tool_results():
    """Counterpart to the prior test: when `final` arrives in a turn that
    produced ONLY text (no new tool_results), the loop must still stop —
    the backend has nothing more to synthesize. Without this guard a
    backend that emits `final` after a clean text-only turn would burn a
    follow-up POST."""
    text_only_final = [
        "event: token",
        'data: {"chunk": "Done."}',
        "",
        "event: final",
        'data: {"answer": "Done."}',
        "",
    ]
    client = _ScriptedAsyncClient([text_only_final])
    p = _provider(client)

    result = await p.generate_with_tools(prompt="hi", timeout=30.0)

    assert len(client.posts) == 1
    assert result.response == "Done."


@pytest.mark.asyncio
async def test_got_error_terminates_immediately_even_with_new_tool_results():
    """`got_error` is unconditional — an error from the backend is
    terminal regardless of whether tools fired in the same turn. Avoid
    follow-up POSTs that would surface a second error from the same
    broken conversation."""
    error_turn = [
        "event: tool_call",
        'data: {"tool_call_id": "tc-1", "tool_name": "search_tools", "input": {}}',
        "",
        "event: tool_result",
        'data: {"tool_call_id": "tc-1", "tool_name": "search_tools", "result": {}}',
        "",
        "event: error",
        'data: {"error": "backend exploded"}',
        "",
    ]
    client = _ScriptedAsyncClient([error_turn, _SECOND_TURN_ANSWER])
    p = _provider(client)

    result = await p.generate_with_tools(prompt="hi", timeout=30.0)

    # Stopped after the first turn even though tool_results arrived.
    assert len(client.posts) == 1, client.posts
    assert "backend exploded" in result.response or "Error" in result.response


@pytest.mark.asyncio
async def test_conversation_creation_failure_returns_error_llmresult():
    """If _open_conversation raises, generate_with_tools must surface a
    well-formed LLMResult with an error response — NOT propagate the
    exception. The test runner expects an LLMResult per call."""
    client = _ScriptedAsyncClient([])
    p = _provider(client)

    async def _failing_open_conversation():
        raise RuntimeError("Conversation creation failed: HTTP 503 - down")

    p._open_conversation = _failing_open_conversation  # type: ignore[assignment]

    result = await p.generate_with_tools(prompt="hi", timeout=30.0)

    assert "failed to create conversation" in result.response.lower(), result.response
    assert "HTTP 503" in result.response
    # No POST should have happened because we never reached the SSE loop.
    assert client.posts == []
    # Logs include a diagnostic line so debugging is possible.
    assert any("Conversation creation failed" in line for line in result.logs), result.logs
