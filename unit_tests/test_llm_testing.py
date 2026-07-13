"""Tests for provider connection checks shared by the API and CLI."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from testmcpy.llm_testing import test_llm_provider_connection as check_provider


@pytest.mark.asyncio
async def test_missing_default_api_key_has_actionable_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = await check_provider(provider="openai", model="gpt-test")

    assert result["success"] is False
    assert result["tested"] is True
    assert "OPENAI_API_KEY" in result["error"]


@pytest.mark.asyncio
async def test_cli_backed_provider_is_not_reported_as_success():
    result = await check_provider(
        provider="claude-sdk",
        model="definitely-invalid",
    )

    assert result["success"] is False
    assert result["tested"] is False
    assert "cannot be verified" in result["error"]


@pytest.mark.asyncio
async def test_rejects_invalid_base_url_without_connecting():
    result = await check_provider(
        provider="ollama",
        model="llama",
        base_url="file:///etc/passwd",
    )

    assert result["success"] is False
    assert "absolute HTTP(S) URL" in result["error"]


@pytest.mark.asyncio
async def test_provider_error_redacts_direct_secret(monkeypatch):
    import anthropic

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.messages.create = AsyncMock(side_effect=RuntimeError("bad key sk-private"))
    monkeypatch.setattr(anthropic, "AsyncAnthropic", MagicMock(return_value=fake_client))

    result = await check_provider(
        provider="anthropic",
        model="claude-test",
        api_key="sk-private",
    )

    assert result["success"] is False
    assert "sk-private" not in result["error"]
    assert "***" in result["error"]


@pytest.mark.asyncio
async def test_success_response_redacts_echoed_profile_secret(monkeypatch):
    import openai

    secret = "profile-openai-secret-12345"
    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=f"Bearer {secret}"))]
        )
    )
    monkeypatch.setattr(openai, "AsyncOpenAI", MagicMock(return_value=fake_client))

    result = await check_provider(
        provider="openai",
        model="gpt-test",
        api_key=secret,
    )

    assert result["success"] is True
    assert secret not in result["response"]
    assert "***REDACTED***" in result["response"]


@pytest.mark.asyncio
async def test_google_uses_installed_google_genai_client(monkeypatch):
    from google import genai

    generate = AsyncMock(return_value=SimpleNamespace(text="test successful"))
    aio = SimpleNamespace(
        models=SimpleNamespace(generate_content=generate),
        aclose=AsyncMock(),
    )
    client = SimpleNamespace(aio=aio, close=MagicMock())
    client_factory = MagicMock(return_value=client)
    monkeypatch.setattr(genai, "Client", client_factory)

    result = await check_provider(
        provider="google",
        model="gemini-test",
        api_key="google-secret",
        timeout=12,
    )

    assert result["success"] is True
    assert result["response"] == "test successful"
    client_factory.assert_called_once_with(
        api_key="google-secret",
        http_options={"timeout": 12_000},
    )
    generate.assert_awaited_once()
    aio.aclose.assert_awaited_once()
    client.close.assert_called_once()
