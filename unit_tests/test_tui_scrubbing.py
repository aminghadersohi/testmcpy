"""Security regressions for credentials echoed by the CLI chat runtime."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from typer.testing import CliRunner

import testmcpy.cli.commands.tui  # noqa: F401
from testmcpy.cli.app import app
from testmcpy.scrubber import register_secret, reset_cache
from testmcpy.src.mcp_client import MCPToolResult


@pytest.fixture(autouse=True)
def _clean_scrubber_registry():
    reset_cache()
    yield
    reset_cache()


def _invoke_chat(provider, mcp_client, user_input: str, *, no_mcp: bool = False):
    profile_config = SimpleNamespace(default_profile=None, get_profile=lambda _profile_id: None)
    args = ["chat", "--mcp-url", "https://mcp.example.com/mcp"]
    if no_mcp:
        args.append("--no-mcp")
    with (
        patch(
            "testmcpy.llm_profiles.resolve_llm_provider_selection",
            return_value=("openai", "gpt-test", {}),
        ),
        patch("testmcpy.llm_profiles.get_default_llm_profile_id", return_value=None),
        patch("testmcpy.mcp_profiles.get_profile_config", return_value=profile_config),
        patch(
            "testmcpy.src.llm_integration.create_llm_provider",
            return_value=provider,
        ),
        patch("testmcpy.src.mcp_client.MCPClient", return_value=mcp_client),
    ):
        return CliRunner().invoke(app, args, input=user_input)


def test_chat_scrubs_provider_error_and_rendered_traceback():
    secret = "cli-provider-traceback-secret-12345"
    register_secret(secret)
    provider = Mock(
        initialize=AsyncMock(),
        generate_with_tools=AsyncMock(side_effect=RuntimeError(f"provider echoed {secret}")),
        close=AsyncMock(),
    )

    result = _invoke_chat(provider, Mock(), "hello\nexit\n", no_mcp=True)

    assert result.exit_code == 0, result.exception
    assert secret not in result.output
    assert "Traceback" in result.output
    provider.close.assert_awaited_once()


def test_chat_scrubs_tool_exceptions_error_results_and_content():
    secret = "cli-tool-output-secret-12345"
    register_secret(secret)
    provider_response = SimpleNamespace(
        response=f"provider echoed {secret}",
        tool_calls=[{"name": "inspect", "arguments": {}}],
        tool_results=[],
    )
    provider = Mock(
        initialize=AsyncMock(),
        generate_with_tools=AsyncMock(return_value=provider_response),
        close=AsyncMock(),
    )
    mcp_client = Mock(
        initialize=AsyncMock(),
        list_tools=AsyncMock(
            return_value=[SimpleNamespace(name="inspect", description="Inspect", input_schema={})]
        ),
        call_tool=AsyncMock(
            side_effect=[
                RuntimeError(f"tool exception {secret}"),
                MCPToolResult(
                    tool_call_id="call-2",
                    content=None,
                    is_error=True,
                    error_message=f"tool result error {secret}",
                ),
                MCPToolResult(
                    tool_call_id="call-3",
                    content={"nested": [f"tool content {secret}"]},
                    is_error=False,
                ),
            ]
        ),
        close=AsyncMock(),
    )

    result = _invoke_chat(provider, mcp_client, "one\ntwo\nthree\nexit\n")

    assert result.exit_code == 0, result.exception
    assert secret not in result.output
    assert "Tool error" in result.output
    assert "tool result error" in result.output
    assert "tool content" in result.output
    mcp_client.close.assert_awaited_once()
    provider.close.assert_awaited_once()


def test_chat_scrubs_mcp_connection_failure():
    secret = "cli-mcp-connection-secret-12345"
    register_secret(secret)
    provider = Mock(initialize=AsyncMock(), close=AsyncMock())
    mcp_client = Mock(
        initialize=AsyncMock(side_effect=RuntimeError(f"connection echoed {secret}")),
        close=AsyncMock(),
    )

    result = _invoke_chat(provider, mcp_client, "exit\n")

    assert result.exit_code == 0, result.exception
    assert secret not in result.output
    assert "MCP connection failed" in result.output
    mcp_client.close.assert_awaited_once()
    provider.close.assert_awaited_once()
