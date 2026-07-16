"""Regression tests for provider-neutral chat history replay."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from testmcpy.src.llm_integration import (
    _CODEX_SYSTEM_PROMPT,
    _GEMINI_SDK_SYSTEM_PROMPT,
    AnthropicProvider,
    AssistantProvider,
    ClaudeSDKProvider,
    CodexSDKProvider,
    GeminiCLIProvider,
    GeminiProvider,
    GeminiSDKProvider,
    OpenAIProvider,
    _compose_agent_system_prompt,
    _format_prompt_with_history,
    _prepare_agent_chat_context,
    _prepare_chat_messages,
)

HISTORY = [
    {"role": "system", "content": "Answer concisely."},
    {"role": "user", "content": "My project is Atlas."},
    {"role": "assistant", "content": "Understood."},
]


def test_prepare_chat_messages_normalizes_system_and_dialogue():
    system_prompt, dialogue = _prepare_chat_messages(
        [
            {"role": "assistant", "content": "orphaned"},
            {"role": "system", "content": " First instruction. "},
            {"role": "user", "content": "First question"},
            {"role": "user", "content": "More detail"},
            {"role": "assistant", "content": "First answer"},
            {"role": "assistant", "content": "More answer"},
            {"role": "system", "content": "Second instruction."},
            {"role": "tool", "content": "ignored"},
            {"role": "user", "content": "   "},
            {"role": "user", "content": 123},
            "not a message",
        ],
        "Current question",
    )

    assert system_prompt == "First instruction.\n\nSecond instruction."
    assert dialogue == [
        {"role": "user", "content": "First question\n\nMore detail"},
        {"role": "assistant", "content": "First answer\n\nMore answer"},
        {"role": "user", "content": "Current question"},
    ]


def test_prepare_chat_messages_does_not_duplicate_current_prompt():
    system_prompt, dialogue = _prepare_chat_messages(
        [{"role": "user", "content": "Already current"}],
        "Already current",
    )

    assert system_prompt is None
    assert dialogue == [{"role": "user", "content": "Already current"}]


def test_format_prompt_with_history_returns_plain_prompt_without_history():
    assert _format_prompt_with_history("Current question", None) == "Current question"
    assert _format_prompt_with_history("Current question", []) == "Current question"


def test_format_prompt_with_history_serializes_authoritative_roles():
    formatted = _format_prompt_with_history("What is my project?", HISTORY)

    instruction, encoded_transcript = formatted.split("\n\n", 1)
    assert "answer only current_user" in instruction
    assert json.loads(encoded_transcript) == {
        "system": "Answer concisely.",
        "messages": [
            {"role": "user", "content": "My project is Atlas."},
            {"role": "assistant", "content": "Understood."},
        ],
        "current_user": "What is my project?",
    }


def test_agent_chat_context_separates_native_system_and_deduplicates_current_turn():
    native_system, formatted = _prepare_agent_chat_context(
        "What is my project?",
        [*HISTORY, {"role": "user", "content": "What is my project?"}],
    )

    instruction, encoded_transcript = formatted.split("\n\n", 1)
    assert native_system == "Answer concisely."
    assert "answer only current_user" in instruction
    assert json.loads(encoded_transcript) == {
        "system": None,
        "messages": [
            {"role": "user", "content": "My project is Atlas."},
            {"role": "assistant", "content": "Understood."},
        ],
        "current_user": "What is my project?",
    }


def test_agent_system_composition_preserves_required_mcp_policy_priority():
    composed = _compose_agent_system_prompt(
        "REQUIRED RULES: use only configured MCP tools.",
        "Answer in haiku form.",
    )

    assert composed.startswith("REQUIRED RULES: use only configured MCP tools.")
    assert "ADDITIONAL SAVED CONVERSATION INSTRUCTION:\nAnswer in haiku form." in composed
    assert "rules always take precedence" in composed


def test_claude_sdk_options_use_saved_prompt_as_native_system_instruction():
    provider = ClaudeSDKProvider(model="claude-test")

    with patch(
        "claude_agent_sdk.ClaudeAgentOptions",
        side_effect=lambda **kwargs: SimpleNamespace(**kwargs),
    ):
        options = provider.build_agent_options(
            cwd="/tmp",
            saved_system_prompt="Answer in haiku form.",
        )

    assert options.system_prompt.startswith(provider._MCP_ONLY_SYSTEM_PROMPT)
    assert "ADDITIONAL SAVED CONVERSATION INSTRUCTION:\nAnswer in haiku form." in (
        options.system_prompt
    )


def test_claude_chat_tool_search_keeps_saved_native_system_instruction():
    provider = ClaudeSDKProvider(model="claude-test")

    with patch(
        "claude_agent_sdk.ClaudeAgentOptions",
        side_effect=lambda **kwargs: SimpleNamespace(**kwargs),
    ):
        options = provider.build_agent_options(
            cwd="/tmp",
            allow_tool_search=True,
            saved_system_prompt="Answer in haiku form.",
        )

    assert options.tools == ["ToolSearch"]
    assert options.system_prompt.startswith(provider._MCP_TOOL_SEARCH_SYSTEM_PROMPT)
    assert "ADDITIONAL SAVED CONVERSATION INSTRUCTION:\nAnswer in haiku form." in (
        options.system_prompt
    )


def test_claude_chat_tool_search_always_applies_required_system_policy():
    provider = ClaudeSDKProvider(model="claude-test")

    with patch(
        "claude_agent_sdk.ClaudeAgentOptions",
        side_effect=lambda **kwargs: SimpleNamespace(**kwargs),
    ):
        options = provider.build_agent_options(
            cwd="/tmp",
            allow_tool_search=True,
        )

    assert options.tools == ["ToolSearch"]
    assert options.system_prompt == provider._MCP_TOOL_SEARCH_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_codex_sdk_uses_native_saved_instruction_and_replays_dialogue():
    provider = CodexSDKProvider(
        model="codex-o3",
        mcp_url="https://mcp.example.test/mcp",
        openai_api_key="sk-test",
    )

    class FakeMCPServer:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    sdk_result = SimpleNamespace(
        final_output="Atlas",
        new_items=[],
        context_wrapper=None,
    )
    run = AsyncMock(return_value=sdk_result)

    with (
        patch("agents.Agent") as agent,
        patch("agents.Runner.run", new=run),
        patch("agents.mcp.MCPServerStreamableHttp", return_value=FakeMCPServer()),
        patch("agents.models.openai_provider.OpenAIProvider"),
        patch("agents.run_config.RunConfig"),
    ):
        result = await provider._run_agent(
            "What is my project?",
            timeout=30.0,
            messages=HISTORY,
        )

    assert result.response_text == "Atlas"
    instructions = agent.call_args.kwargs["instructions"]
    assert instructions.startswith(_CODEX_SYSTEM_PROMPT)
    assert "ADDITIONAL SAVED CONVERSATION INSTRUCTION:\nAnswer concisely." in instructions
    _, encoded_transcript = run.await_args.args[1].split("\n\n", 1)
    assert json.loads(encoded_transcript)["system"] is None


@pytest.mark.asyncio
async def test_gemini_sdk_uses_native_saved_instruction_and_replays_dialogue():
    pytest.importorskip("google.adk", reason="google-adk not installed")
    provider = GeminiSDKProvider(
        model="gemini-sdk-flash",
        mcp_url="https://mcp.example.test/mcp",
        api_key="AIza-test",
    )

    class FakeGemini:
        def __init__(self, **_kwargs):
            pass

    class FakeSessionService:
        async def create_session(self, **_kwargs):
            return SimpleNamespace(id="session-id")

    class FakeRunner:
        def __init__(self, **_kwargs):
            pass

        async def run_async(self, **kwargs):
            self.run_kwargs = kwargs
            if False:
                yield None

    toolset = MagicMock()
    toolset.close = AsyncMock()
    runner = FakeRunner()

    with (
        patch("google.adk.agents.llm_agent.LlmAgent") as agent,
        patch("google.adk.models.google_llm.Gemini", FakeGemini),
        patch("google.adk.runners.Runner", return_value=runner),
        patch(
            "google.adk.sessions.in_memory_session_service.InMemorySessionService",
            return_value=FakeSessionService(),
        ),
        patch("google.adk.tools.mcp_tool.mcp_session_manager.StreamableHTTPConnectionParams"),
        patch("google.adk.tools.mcp_tool.mcp_toolset.McpToolset", return_value=toolset),
    ):
        await provider._run_agent(
            "What is my project?",
            timeout=30.0,
            messages=HISTORY,
        )

    instructions = agent.call_args.kwargs["instruction"]
    assert instructions.startswith(_GEMINI_SDK_SYSTEM_PROMPT)
    assert "ADDITIONAL SAVED CONVERSATION INSTRUCTION:\nAnswer concisely." in instructions
    transcript_text = runner.run_kwargs["new_message"].parts[0].text
    _, encoded_transcript = transcript_text.split("\n\n", 1)
    assert json.loads(encoded_transcript)["system"] is None
    toolset.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_gemini_cli_keeps_system_prompt_in_portable_transcript_fallback():
    provider = GeminiCLIProvider.__new__(GeminiCLIProvider)
    provider.model = "gemini-2.5-pro"
    provider.gemini_cli_path = "/usr/bin/gemini"
    provider.tool_discovery = MagicMock()

    process = AsyncMock()
    process.communicate = AsyncMock(return_value=(b"Atlas", b""))
    process.returncode = 0
    with patch("asyncio.create_subprocess_exec", return_value=process):
        await provider.generate_with_tools(
            "What is my project?",
            tools=[],
            messages=HISTORY,
        )

    transcript_text = process.communicate.await_args.kwargs["input"].decode()
    _, encoded_transcript = transcript_text.split("\n\n", 1)
    assert json.loads(encoded_transcript)["system"] == "Answer concisely."


@pytest.mark.asyncio
async def test_openai_payload_preserves_history_and_system_message():
    provider = OpenAIProvider(model="gpt-test", api_key="test-key")
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "choices": [{"message": {"content": "Atlas"}}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 1, "total_tokens": 9},
    }
    provider.client.post = AsyncMock(return_value=response)

    try:
        result = await provider.generate_with_tools(
            prompt="What is my project?",
            tools=[],
            messages=HISTORY,
        )
    finally:
        await provider.close()

    assert result.response == "Atlas"
    request_json = provider.client.post.await_args.kwargs["json"]
    assert request_json["messages"] == [
        {"role": "system", "content": "Answer concisely."},
        {"role": "user", "content": "My project is Atlas."},
        {"role": "assistant", "content": "Understood."},
        {"role": "user", "content": "What is my project?"},
    ]


@pytest.mark.asyncio
async def test_anthropic_separates_system_from_replayed_dialogue():
    provider = AnthropicProvider(model="claude-test", api_key="test-key")
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "content": [{"type": "text", "text": "Atlas"}],
        "usage": {"input_tokens": 8, "output_tokens": 1},
    }
    provider.client.post = AsyncMock(return_value=response)

    try:
        result = await provider.generate_with_tools(
            prompt="What is my project?",
            tools=[],
            messages=HISTORY,
        )
    finally:
        await provider.client.aclose()

    assert result.response == "Atlas"
    request_json = provider.client.post.await_args.kwargs["json"]
    assert request_json["system"] == [{"type": "text", "text": "Answer concisely."}]
    assert request_json["messages"] == [
        {"role": "user", "content": "My project is Atlas."},
        {"role": "assistant", "content": "Understood."},
        {"role": "user", "content": "What is my project?"},
    ]


def test_assistant_payload_preserves_history_and_system_message():
    provider = AssistantProvider(
        model="gpt-test",
        workspace_hash="workspace",
        domain="example.test",
        conversations_path="/conversations",
        completions_path="/completions",
    )
    provider._conversation_id = "conversation-123"

    payload = provider._build_completions_payload("What is my project?", HISTORY)

    assert payload == {
        "conversation_id": "conversation-123",
        "messages": [
            {"role": "system", "content": "Answer concisely."},
            {"role": "user", "content": "My project is Atlas."},
            {"role": "assistant", "content": "Understood."},
            {"role": "user", "content": "What is my project?"},
        ],
        "model_override": "gpt-test",
    }


@pytest.mark.asyncio
async def test_gemini_maps_system_instruction_separately_from_dialogue():
    provider = GeminiProvider(
        model="gemini-test",
        api_key="test-key",
        mcp_url="https://mcp.example.test/mcp",
    )
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "Atlas"}]}}],
        "usageMetadata": {
            "promptTokenCount": 8,
            "candidatesTokenCount": 1,
            "totalTokenCount": 9,
        },
    }
    provider.client.post = AsyncMock(return_value=response)

    try:
        result = await provider.generate_with_tools(
            prompt="What is my project?",
            tools=[],
            messages=HISTORY,
        )
    finally:
        await provider.close()

    assert result.response == "Atlas"
    request_json = provider.client.post.await_args.kwargs["json"]
    assert request_json["systemInstruction"] == {"parts": [{"text": "Answer concisely."}]}
    assert request_json["contents"] == [
        {"role": "user", "parts": [{"text": "My project is Atlas."}]},
        {"role": "model", "parts": [{"text": "Understood."}]},
        {"role": "user", "parts": [{"text": "What is my project?"}]},
    ]
    assert all(item["role"] != "system" for item in request_json["contents"])
