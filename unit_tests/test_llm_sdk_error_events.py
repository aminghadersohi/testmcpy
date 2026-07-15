"""Regression tests for vendor SDKs that report failures inside event streams."""

import sys
import types
from unittest.mock import AsyncMock, patch

import pytest

from testmcpy.src.llm_integration import ClaudeSDKProvider, GeminiSDKProvider


def _install_fake_claude_sdk(monkeypatch):
    fake_package = types.ModuleType("claude_agent_sdk")
    fake_types = types.ModuleType("claude_agent_sdk.types")

    class ClaudeSDKError(Exception):
        pass

    class CLIConnectionError(Exception):
        pass

    class CLINotFoundError(Exception):
        pass

    class ProcessError(Exception):
        pass

    class AssistantMessage:
        def __init__(self, content):
            self.content = content

    class TextBlock:
        def __init__(self, text):
            self.text = text

    class ThinkingBlock:
        pass

    class ToolUseBlock:
        pass

    class UserMessage:
        pass

    class SystemMessage:
        pass

    class RateLimitEvent:
        pass

    class ResultMessage:
        def __init__(self, **kwargs):
            self.usage = kwargs.get("usage")
            self.total_cost_usd = kwargs.get("total_cost_usd")
            self.duration_ms = kwargs.get("duration_ms", 0)
            self.num_turns = kwargs.get("num_turns", 1)
            self.is_error = kwargs.get("is_error", False)
            self.errors = kwargs.get("errors")
            self.result = kwargs.get("result")
            self.subtype = kwargs.get("subtype", "success")

    class ToolResultBlock:
        pass

    for name, value in {
        "AssistantMessage": AssistantMessage,
        "ClaudeAgentOptions": object,
        "ClaudeSDKError": ClaudeSDKError,
        "CLIConnectionError": CLIConnectionError,
        "CLINotFoundError": CLINotFoundError,
        "ProcessError": ProcessError,
        "RateLimitEvent": RateLimitEvent,
        "ResultMessage": ResultMessage,
        "SystemMessage": SystemMessage,
        "TextBlock": TextBlock,
        "ThinkingBlock": ThinkingBlock,
        "ToolUseBlock": ToolUseBlock,
        "UserMessage": UserMessage,
    }.items():
        setattr(fake_package, name, value)
    fake_types.ToolResultBlock = ToolResultBlock

    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_package)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk.types", fake_types)
    return fake_package


def _claude_provider(monkeypatch):
    provider = ClaudeSDKProvider(model="claude-sonnet-4-5")
    provider._mcp_server_config = {}
    monkeypatch.setattr(provider, "build_agent_options", lambda **_kwargs: object())
    monkeypatch.setattr(
        provider,
        "start_insecure_mcp_proxy",
        AsyncMock(return_value=None),
    )
    return provider


@pytest.mark.asyncio
async def test_claude_result_message_failure_becomes_sdk_error(monkeypatch):
    sdk = _install_fake_claude_sdk(monkeypatch)

    async def fake_query(**_kwargs):
        yield sdk.ResultMessage(
            is_error=True,
            errors=["rate limit exceeded"],
            result="request could not be completed",
            subtype="error_max_turns",
        )

    sdk.query = fake_query

    result = await _claude_provider(monkeypatch)._run_agent("hello", 30.0, None)

    assert result.error == "rate limit exceeded; request could not be completed"
    assert result.response_text == f"Error: {result.error}"


@pytest.mark.asyncio
async def test_claude_iteration_error_retains_partial_text_and_sets_error(monkeypatch):
    sdk = _install_fake_claude_sdk(monkeypatch)

    async def fake_query(**_kwargs):
        yield sdk.AssistantMessage([sdk.TextBlock("Partial answer")])
        raise sdk.ClaudeSDKError("stream disconnected")

    sdk.query = fake_query

    result = await _claude_provider(monkeypatch)._run_agent("hello", 30.0, None)

    assert result.response_text == "Partial answer"
    assert result.error == "stream disconnected"


class _FakeGeminiEvent:
    def __init__(self, *, error_code=None, error_message=None, interrupted=None):
        self.error_code = error_code
        self.error_message = error_message
        self.interrupted = interrupted
        self.content = None
        self.usage_metadata = None

    def get_function_calls(self):
        return []

    def get_function_responses(self):
        return []

    def is_final_response(self):
        return True


@pytest.mark.parametrize(
    ("event", "expected_error"),
    [
        (
            _FakeGeminiEvent(
                error_code="RESOURCE_EXHAUSTED",
                error_message="quota exceeded",
            ),
            "RESOURCE_EXHAUSTED: quota exceeded",
        ),
        (
            _FakeGeminiEvent(interrupted=True),
            "Gemini SDK run was interrupted",
        ),
    ],
)
@pytest.mark.asyncio
async def test_gemini_terminal_failure_event_becomes_sdk_error(event, expected_error):
    pytest.importorskip("google.adk", reason="google-adk not installed")

    class FakeMcpToolset:
        async def close(self):
            pass

    class FakeSession:
        id = "session-id"

    class FakeSessionService:
        async def create_session(self, **_kwargs):
            return FakeSession()

    class FakeRunner:
        def __init__(self, **_kwargs):
            pass

        async def run_async(self, **_kwargs):
            yield event

    class FakeGemini:
        def __init__(self, **_kwargs):
            pass

    provider = GeminiSDKProvider(model="gemini-sdk-flash", api_key="AIza-test")

    with (
        patch(
            "google.adk.tools.mcp_tool.mcp_toolset.McpToolset",
            return_value=FakeMcpToolset(),
        ),
        patch(
            "google.adk.sessions.in_memory_session_service.InMemorySessionService",
            return_value=FakeSessionService(),
        ),
        patch("google.adk.runners.Runner", side_effect=FakeRunner),
        patch("google.adk.tools.mcp_tool.mcp_session_manager.StreamableHTTPConnectionParams"),
        patch("google.adk.agents.llm_agent.LlmAgent"),
        patch("google.adk.models.google_llm.Gemini", FakeGemini),
    ):
        result = await provider._run_agent("hello", 30.0, None)

    assert result.error == expected_error
    assert result.response_text == f"Error: {expected_error}"
