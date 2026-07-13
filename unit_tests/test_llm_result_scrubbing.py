"""Security regressions for provider-controlled LLM result text."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from testmcpy.config import reload_config
from testmcpy.scrubber import register_secret, reset_cache
from testmcpy.src.llm_integration import (
    CodexSDKProvider,
    LLMResult,
    OpenAIProvider,
    create_llm_provider,
)
from testmcpy.src.mcp_client import MCPToolResult


def test_llm_result_scrubs_registered_secrets_before_callers_receive_it():
    secret = "provider-result-secret-12345"
    register_secret(secret)
    try:
        result = LLMResult(
            response=f"upstream echoed {secret}",
            thinking=f"debugged {secret}",
            raw_response={"body": f"Bearer {secret}"},
            logs=[f"provider log {secret}"],
        )

        assert secret not in result.response
        assert secret not in result.thinking
        assert secret not in result.raw_response["body"]
        assert secret not in result.logs[0]
    finally:
        reset_cache()


def test_llm_result_scrubs_nested_tool_payloads_without_changing_container_types():
    secret = "nested-tool-payload-secret-12345"
    tool_calls = [
        {
            "name": "inspect",
            "arguments": {
                "filters": [f"prefix {secret}", {"values": (secret, 42)}],
            },
        }
    ]
    tool_results = [
        {
            "content": {"items": [{"echo": secret}]},
            "is_error": False,
        }
    ]
    register_secret(secret)
    try:
        result = LLMResult(
            response="ok",
            tool_calls=tool_calls,
            tool_results=tool_results,
        )

        assert isinstance(result.tool_calls, list)
        assert isinstance(result.tool_calls[0], dict)
        assert isinstance(result.tool_calls[0]["arguments"]["filters"], list)
        assert isinstance(result.tool_calls[0]["arguments"]["filters"][1]["values"], tuple)
        assert isinstance(result.tool_results, list)
        assert isinstance(result.tool_results[0], dict)
        assert secret not in repr(result.tool_calls)
        assert secret not in repr(result.tool_results)
        assert secret in repr(tool_calls)
        assert secret in repr(tool_results)
    finally:
        reset_cache()


def test_llm_result_preserves_and_scrubs_native_tool_result_dataclasses():
    secret = "native-tool-result-secret-12345"
    native_result = MCPToolResult(
        tool_call_id="call-1",
        tool_name="inspect",
        content={"nested": [{"echo": secret}, (f"again {secret}",)]},
        is_error=True,
        error_message=f"tool failed with {secret}",
    )
    register_secret(secret)
    try:
        result = LLMResult(
            response="ok",
            tool_results=[native_result],  # type: ignore[list-item]
        )

        scrubbed_result = result.tool_results[0]
        assert isinstance(scrubbed_result, MCPToolResult)
        assert scrubbed_result is not native_result
        assert isinstance(scrubbed_result.content, dict)
        assert isinstance(scrubbed_result.content["nested"], list)
        assert isinstance(scrubbed_result.content["nested"][1], tuple)
        assert secret not in repr(scrubbed_result.content)
        assert secret not in scrubbed_result.error_message
        assert secret in repr(native_result.content)
        assert secret in native_result.error_message
    finally:
        reset_cache()


@pytest.mark.asyncio
async def test_llm_result_scrubs_dynamically_resolved_sdk_mcp_token(monkeypatch):
    secret = "resolved-sdk-mcp-token-12345"
    provider = CodexSDKProvider(
        model="codex-o3",
        mcp_url="https://mcp.example.com/mcp",
        openai_api_key="test-provider-key-12345",
    )
    monkeypatch.setattr(provider, "_check_sdk_installed", lambda: None)
    monkeypatch.setattr(provider, "_validate_credentials", AsyncMock())
    monkeypatch.setattr(
        provider,
        "_resolve_mcp_bearer_token",
        AsyncMock(return_value=secret),
    )
    reset_cache()
    try:
        await provider.initialize()
        result = LLMResult(
            response="ok",
            tool_calls=[{"arguments": {"authorization": f"Bearer {secret}"}}],
        )

        assert provider._mcp_headers == {"Authorization": f"Bearer {secret}"}
        assert secret not in repr(result.tool_calls)
    finally:
        reset_cache()


@pytest.mark.asyncio
async def test_llm_result_scrubs_codex_auth_json_fallback_key(tmp_path, monkeypatch):
    secret = "codex-auth-json-platform-key-12345"
    auth_file = tmp_path / ".codex" / "auth.json"
    auth_file.parent.mkdir(parents=True)
    auth_file.write_text(f'{{"OPENAI_API_KEY": "{secret}"}}')
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    provider = CodexSDKProvider(model="codex-o3")
    reset_cache()
    try:
        await provider._validate_credentials()
        result = LLMResult(
            response="ok",
            tool_results=[{"content": f"upstream echoed {secret}"}],
        )

        assert provider.openai_api_key == secret
        assert secret not in repr(result.tool_results)
    finally:
        reset_cache()


@pytest.mark.asyncio
async def test_llm_result_scrubs_api_key_loaded_only_from_dotenv(tmp_path, monkeypatch):
    original_cwd = Path.cwd()
    secret = "dotenv-only-provider-secret-12345"
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"OPENAI_API_KEY={secret}\n")
    reset_cache()
    reload_config()
    provider = OpenAIProvider(model="gpt-test")

    try:
        await provider.initialize()
        result = LLMResult(response=f"upstream echoed {provider.api_key}")

        assert secret not in result.response
    finally:
        await provider.close()
        monkeypatch.chdir(original_cwd)
        reload_config()
        reset_cache()


@pytest.mark.asyncio
async def test_llm_result_scrubs_direct_factory_credential():
    secret = "direct-factory-provider-secret-12345"
    reset_cache()
    provider = create_llm_provider("openai", "gpt-test", api_key=secret)

    try:
        result = LLMResult(response=f"upstream echoed {secret}")

        assert secret not in result.response
    finally:
        await provider.close()
        reset_cache()
