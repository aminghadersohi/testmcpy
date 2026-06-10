"""
Unit tests for all LLM provider factories — verifies every provider
can be instantiated and has correct attributes.
"""

from unittest.mock import patch

import pytest

from testmcpy.src.llm_integration import (
    ClaudeSDKProvider,
    CodexSDKProvider,
    GeminiCLIProvider,
    GeminiProvider,
    GeminiSDKProvider,
    LocalModelProvider,
    OllamaProvider,
    OpenRouterProvider,
    XAIProvider,
    create_llm_provider,
)


class TestOllamaProviderFactory:
    def test_factory_creates(self):
        p = create_llm_provider("ollama", "llama3")
        assert isinstance(p, OllamaProvider)

    def test_model_set(self):
        p = create_llm_provider("ollama", "mistral")
        assert p.model == "mistral"


class TestOpenRouterProviderFactory:
    def test_factory_creates(self):
        p = create_llm_provider("openrouter", "deepseek/deepseek-chat-v3", api_key="test")
        assert isinstance(p, OpenRouterProvider)

    def test_base_url(self):
        p = create_llm_provider("openrouter", "test-model", api_key="test")
        assert "openrouter.ai" in p.base_url


class TestXAIProviderFactory:
    def test_factory_creates(self):
        p = create_llm_provider("xai", "grok-4-0709", api_key="test")
        assert isinstance(p, XAIProvider)

    def test_grok_alias(self):
        p = create_llm_provider("grok", "grok-4-0709", api_key="test")
        assert isinstance(p, XAIProvider)

    def test_base_url(self):
        p = create_llm_provider("xai", "grok-4-0709", api_key="test")
        assert "x.ai" in p.base_url

    @pytest.mark.asyncio
    async def test_missing_key_raises(self):
        p = create_llm_provider("xai", "grok-4-0709", api_key="")
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="xAI"):
                await p.initialize()


class TestGeminiProviderFactory:
    def test_factory_creates(self):
        p = create_llm_provider("gemini", "gemini-3.1-pro", api_key="test")
        assert isinstance(p, GeminiProvider)

    def test_google_alias(self):
        p = create_llm_provider("google", "gemini-3.1-pro", api_key="test")
        assert isinstance(p, GeminiProvider)


class TestClaudeSDKProviderFactory:
    def test_factory_creates(self):
        p = create_llm_provider("claude-sdk", "claude-sonnet-4-6")
        assert isinstance(p, ClaudeSDKProvider)

    def test_claude_cli_alias(self):
        p = create_llm_provider("claude-cli", "claude-sonnet-4-6")
        assert isinstance(p, ClaudeSDKProvider)

    def test_claude_code_alias(self):
        p = create_llm_provider("claude-code", "claude-sonnet-4-6")
        assert isinstance(p, ClaudeSDKProvider)


def _is_cli_not_found(exc: Exception) -> bool:
    """Check if exception is a CLI-not-installed error."""
    msg = str(exc).lower()
    return "not found" in msg or "no such file" in msg


class TestCodexSDKProviderFactory:
    def test_factory_creates(self) -> None:
        p = create_llm_provider("codex-sdk", "codex-o4-mini")
        assert isinstance(p, CodexSDKProvider)

    def test_codex_cli_alias(self) -> None:
        p = create_llm_provider("codex-cli", "codex-o4-mini")
        assert isinstance(p, CodexSDKProvider)

    def test_codex_alias(self) -> None:
        p = create_llm_provider("codex", "codex-o4-mini")
        assert isinstance(p, CodexSDKProvider)


class TestGeminiCLIProviderFactory:
    def test_factory_creates(self):
        try:
            p = create_llm_provider("gemini-cli", "gemini-2.5-pro")
            assert isinstance(p, GeminiCLIProvider)
        except Exception as e:
            if _is_cli_not_found(e):
                pytest.skip("Gemini CLI not installed")
            raise


class TestLocalModelProviderFactory:
    def test_factory_creates(self):
        p = create_llm_provider("local", "gpt2")
        assert isinstance(p, LocalModelProvider)

    def test_model_set(self):
        p = create_llm_provider("local", "llama-7b")
        assert p.model == "llama-7b"


class TestGeminiSDKProviderFactory:
    def test_factory_creates(self) -> None:
        p = create_llm_provider("gemini-sdk", "gemini-sdk-flash", api_key="AIza-test")
        assert isinstance(p, GeminiSDKProvider)

    def test_model_remapped(self) -> None:
        p = create_llm_provider("gemini-sdk", "gemini-sdk-flash", api_key="AIza-test")
        assert p.model == "gemini-2.5-flash"


class TestUnknownProvider:
    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            create_llm_provider("nonexistent", "model")
