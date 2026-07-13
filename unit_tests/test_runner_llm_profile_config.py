"""Regression tests for applying LLM profiles to normal TestRunner execution."""

from unittest.mock import AsyncMock, patch

import pytest

from testmcpy.llm_profiles import LLMProfileConfigError, reload_llm_profile_config
from testmcpy.src.test_runner import TestRunner as Runner


class _MCPClient:
    auth_config = None


@pytest.mark.asyncio
async def test_initialize_rejects_malformed_default_profile_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".llm_providers.yaml").write_text(
        "profiles:\n  prod:\n    providers:\n      - null\n"
    )
    reload_llm_profile_config()

    runner = Runner(
        model="gpt-test",
        provider="openai",
        mcp_client=_MCPClient(),  # type: ignore[arg-type]
    )

    with pytest.raises(LLMProfileConfigError, match="Invalid LLM profile configuration"):
        await runner.initialize()


@pytest.mark.asyncio
async def test_initialize_passes_environment_backed_profile_key_to_provider(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    (tmp_path / ".llm_providers.yaml").write_text(
        """
default: prod
profiles:
  prod:
    name: Production
    description: ''
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-test
        api_key_env: OPENAI_API_KEY
        default: true
"""
    )
    reload_llm_profile_config()
    fake_provider = AsyncMock()

    with patch(
        "testmcpy.src.test_runner.create_llm_provider",
        return_value=fake_provider,
    ) as create_provider:
        runner = Runner(
            model="gpt-test",
            provider="openai",
            mcp_client=_MCPClient(),  # type: ignore[arg-type]
        )
        await runner.initialize()

    assert create_provider.call_args.kwargs["api_key"] == "environment-secret"
    assert create_provider.call_args.kwargs["api_key_env"] == "OPENAI_API_KEY"
    fake_provider.initialize.assert_awaited_once()


@pytest.mark.asyncio
async def test_explicit_provider_config_overrides_profile_runtime_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".llm_providers.yaml").write_text(
        """
default: prod
profiles:
  prod:
    name: Production
    description: ''
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-test
        api_key: profile-secret
"""
    )
    reload_llm_profile_config()
    fake_provider = AsyncMock()

    with patch(
        "testmcpy.src.test_runner.create_llm_provider",
        return_value=fake_provider,
    ) as create_provider:
        runner = Runner(
            model="gpt-test",
            provider="openai",
            mcp_client=_MCPClient(),  # type: ignore[arg-type]
            provider_config={"api_key": "explicit-secret"},
        )
        await runner.initialize()

    assert create_provider.call_args.kwargs["api_key"] == "explicit-secret"

    from testmcpy.scrubber import scrub_text

    assert "explicit-secret" not in scrub_text("upstream echoed explicit-secret")


@pytest.mark.asyncio
async def test_initialize_scrubs_profile_secrets_echoed_by_provider(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".llm_providers.yaml").write_text(
        """
default: prod
profiles:
  prod:
    name: Production
    providers:
      - name: Assistant
        provider: assistant
        model: assistant-model
        api_token: echoed-profile-token
        api_secret: echoed-profile-secret
"""
    )
    reload_llm_profile_config()
    fake_provider = AsyncMock()
    fake_provider.initialize.side_effect = RuntimeError(
        "upstream echoed echoed-profile-token and echoed-profile-secret"
    )

    with patch(
        "testmcpy.src.test_runner.create_llm_provider",
        return_value=fake_provider,
    ):
        runner = Runner(
            model="assistant-model",
            provider="assistant",
            mcp_client=_MCPClient(),  # type: ignore[arg-type]
        )
        with pytest.raises(RuntimeError) as exc_info:
            await runner.initialize()

    message = str(exc_info.value)
    assert "echoed-profile-token" not in message
    assert "echoed-profile-secret" not in message
    assert message.count("***REDACTED***") == 2
    fake_provider.close.assert_awaited_once()
