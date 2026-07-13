"""
Unit tests for AssistantProvider — the chatbot endpoint provider.

Tests config resolution, validation, header building, and
SSE event parsing without making real API calls.
"""

from unittest.mock import patch

import httpx
import pytest

from testmcpy.scrubber import reset_cache, scrub_text
from testmcpy.src.llm_integration import AssistantProvider, create_llm_provider

# Required paths — no hardcoded defaults in AssistantProvider any more.
_P = {
    "conversations_path": "/api/v1/copilot/conversations",
    "completions_path": "/api/v1/copilot/completions",
}


class TestAssistantProviderConstruction:
    """Test constructor and config resolution."""

    def test_factory_creates_assistant(self):
        provider = create_llm_provider(
            "assistant", "default", workspace_hash="ws-test", domain="test.com", **_P
        )
        assert isinstance(provider, AssistantProvider)

    def test_chatbot_alias(self):
        provider = create_llm_provider(
            "chatbot", "default", workspace_hash="ws-test", domain="test.com", **_P
        )
        assert isinstance(provider, AssistantProvider)

    def test_workspace_hash_from_kwargs(self):
        provider = AssistantProvider(workspace_hash="ws-abc", domain="example.com", **_P)
        assert provider.workspace_hash == "ws-abc"

    @patch.dict("os.environ", {"ASSISTANT_WORKSPACE_HASH": "ws-env"}, clear=False)
    def test_env_vars_are_ignored(self):
        """testmcpy code does not read env vars directly. Even with
        ASSISTANT_WORKSPACE_HASH set, the constructor must require an
        explicit workspace_hash kwarg.
        """
        provider = AssistantProvider(domain="example.com", **_P)
        assert provider.workspace_hash == ""

    def test_kwargs_only(self):
        """Confirm that kwargs are the sole source of config."""
        with patch.dict("os.environ", {"ASSISTANT_WORKSPACE_HASH": "ws-env"}, clear=False):
            provider = AssistantProvider(workspace_hash="ws-kwarg", domain="example.com", **_P)
            assert provider.workspace_hash == "ws-kwarg"

    def test_base_url_from_domain(self):
        provider = AssistantProvider(workspace_hash="ws-abc", domain="app.example.com", **_P)
        assert provider.base_url == "https://ws-abc.app.example.com"

    def test_base_url_from_environment_staging(self):
        provider = AssistantProvider(workspace_hash="ws-abc", environment="staging", **_P)
        assert provider.base_url == ""

    def test_base_url_from_environment_production(self):
        provider = AssistantProvider(workspace_hash="ws-abc", environment="production", **_P)
        assert provider.base_url == ""

    def test_base_url_empty_without_workspace(self):
        provider = AssistantProvider(**_P)
        assert provider.base_url == ""

    def test_model_default(self):
        provider = AssistantProvider(workspace_hash="ws-abc", domain="test.com", **_P)
        assert provider.model == "default"

    def test_model_override(self):
        provider = AssistantProvider(
            workspace_hash="ws-abc", domain="test.com", model_override="gpt-5.4", **_P
        )
        assert provider.model_override == "gpt-5.4"

    def test_conversations_path_explicit(self):
        provider = AssistantProvider(
            workspace_hash="ws-abc",
            domain="test.com",
            conversations_path="/custom/conversations",
            completions_path="/custom/completions",
        )
        assert provider.conversations_path == "/custom/conversations"

    def test_completions_path_explicit(self):
        provider = AssistantProvider(
            workspace_hash="ws-abc",
            domain="test.com",
            conversations_path="/custom/conversations",
            completions_path="/custom/completions",
        )
        assert provider.completions_path == "/custom/completions"

    def test_missing_conversations_path_raises(self):
        with pytest.raises(ValueError, match="conversations_path"):
            AssistantProvider(completions_path="/api/v1/copilot/completions")

    def test_missing_completions_path_raises(self):
        with pytest.raises(ValueError, match="completions_path"):
            AssistantProvider(conversations_path="/api/v1/copilot/conversations")

    @pytest.mark.parametrize(
        "path",
        ["//attacker.example/collect", "https://attacker.example/collect", "/path?redirect=x"],
    )
    def test_rejects_cross_origin_or_ambiguous_endpoint_paths(self, path):
        with pytest.raises(ValueError, match="same-origin path"):
            AssistantProvider(
                conversations_path=path,
                completions_path="/completions",
            )


class TestAssistantProviderValidation:
    """Test initialize() validation errors."""

    @pytest.mark.asyncio
    async def test_missing_base_url_raises(self):
        provider = AssistantProvider(**_P)
        with pytest.raises(ValueError, match="workspace_hash"):
            await provider.initialize()

    @pytest.mark.asyncio
    async def test_missing_api_token_raises(self):
        provider = AssistantProvider(workspace_hash="ws-abc", domain="test.com", **_P)
        provider.api_token = ""
        provider.api_secret = ""
        with pytest.raises(ValueError, match="api_token"):
            await provider.initialize()

    @pytest.mark.asyncio
    async def test_missing_api_secret_raises(self):
        provider = AssistantProvider(workspace_hash="ws-abc", domain="test.com", **_P)
        provider.api_token = "token"
        provider.api_secret = ""
        with pytest.raises(ValueError, match="api_token"):
            await provider.initialize()

    @pytest.mark.asyncio
    async def test_auth_error_scrubs_echoed_credentials(self):
        token = "assistant-token-echoed"
        secret = "assistant-secret-echoed"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401,
                text=f"invalid {token} / {secret}",
                request=request,
            )

        provider = AssistantProvider(
            workspace_hash="ws-abc",
            domain="test.com",
            api_url="https://auth.test/token",
            api_token=token,
            api_secret=secret,
            **_P,
        )
        provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(RuntimeError) as exc_info:
                await provider._authenticate()
        finally:
            await provider.close()
            reset_cache()

        assert token not in str(exc_info.value)
        assert secret not in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_auth_registers_returned_session_token(self):
        session_token = "returned-session-token-value"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"payload": {"access_token": session_token}},
                request=request,
            )

        provider = AssistantProvider(
            workspace_hash="ws-abc",
            domain="test.com",
            api_url="https://auth.test/token",
            api_token="assistant-token-value",
            api_secret="assistant-secret-value",
            **_P,
        )
        provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await provider._authenticate()
            assert session_token not in scrub_text(f"echoed {session_token}")
        finally:
            await provider.close()
            reset_cache()


class TestAssistantProviderHeaders:
    """Test _build_headers method."""

    def test_headers_include_jwt(self):
        provider = AssistantProvider(workspace_hash="ws-abc", domain="test.com", **_P)
        provider._session_token = "jwt-test-token"
        headers = provider._build_headers()
        assert headers["Authorization"] == "Bearer jwt-test-token"

    def test_headers_include_csrf(self):
        provider = AssistantProvider(workspace_hash="ws-abc", domain="test.com", **_P)
        provider._session_token = "jwt-test-token"
        headers = provider._build_headers()
        assert "csrf_access_token" in headers["Cookie"]

    def test_headers_include_referer(self):
        provider = AssistantProvider(workspace_hash="ws-abc", domain="test.com", **_P)
        provider._session_token = "jwt-test-token"
        headers = provider._build_headers()
        assert "Referer" in headers


class TestAssistantProviderApiUrl:
    """Test API URL resolution for different environments."""

    def test_staging_api_url(self):
        provider = AssistantProvider(
            workspace_hash="ws-abc",
            environment="staging",
            api_url="https://staging.example.com/api/v1/auth/",
            **_P,
        )
        assert "staging" in provider.api_url

    def test_production_api_url(self):
        provider = AssistantProvider(
            workspace_hash="ws-abc",
            environment="production",
            api_url="https://api.example.com/api/v1/auth/",
            **_P,
        )
        assert "example.com" in provider.api_url

    def test_custom_api_url(self):
        provider = AssistantProvider(
            workspace_hash="ws-abc",
            domain="test.com",
            api_url="https://custom-auth.example.com/auth/",
            **_P,
        )
        assert provider.api_url == "https://custom-auth.example.com/auth/"

    @patch.dict("os.environ", {"ASSISTANT_API_URL": "https://env-auth.com/auth/"}, clear=False)
    def test_api_url_env_var_ignored(self):
        """ASSISTANT_API_URL set in the environment must not leak into the
        provider — code must rely on the api_url kwarg only. We pass an
        explicit value to verify it wins over the env var (if env-var
        reading were re-introduced, this assertion would fail).
        """
        provider = AssistantProvider(
            workspace_hash="ws-abc",
            domain="test.com",
            api_url="https://kwarg-auth.com/auth/",
            **_P,
        )
        assert provider.api_url == "https://kwarg-auth.com/auth/"
        assert "env-auth.com" not in provider.api_url
