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
    claude_cli_auth_env,
    claude_provider_api_key_kwargs,
    create_llm_provider,
    resolve_claude_cli_token,
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


class TestClaudeCliAuthEnv:
    """The UI-entered token is routed to the right CLI env var by prefix."""

    def test_subscription_token_maps_to_oauth_var(self):
        assert claude_cli_auth_env("sk-ant-oat-abc") == {
            "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-abc"
        }

    def test_api_key_maps_to_anthropic_api_key(self):
        assert claude_cli_auth_env("sk-ant-api03-xyz") == {"ANTHROPIC_API_KEY": "sk-ant-api03-xyz"}

    def test_blank_token_yields_no_override(self):
        assert claude_cli_auth_env("") == {}
        assert claude_cli_auth_env(None) == {}

    def test_token_is_stripped(self):
        assert claude_cli_auth_env("  sk-ant-oat-z  ") == {
            "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-z"
        }


class TestClaudeSDKProviderTokenInjection:
    """ClaudeSDKProvider builds the CLI subprocess env from the token."""

    def test_factory_passes_api_key_through(self):
        # create_llm_provider filters kwargs by signature; api_key must survive.
        p = create_llm_provider("claude-sdk", "claude-sonnet-4-6", api_key="sk-ant-oat-1")
        assert p._cli_token == "sk-ant-oat-1"

    def test_api_key_env_resolves_from_environment(self):
        with patch.dict("os.environ", {"MY_CLAUDE_TOK": "sk-ant-oat-fromenv"}):
            p = ClaudeSDKProvider(model="m", api_key_env="MY_CLAUDE_TOK")
            assert p._cli_token == "sk-ant-oat-fromenv"

    def test_direct_api_key_wins_over_env(self):
        with patch.dict("os.environ", {"MY_CLAUDE_TOK": "sk-ant-oat-env"}):
            p = ClaudeSDKProvider(model="m", api_key="sk-direct", api_key_env="MY_CLAUDE_TOK")
            assert p._cli_token == "sk-direct"

    def test_clean_env_with_oauth_token_drops_api_key(self):
        env = ClaudeSDKProvider._build_clean_env(
            source_env={"ANTHROPIC_API_KEY": "old", "CLAUDE_CODE_FOO": "x", "PATH": "/bin"},
            cli_token="sk-ant-oat-1",
        )
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat-1"
        assert "ANTHROPIC_API_KEY" not in env
        assert "CLAUDE_CODE_FOO" not in env  # CLAUDE_CODE* still stripped
        assert env["IS_SANDBOX"] == "1"

    def test_clean_env_with_api_key_drops_oauth(self):
        env = ClaudeSDKProvider._build_clean_env(
            source_env={"CLAUDE_CODE_OAUTH_TOKEN": "old", "PATH": "/bin"},
            cli_token="sk-ant-api-2",
        )
        assert env["ANTHROPIC_API_KEY"] == "sk-ant-api-2"
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in env

    def test_clean_env_without_token_keeps_historical_behavior(self):
        env = ClaudeSDKProvider._build_clean_env(source_env={"PATH": "/bin"}, cli_token=None)
        assert env["ANTHROPIC_API_KEY"] == ""  # blanked -> host subscription login
        assert env["IS_SANDBOX"] == "1"


class TestResolveClaudeCliToken:
    """Best-effort token lookup from the LLM profiles config."""

    def _cfg(self, providers):
        from testmcpy.llm_profiles import LLMProfile

        profile = LLMProfile(profile_id="p", name="p", description="", providers=providers)

        class _Cfg:
            def get_profile(self, _pid=None):
                return profile

        return _Cfg()

    def _prov(self, **kw):
        from testmcpy.llm_profiles import LLMProviderConfig

        return LLMProviderConfig(**kw)

    def test_direct_api_key_for_matching_model(self):
        cfg = self._cfg(
            [self._prov(name="x", provider="claude-sdk", model="claude-x", api_key="sk-ant-oat-1")]
        )
        with patch("testmcpy.llm_profiles.get_llm_profile_config", return_value=cfg):
            assert resolve_claude_cli_token("claude-x") == "sk-ant-oat-1"

    def test_prefers_model_match_over_default(self):
        cfg = self._cfg(
            [
                self._prov(
                    name="d",
                    provider="claude-sdk",
                    model="other",
                    api_key="tok-default",
                    default=True,
                ),
                self._prov(name="m", provider="claude-code", model="wanted", api_key="tok-wanted"),
            ]
        )
        with patch("testmcpy.llm_profiles.get_llm_profile_config", return_value=cfg):
            assert resolve_claude_cli_token("wanted") == "tok-wanted"

    def test_falls_back_to_default_when_no_model_match(self):
        cfg = self._cfg(
            [
                self._prov(name="a", provider="claude-sdk", model="m1", api_key="tok-a"),
                self._prov(
                    name="b", provider="claude-sdk", model="m2", api_key="tok-b", default=True
                ),
            ]
        )
        with patch("testmcpy.llm_profiles.get_llm_profile_config", return_value=cfg):
            assert resolve_claude_cli_token("nope") == "tok-b"

    def test_resolves_api_key_env(self):
        cfg = self._cfg(
            [self._prov(name="x", provider="claude-sdk", model="m", api_key_env="MY_TOK")]
        )
        with patch("testmcpy.llm_profiles.get_llm_profile_config", return_value=cfg):
            with patch.dict("os.environ", {"MY_TOK": "sk-ant-oat-env"}):
                assert resolve_claude_cli_token("m") == "sk-ant-oat-env"

    def test_none_when_no_claude_provider(self):
        cfg = self._cfg([self._prov(name="x", provider="anthropic", model="m", api_key="k")])
        with patch("testmcpy.llm_profiles.get_llm_profile_config", return_value=cfg):
            assert resolve_claude_cli_token("m") is None

    def test_bad_profile_config_degrades_to_none(self):
        # A malformed/unreadable profile must not break claude-sdk construction.
        with patch(
            "testmcpy.llm_profiles.get_llm_profile_config",
            side_effect=ValueError("corrupt profile"),
        ):
            assert resolve_claude_cli_token("m") is None


class TestClaudeProviderApiKeyKwargs:
    def test_empty_for_non_claude_providers(self):
        assert claude_provider_api_key_kwargs("anthropic", "m") == {}
        assert claude_provider_api_key_kwargs("openai", "m") == {}

    def test_returns_api_key_for_claude_when_token_found(self):
        with patch(
            "testmcpy.src.llm_integration.resolve_claude_cli_token", return_value="sk-ant-oat-9"
        ):
            assert claude_provider_api_key_kwargs("claude-sdk", "m") == {"api_key": "sk-ant-oat-9"}

    def test_empty_for_claude_when_no_token(self):
        with patch("testmcpy.src.llm_integration.resolve_claude_cli_token", return_value=None):
            assert claude_provider_api_key_kwargs("claude-code", "m") == {}


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
