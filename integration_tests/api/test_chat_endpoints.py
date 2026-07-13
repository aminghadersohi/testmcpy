"""Integration tests for /api/chat and /api/chat/stream.

Covers the selected-profile auth routing (the LLM provider must receive the
SELECTED MCP profile's mcp_url/auth, not the default profile's) and the
TESTMCPY_CHAT_OAUTH_LOGIN-gated interactive OAuth re-login path.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

OAUTH_ERROR = ValueError(
    "No usable cached OAuth token for http://mock-mcp:3000/mcp. Authenticate the MCP profile first."
)


def make_fake_provider(init_error: Exception | None = None) -> AsyncMock:
    """Build a fake LLM provider whose generate_with_tools returns a plain result."""
    provider = AsyncMock()
    if init_error is not None:
        provider.initialize.side_effect = init_error
    provider.generate_with_tools.return_value = SimpleNamespace(
        response="hello",
        tool_calls=[],
        tool_results=[],
        thinking=None,
        token_usage={"prompt": 1, "completion": 1, "total": 2},
        cost=0.0,
        duration=0.1,
    )
    return provider


CHAT_BODY = {
    "message": "hey",
    "model": "claude-sonnet-4-6",
    "provider": "anthropic",
    "profiles": ["test:Test MCP"],
}


class TestChatSelectedProfileAuth:
    """The provider factory must receive the selected profile's mcp_url/auth."""

    def test_chat_passes_selected_profile_mcp_url_and_auth(self, client, mock_mcp_client):
        mock_mcp_client.auth_config = {"type": "oauth", "oauth_auto_discover": True}
        with patch(
            "testmcpy.server.api.create_llm_provider", return_value=make_fake_provider()
        ) as factory:
            res = client.post("/api/chat", json=CHAT_BODY)
        assert res.status_code == 200
        assert res.json()["response"] == "hello"
        kwargs = factory.call_args.kwargs
        assert kwargs["mcp_url"] == mock_mcp_client.base_url
        assert kwargs["auth"] == {"type": "oauth", "oauth_auto_discover": True}

    def test_chat_uses_native_results_without_replaying_tool_calls(self, client, mock_mcp_client):
        native_provider = make_fake_provider()
        native_provider.generate_with_tools.return_value = SimpleNamespace(
            response="created once",
            tool_calls=[{"name": "health_check", "arguments": {"mutate": True}, "id": "native-1"}],
            tool_results=[
                {
                    "tool_call_id": "native-1",
                    "content": "already executed by provider",
                    "is_error": False,
                }
            ],
            thinking=None,
            token_usage=None,
            cost=0.0,
            duration=0.1,
        )

        with patch("testmcpy.server.api.create_llm_provider", return_value=native_provider):
            native_response = client.post("/api/chat", json=CHAT_BODY)

        assert native_response.status_code == 200
        assert native_response.json()["tool_calls"][0]["result"] == ("already executed by provider")
        mock_mcp_client.call_tool.assert_not_awaited()

        non_native_provider = make_fake_provider()
        non_native_provider.generate_with_tools.return_value = SimpleNamespace(
            response="execute through MCP",
            tool_calls=[{"name": "health_check", "arguments": {}, "id": "mcp-1"}],
            tool_results=[],
            thinking=None,
            token_usage=None,
            cost=0.0,
            duration=0.1,
        )

        with patch("testmcpy.server.api.create_llm_provider", return_value=non_native_provider):
            non_native_response = client.post("/api/chat", json=CHAT_BODY)

        assert non_native_response.status_code == 200
        assert non_native_response.json()["tool_calls"][0]["result"] == "OK"
        mock_mcp_client.call_tool.assert_awaited_once()

    def test_chat_rejects_explicit_missing_llm_profile(self, client):
        response = client.post(
            "/api/chat",
            json={
                "message": "hey",
                "llm_profile": "missing",
                "profiles": ["test:Test MCP"],
            },
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "LLM profile 'missing' was not found"

    def test_chat_treats_blank_llm_profile_as_unselected(self, client):
        body = {**CHAT_BODY, "llm_profile": ""}
        with patch("testmcpy.server.api.create_llm_provider", return_value=make_fake_provider()):
            response = client.post("/api/chat", json=body)

        assert response.status_code == 200

    def test_chat_reports_malformed_profile_config_as_conflict(self, client):
        Path(".llm_providers.yaml").write_text("profiles: [not-a-mapping]\n")

        response = client.post(
            "/api/chat",
            json={"message": "hey", "llm_profile": "missing"},
        )

        assert response.status_code == 409
        assert "Invalid LLM profile configuration" in response.json()["detail"]

    def test_chat_stream_reports_malformed_profile_config_detail(self, client):
        Path(".llm_providers.yaml").write_text("profiles: [not-a-mapping]\n")

        response = client.post(
            "/api/chat/stream",
            json={"message": "hey", "profiles": ["test:Test MCP"]},
        )

        assert response.status_code == 200
        assert "Invalid LLM profile configuration" in response.text
        assert "Internal error" not in response.text

    def test_chat_stream_passes_selected_profile_mcp_url_and_auth(self, client, mock_mcp_client):
        mock_mcp_client.auth_config = {"type": "oauth", "oauth_auto_discover": True}
        with patch(
            "testmcpy.server.api.create_llm_provider", return_value=make_fake_provider()
        ) as factory:
            res = client.post("/api/chat/stream", json=CHAT_BODY)
        assert res.status_code == 200
        assert '"type": "complete"' in res.text or '"complete"' in res.text
        kwargs = factory.call_args.kwargs
        assert kwargs["mcp_url"] == mock_mcp_client.base_url
        assert kwargs["auth"] == {"type": "oauth", "oauth_auto_discover": True}

    def test_chat_resolves_profile_api_key_env(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "runtime-profile-key")
        Path(".llm_providers.yaml").write_text(
            """
default: env-profile
profiles:
  env-profile:
    name: Environment profile
    providers:
      - name: Claude
        provider: anthropic
        model: claude-test
        api_key_env: ANTHROPIC_API_KEY
        default: true
"""
        )
        body = {
            "message": "hey",
            "llm_profile": "env-profile",
            "profiles": ["test:Test MCP"],
        }

        with patch(
            "testmcpy.server.api.create_llm_provider", return_value=make_fake_provider()
        ) as factory:
            response = client.post("/api/chat", json=body)

        assert response.status_code == 200
        assert factory.call_args.kwargs["api_key"] == "runtime-profile-key"

    def test_chat_openai_profile_missing_bound_env_never_uses_ambient_key(
        self, client, monkeypatch
    ):
        ambient_secret = "ambient-openai-key-must-not-be-used"
        monkeypatch.setenv("OPENAI_API_KEY", ambient_secret)
        monkeypatch.delenv("PROFILE_OPENAI_KEY", raising=False)
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  isolated:
    name: Isolated OpenAI
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-test
        api_key_env: PROFILE_OPENAI_KEY
"""
        )

        with patch("testmcpy.server.api.create_llm_provider") as factory:
            response = client.post(
                "/api/chat",
                json={
                    "message": "hey",
                    "llm_profile": "isolated",
                    "profiles": ["test:Test MCP"],
                },
            )

        assert response.status_code == 409
        assert "configured API key" in response.json()["detail"]
        assert ambient_secret not in response.text
        factory.assert_not_called()

    def test_chat_default_profile_missing_bound_env_never_uses_ambient_key(
        self, client, monkeypatch
    ):
        ambient_secret = "ambient-default-key-must-not-be-used"
        monkeypatch.setenv("OPENAI_API_KEY", ambient_secret)
        monkeypatch.delenv("PROFILE_OPENAI_KEY", raising=False)
        Path(".llm_providers.yaml").write_text(
            """
default: isolated
profiles:
  isolated:
    name: Isolated OpenAI
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-test
        api_key_env: PROFILE_OPENAI_KEY
"""
        )

        with patch("testmcpy.server.api.create_llm_provider") as factory:
            response = client.post(
                "/api/chat",
                json={
                    "message": "hey",
                    "profiles": ["test:Test MCP"],
                },
            )

        assert response.status_code == 409
        assert "configured API key" in response.json()["detail"]
        assert ambient_secret not in response.text
        factory.assert_not_called()

    def test_chat_anthropic_profile_blank_key_expression_never_uses_ambient_key(
        self, client, monkeypatch
    ):
        ambient_secret = "ambient-anthropic-key-must-not-be-used"
        monkeypatch.setenv("ANTHROPIC_API_KEY", ambient_secret)
        monkeypatch.delenv("PROFILE_ANTHROPIC_KEY", raising=False)
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  isolated:
    name: Isolated Anthropic
    providers:
      - name: Anthropic
        provider: anthropic
        model: claude-test
        api_key: ${PROFILE_ANTHROPIC_KEY}
"""
        )

        with patch("testmcpy.server.api.create_llm_provider") as factory:
            response = client.post(
                "/api/chat",
                json={
                    "message": "hey",
                    "llm_profile": "isolated",
                    "profiles": ["test:Test MCP"],
                },
            )

        assert response.status_code == 409
        assert "configured API key" in response.json()["detail"]
        assert ambient_secret not in response.text
        factory.assert_not_called()

    def test_chat_passes_complete_assistant_profile_runtime_config(self, client):
        Path(".llm_providers.yaml").write_text(
            """
default: assistant-profile
profiles:
  assistant-profile:
    name: Assistant profile
    providers:
      - name: Assistant
        provider: assistant
        model: assistant-model
        workspace_hash: workspace-1
        domain: example.test
        api_token: token-1
        api_secret: secret-1
        api_url: https://example.test/auth
        conversations_path: /conversations
        completions_path: /completions
        default: true
"""
        )
        body = {
            "message": "hey",
            "llm_profile": "assistant-profile",
            "profiles": ["test:Test MCP"],
        }

        with patch(
            "testmcpy.server.api.create_llm_provider", return_value=make_fake_provider()
        ) as factory:
            response = client.post("/api/chat", json=body)

        assert response.status_code == 200
        kwargs = factory.call_args.kwargs
        assert factory.call_args.args == ("assistant", "assistant-model")
        assert kwargs["workspace_hash"] == "workspace-1"
        assert kwargs["domain"] == "example.test"
        assert kwargs["api_token"] == "token-1"
        assert kwargs["api_secret"] == "secret-1"
        assert kwargs["api_url"] == "https://example.test/auth"

    def test_chat_and_stream_scrub_profile_key_echoed_by_provider(self, client):
        secret = "profile-openai-secret-12345"
        Path(".llm_providers.yaml").write_text(
            f"""
default: redaction-profile
profiles:
  redaction-profile:
    name: Redaction profile
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-test
        api_key: {secret}
        default: true
"""
        )
        provider = make_fake_provider()
        provider.generate_with_tools.return_value = SimpleNamespace(
            response=f"Error: upstream echoed Bearer {secret}",
            tool_calls=[],
            thinking=f"debug {secret}",
            token_usage=None,
            cost=0.0,
            duration=0.1,
        )
        body = {
            "message": "hey",
            "llm_profile": "redaction-profile",
            "profiles": ["test:Test MCP"],
        }

        with patch("testmcpy.server.api.create_llm_provider", return_value=provider):
            response = client.post("/api/chat", json=body)
            stream_response = client.post("/api/chat/stream", json=body)

        assert response.status_code == 200
        assert stream_response.status_code == 200
        assert secret not in response.text
        assert secret not in stream_response.text
        assert "***REDACTED***" in response.text
        assert "***REDACTED***" in stream_response.text

    def test_chat_and_stream_close_provider_after_generation_error(self, client):
        regular_provider = make_fake_provider()
        regular_provider.generate_with_tools.side_effect = RuntimeError("generation failed")
        stream_provider = make_fake_provider()
        stream_provider.generate_with_tools.side_effect = RuntimeError("generation failed")

        with patch(
            "testmcpy.server.api.create_llm_provider",
            side_effect=[regular_provider, stream_provider],
        ):
            regular = client.post("/api/chat", json=CHAT_BODY)
            streamed = client.post("/api/chat/stream", json=CHAT_BODY)

        assert regular.status_code == 500
        assert streamed.status_code == 200
        regular_provider.close.assert_awaited_once()
        stream_provider.close.assert_awaited_once()


class TestChatOAuthLoginFlag:
    """TESTMCPY_CHAT_OAUTH_LOGIN gates the interactive OAuth re-login retry."""

    def test_flag_off_oauth_error_surfaces(self, client, monkeypatch):
        monkeypatch.setenv("TESTMCPY_CHAT_OAUTH_LOGIN", "false")
        relogin_client = AsyncMock()
        with (
            patch(
                "testmcpy.server.api.create_llm_provider",
                return_value=make_fake_provider(init_error=OAUTH_ERROR),
            ),
            patch("testmcpy.server.api.get_mcp_client_for_server", relogin_client),
        ):
            res = client.post("/api/chat", json=CHAT_BODY)
        assert res.status_code == 500
        assert "No usable cached OAuth token" in res.json()["detail"]
        # Awaited once by the endpoint's normal client resolution — no re-login.
        assert relogin_client.await_count == 1

    def test_flag_off_stream_emits_error_event(self, client, monkeypatch):
        monkeypatch.setenv("TESTMCPY_CHAT_OAUTH_LOGIN", "0")
        with patch(
            "testmcpy.server.api.create_llm_provider",
            return_value=make_fake_provider(init_error=OAUTH_ERROR),
        ):
            res = client.post("/api/chat/stream", json=CHAT_BODY)
        assert res.status_code == 200
        assert '"error"' in res.text
        assert "No usable cached OAuth token" in res.text

    def test_flag_on_chat_retries_after_relogin(self, client, monkeypatch):
        monkeypatch.delenv("TESTMCPY_CHAT_OAUTH_LOGIN", raising=False)  # default ON
        failing = make_fake_provider(init_error=OAUTH_ERROR)
        working = make_fake_provider()
        relogin_client = AsyncMock()
        with (
            patch(
                "testmcpy.server.api.create_llm_provider",
                side_effect=[failing, working],
            ),
            patch("testmcpy.server.api.get_mcp_client_for_server", relogin_client),
        ):
            res = client.post("/api/chat", json=CHAT_BODY)
        assert res.status_code == 200
        assert res.json()["response"] == "hello"
        # Resolution + re-login.
        assert relogin_client.await_count == 2
        assert relogin_client.await_args.args == ("test", "Test MCP")

    def test_flag_on_stream_emits_oauth_status_and_completes(self, client, monkeypatch):
        monkeypatch.delenv("TESTMCPY_CHAT_OAUTH_LOGIN", raising=False)  # default ON
        failing = make_fake_provider(init_error=OAUTH_ERROR)
        working = make_fake_provider()
        relogin_client = AsyncMock()
        with (
            patch(
                "testmcpy.server.api.create_llm_provider",
                side_effect=[failing, working],
            ),
            patch("testmcpy.server.api.get_mcp_client_for_server", relogin_client),
        ):
            res = client.post("/api/chat/stream", json=CHAT_BODY)
        assert res.status_code == 200
        assert "Waiting for OAuth login in browser..." in res.text
        # Resolution + re-login.
        assert relogin_client.await_count == 2
        assert relogin_client.await_args.args == ("test", "Test MCP")

    def test_flag_on_non_oauth_value_error_not_retried(self, client, monkeypatch):
        monkeypatch.delenv("TESTMCPY_CHAT_OAUTH_LOGIN", raising=False)
        relogin_client = AsyncMock()
        with (
            patch(
                "testmcpy.server.api.create_llm_provider",
                return_value=make_fake_provider(init_error=ValueError("API key missing")),
            ),
            patch("testmcpy.server.api.get_mcp_client_for_server", relogin_client),
        ):
            res = client.post("/api/chat", json=CHAT_BODY)
        assert res.status_code == 500
        assert "API key missing" in res.json()["detail"]
        # Awaited once by the endpoint's normal client resolution — no re-login.
        assert relogin_client.await_count == 1

    def test_flag_on_tool_execution_uses_refreshed_client(self, client, monkeypatch):
        """After re-login the old clients are closed; tools must run on the new ones."""
        monkeypatch.delenv("TESTMCPY_CHAT_OAUTH_LOGIN", raising=False)  # default ON

        tool = MagicMock()
        tool.name = "health_check"
        tool.description = "Check health"
        tool.input_schema = {"type": "object", "properties": {}}

        tool_result = MagicMock()
        tool_result.content = "OK"
        tool_result.is_error = False
        tool_result.error_message = None

        old_client = AsyncMock()
        old_client.base_url = "http://mock-mcp:3000/mcp"
        old_client.auth_config = {"type": "oauth", "oauth_auto_discover": True}
        old_client.list_tools.return_value = [tool]
        new_client = AsyncMock()
        new_client.base_url = "http://mock-mcp:3000/mcp"
        new_client.auth_config = {"type": "oauth", "oauth_auto_discover": True}
        new_client.call_tool.return_value = tool_result

        failing = make_fake_provider(init_error=OAUTH_ERROR)
        working = make_fake_provider()
        working.generate_with_tools.return_value = SimpleNamespace(
            response="done",
            tool_calls=[{"name": "health_check", "arguments": {}, "id": "tc1"}],
            thinking=None,
            token_usage=None,
            cost=0.0,
            duration=0.1,
        )
        with (
            patch(
                "testmcpy.server.api.create_llm_provider",
                side_effect=[failing, working],
            ),
            patch(
                "testmcpy.server.api.get_mcp_client_for_server",
                AsyncMock(side_effect=[old_client, new_client]),
            ),
        ):
            res = client.post("/api/chat", json=CHAT_BODY)
        assert res.status_code == 200
        new_client.call_tool.assert_awaited_once()
        old_client.call_tool.assert_not_awaited()


class TestReloginBackoffInterplay:
    """_relogin_oauth_servers must clear back-off so the reconnect is immediate."""

    def test_relogin_clears_backoff(self, client):
        import asyncio

        from testmcpy.server import api as api_module

        api_module._record_failure("p:m")
        assert api_module._backoff_remaining("p:m") > 0
        with patch("testmcpy.server.api.get_mcp_client_for_server", AsyncMock()):
            asyncio.run(api_module._relogin_oauth_servers(["p:m"]))
        assert api_module._backoff_remaining("p:m") == 0.0

    def test_clear_cached_client_default_still_records_backoff(self, client, mock_mcp_client):
        import asyncio

        from testmcpy.server import api as api_module

        api_module._connection_backoff.pop("test:Test MCP", None)
        assert asyncio.run(api_module.clear_cached_client("test:Test MCP")) is True
        assert api_module._backoff_remaining("test:Test MCP") > 0
        api_module._connection_backoff.pop("test:Test MCP", None)
