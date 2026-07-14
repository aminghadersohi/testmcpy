"""Tests for MCP profiles and LLM profiles CRUD endpoints."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml


class TestListMCPProfiles:
    """Tests for GET /api/mcp/profiles."""

    def test_list_profiles_returns_200(self, client):
        resp = client.get("/api/mcp/profiles")
        assert resp.status_code == 200

    def test_list_profiles_has_profiles_key(self, client):
        resp = client.get("/api/mcp/profiles")
        data = resp.json()
        assert "profiles" in data

    def test_list_profiles_has_default_key(self, client):
        resp = client.get("/api/mcp/profiles")
        data = resp.json()
        assert "default" in data

    def test_list_profiles_contains_test_profile(self, client):
        resp = client.get("/api/mcp/profiles")
        data = resp.json()
        profile_ids = [p["id"] for p in data["profiles"]]
        assert "test" in profile_ids

    def test_list_profiles_default_is_test(self, client):
        resp = client.get("/api/mcp/profiles")
        data = resp.json()
        assert data["default"] == "test"

    def test_list_profiles_profile_has_mcps(self, client):
        resp = client.get("/api/mcp/profiles")
        data = resp.json()
        test_profile = next(p for p in data["profiles"] if p["id"] == "test")
        assert "mcps" in test_profile
        assert len(test_profile["mcps"]) == 1

    def test_list_profiles_mcp_has_name_and_url(self, client):
        resp = client.get("/api/mcp/profiles")
        data = resp.json()
        test_profile = next(p for p in data["profiles"] if p["id"] == "test")
        mcp = test_profile["mcps"][0]
        assert mcp["name"] == "Test MCP"
        assert mcp["mcp_url"] == "http://mock:3000/mcp"

    def test_list_profiles_mcp_has_auth(self, client):
        resp = client.get("/api/mcp/profiles")
        data = resp.json()
        test_profile = next(p for p in data["profiles"] if p["id"] == "test")
        mcp = test_profile["mcps"][0]
        assert "auth" in mcp
        assert mcp["auth"]["type"] == "none"

    def test_list_profiles_round_trips_ssl_and_oauth_flags(self, client):
        update = client.put(
            "/api/mcp/profiles/test/mcps/0",
            json={
                "auth": {
                    "type": "oauth",
                    "oauth_auto_discover": True,
                    "insecure": True,
                }
            },
        )
        assert update.status_code == 200

        response = client.get("/api/mcp/profiles")
        mcp = next(profile for profile in response.json()["profiles"] if profile["id"] == "test")[
            "mcps"
        ][0]
        assert mcp["auth"]["insecure"] is True
        assert mcp["auth"]["oauth_auto_discover"] is True

    def test_list_profiles_default_selection(self, client):
        resp = client.get("/api/mcp/profiles")
        data = resp.json()
        assert "default_selection" in data


class TestProfileAuth:
    """Sensitive auth configuration is only available through POST."""

    def test_profile_auth_post(self, client):
        resp = client.post("/api/mcp/profiles/test/auth")
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-store"
        assert resp.json()["type"] == "none"

    def test_profile_auth_get_is_not_allowed(self, client):
        resp = client.get("/api/mcp/profiles/test/auth")
        assert resp.status_code in (404, 405)

    def test_profile_auth_rejects_cross_origin_browser_request(self, client):
        resp = client.post(
            "/api/mcp/profiles/test/auth",
            headers={"Origin": "https://attacker.example"},
        )
        assert resp.status_code == 403


class TestCreateMCPProfile:
    """Tests for POST /api/mcp/profiles."""

    def test_create_profile_success(self, client):
        resp = client.post(
            "/api/mcp/profiles",
            json={"name": "new-profile", "description": "A new profile"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "profile_id" in data

    def test_create_profile_appears_in_list(self, client):
        client.post(
            "/api/mcp/profiles",
            json={"name": "new-profile", "description": "A new profile"},
        )
        resp = client.get("/api/mcp/profiles")
        data = resp.json()
        ids = [p["id"] for p in data["profiles"]]
        assert "new-profile" in ids

    def test_create_profile_set_as_default(self, client):
        client.post(
            "/api/mcp/profiles",
            json={
                "name": "default-profile",
                "description": "",
                "set_as_default": True,
            },
        )
        resp = client.get("/api/mcp/profiles")
        data = resp.json()
        assert data["default"] == "default-profile"

    def test_create_profile_empty_name_rejected(self, client):
        resp = client.post(
            "/api/mcp/profiles",
            json={"name": "", "description": ""},
        )
        assert resp.status_code == 422

    def test_create_profile_invalid_name_rejected(self, client):
        resp = client.post(
            "/api/mcp/profiles",
            json={"name": "has spaces!", "description": ""},
        )
        assert resp.status_code == 422


class TestUpdateMCPProfile:
    """Tests for PUT /api/mcp/profiles/{profile_id}."""

    def test_update_profile_name(self, client):
        resp = client.put(
            "/api/mcp/profiles/test",
            json={"name": "Updated Test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_update_nonexistent_profile(self, client):
        resp = client.put(
            "/api/mcp/profiles/nonexistent",
            json={"name": "Updated"},
        )
        assert resp.status_code == 404

    def test_update_profile_set_default(self, client):
        # Create a second profile first
        client.post(
            "/api/mcp/profiles",
            json={"name": "second-profile"},
        )
        resp = client.put(
            "/api/mcp/profiles/second-profile",
            json={"set_as_default": True},
        )
        assert resp.status_code == 200


class TestDeleteMCPProfile:
    """Tests for DELETE /api/mcp/profiles/{profile_id}."""

    def test_delete_profile_success(self, client):
        # Create, then delete
        client.post("/api/mcp/profiles", json={"name": "to-delete"})
        resp = client.delete("/api/mcp/profiles/to-delete")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_delete_nonexistent_profile(self, client):
        resp = client.delete("/api/mcp/profiles/nonexistent")
        assert resp.status_code == 404

    def test_delete_removes_from_list(self, client):
        client.post("/api/mcp/profiles", json={"name": "to-delete"})
        client.delete("/api/mcp/profiles/to-delete")
        resp = client.get("/api/mcp/profiles")
        ids = [p["id"] for p in resp.json()["profiles"]]
        assert "to-delete" not in ids


class TestDuplicateMCPProfile:
    """Tests for POST /api/mcp/profiles/{profile_id}/duplicate."""

    def test_duplicate_profile_success(self, client):
        resp = client.post("/api/mcp/profiles/test/duplicate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "profile_id" in data

    def test_duplicate_nonexistent_profile(self, client):
        resp = client.post("/api/mcp/profiles/nonexistent/duplicate")
        assert resp.status_code == 404


class TestSetDefaultProfile:
    """Tests for PUT /api/mcp/profiles/default/{profile_id}."""

    def test_set_default_profile(self, client):
        resp = client.put("/api/mcp/profiles/default/test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_set_default_nonexistent(self, client):
        resp = client.put("/api/mcp/profiles/default/nonexistent")
        assert resp.status_code == 404


class TestAddMCPToProfile:
    """Tests for POST /api/mcp/profiles/{profile_id}/mcps."""

    def test_add_mcp_success(self, client):
        resp = client.post(
            "/api/mcp/profiles/test/mcps",
            json={
                "name": "New MCP",
                "mcp_url": "http://new:3000/mcp",
                "auth": {"type": "none"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_add_duplicate_mcp_name_rejected(self, client):
        resp = client.post(
            "/api/mcp/profiles/test/mcps",
            json={
                "name": "Test MCP",
                "mcp_url": "http://new:3000/mcp",
                "auth": {"type": "none"},
            },
        )
        assert resp.status_code == 400

    def test_add_mcp_to_nonexistent_profile(self, client):
        resp = client.post(
            "/api/mcp/profiles/nonexistent/mcps",
            json={
                "name": "New MCP",
                "mcp_url": "http://new:3000/mcp",
                "auth": {"type": "none"},
            },
        )
        assert resp.status_code == 404


class TestMCPProfileConnection:
    """Saved connection tests must retain transport-wide TLS settings."""

    @pytest.mark.parametrize(
        "auth",
        [
            {"type": "none", "insecure": True},
            {"type": "bearer", "token": "test-token", "insecure": True},
            {
                "type": "jwt",
                "api_url": "https://auth.example.test/token",
                "api_token": "test-user",
                "api_secret": "test-secret",
                "insecure": True,
            },
            {
                "type": "oauth",
                "oauth_auto_discover": True,
                "insecure": True,
            },
        ],
        ids=["none", "bearer", "jwt", "oauth"],
    )
    def test_forwards_insecure_for_every_auth_type(self, client, auth):
        update = client.put(
            "/api/mcp/profiles/test/mcps/0",
            json={"auth": auth},
        )
        assert update.status_code == 200

        test_client = AsyncMock()
        test_client.list_tools.return_value = []
        with patch(
            "testmcpy.server.routers.mcp_profiles.MCPClient",
            return_value=test_client,
        ) as client_class:
            response = client.post("/api/mcp/profiles/test/test-connection/0")

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert client_class.call_args.kwargs["auth"]["type"] == auth["type"]
        assert client_class.call_args.kwargs["auth"]["insecure"] is True

    def test_closes_failed_connection_test_client(self, client):
        test_client = AsyncMock()
        test_client.list_tools.side_effect = RuntimeError("tool discovery failed")

        with patch(
            "testmcpy.server.routers.mcp_profiles.MCPClient",
            return_value=test_client,
        ):
            response = client.post("/api/mcp/profiles/test/test-connection/0")

        assert response.status_code == 200
        assert response.json()["success"] is False
        test_client.close.assert_awaited_once()


class TestDeleteMCPFromProfile:
    """Tests for DELETE /api/mcp/profiles/{profile_id}/mcps/{mcp_index}."""

    def test_delete_mcp_success(self, client):
        resp = client.delete("/api/mcp/profiles/test/mcps/0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_delete_mcp_invalid_index(self, client):
        resp = client.delete("/api/mcp/profiles/test/mcps/99")
        assert resp.status_code == 404

    def test_delete_mcp_nonexistent_profile(self, client):
        resp = client.delete("/api/mcp/profiles/nonexistent/mcps/0")
        assert resp.status_code == 404


class TestExportProfile:
    """Tests for GET /api/mcp/profiles/{profile_id}/export."""

    def test_export_profile_success(self, client):
        resp = client.get("/api/mcp/profiles/test/export")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "yaml" in data
        assert "filename" in data

    def test_export_nonexistent_profile(self, client):
        resp = client.get("/api/mcp/profiles/nonexistent/export")
        assert resp.status_code == 404

    def test_get_export_redacts_literal_secrets(self, client):
        client.put(
            "/api/mcp/profiles/test/mcps/0",
            json={"auth": {"type": "bearer", "token": "literal-secret"}},
        )
        resp = client.get("/api/mcp/profiles/test/export")
        assert resp.status_code == 200
        assert "literal-secret" not in resp.json()["yaml"]
        assert "<redacted>" in resp.json()["yaml"]


class TestLLMProfiles:
    """Tests for LLM profile endpoints under /api/llm/profiles."""

    def test_list_llm_profiles_returns_200(self, client):
        resp = client.get("/api/llm/profiles")
        assert resp.status_code == 200

    def test_list_llm_profiles_has_profiles_key(self, client):
        resp = client.get("/api/llm/profiles")
        data = resp.json()
        assert "profiles" in data

    def test_agent_rejects_explicit_missing_llm_profile(self, client):
        response = client.post(
            "/api/agent/run",
            json={"prompt": "Run tests", "llm_profile": "missing"},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "LLM profile 'missing' was not found"

    def test_agent_rejects_configured_unset_claude_token(self, client, monkeypatch):
        monkeypatch.delenv("MISSING_CLAUDE_AGENT_TOKEN", raising=False)
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    providers:
      - name: Claude agent
        provider: claude-sdk
        model: agent-model
        api_key_env: MISSING_CLAUDE_AGENT_TOKEN
        default: true
"""
        )

        response = client.post(
            "/api/agent/run",
            json={"prompt": "Run tests", "llm_profile": "prod"},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == (
            "LLM profile 'prod' has a configured API key that resolved to an empty value"
        )

    def test_agent_keyless_claude_profile_uses_host_login(self, client, monkeypatch):
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    providers:
      - name: Claude agent
        provider: claude-sdk
        model: agent-model
        default: true
"""
        )
        captured = {}

        class FakeReport:
            run_id = "agent_keyless"

            def to_dict(self):
                return {"run_id": self.run_id, "analysis": "safe"}

        class FakeAgent:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            async def run(self, _prompt):
                return FakeReport()

        monkeypatch.setattr("testmcpy.agent.orchestrator.TestExecutionAgent", FakeAgent)

        response = client.post(
            "/api/agent/run",
            json={"prompt": "Run tests", "llm_profile": "prod"},
        )

        assert response.status_code == 200
        assert captured["cli_token"] is None

    def test_agent_scrubs_profile_token_from_response_and_saved_report(
        self,
        client,
        monkeypatch,
    ):
        secret = "literal-api-agent-credential"
        Path(".llm_providers.yaml").write_text(
            f"""
profiles:
  prod:
    name: Production
    providers:
      - name: Claude agent
        provider: claude-sdk
        model: agent-model
        api_key: {secret}
        default: true
"""
        )
        captured = {}

        class FakeReport:
            run_id = "agent_scrubbed"

            def to_dict(self):
                return {
                    "run_id": self.run_id,
                    "analysis": f"upstream echoed {secret}",
                }

        class FakeAgent:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            async def run(self, _prompt):
                return FakeReport()

        from testmcpy.scrubber import REDACTED, reset_cache

        monkeypatch.setattr("testmcpy.agent.orchestrator.TestExecutionAgent", FakeAgent)
        reset_cache()
        try:
            response = client.post(
                "/api/agent/run",
                json={"prompt": "Run tests", "llm_profile": "prod"},
            )

            assert response.status_code == 200
            assert captured["cli_token"] == secret
            assert secret not in response.text
            assert response.json()["report"]["analysis"] == f"upstream echoed {REDACTED}"
            report_path = Path("tests/.agent_reports/agent_scrubbed.json")
            assert secret not in report_path.read_text()
            assert REDACTED in report_path.read_text()
        finally:
            reset_cache()

    def test_agent_scrubs_profile_token_from_connection_error(self, client, monkeypatch):
        secret = "literal-api-agent-error-credential"
        Path(".llm_providers.yaml").write_text(
            f"""
profiles:
  prod:
    name: Production
    providers:
      - name: Claude agent
        provider: claude-sdk
        model: agent-model
        api_key: {secret}
        default: true
"""
        )

        class FakeAgent:
            def __init__(self, **_kwargs):
                pass

            async def run(self, _prompt):
                raise ConnectionError(f"upstream echoed {secret}")

        from testmcpy.scrubber import REDACTED, reset_cache

        monkeypatch.setattr("testmcpy.agent.orchestrator.TestExecutionAgent", FakeAgent)
        reset_cache()
        try:
            response = client.post(
                "/api/agent/run",
                json={"prompt": "Run tests", "llm_profile": "prod"},
            )

            assert response.status_code == 200
            assert secret not in response.text
            assert response.json()["error"] == f"Connection error: upstream echoed {REDACTED}"
        finally:
            reset_cache()

    def test_list_masks_secrets_and_disables_caching(self, client, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "resolved-secret-must-not-leak")
        Path(".llm_providers.yaml").write_text(
            """
default: prod
profiles:
  prod:
    name: Production
    description: Test
    providers:
      - name: Assistant
        provider: assistant
        model: assistant-model
        api_key: ${OPENAI_API_KEY}
        workspace_hash: workspace-1
        domain: example.test
        api_token: literal-token
        api_secret: literal-secret
        api_url: https://example.test/auth
        conversations_path: /conversations
        completions_path: /completions
        custom_token: future-secret
        custom_option: retained
        default: true
"""
        )

        resp = client.get("/api/llm/profiles")

        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-store"
        provider = resp.json()["profiles"][0]["providers"][0]
        assert provider["api_key"] == "${OPENAI_API_KEY}"
        assert provider["api_token"] == "***"
        assert provider["api_secret"] == "***"
        assert provider["workspace_hash"] == "workspace-1"
        assert provider["conversations_path"] == "/conversations"
        assert provider["custom_option"] == "retained"
        assert "custom_token" not in provider
        assert "resolved-secret-must-not-leak" not in resp.text
        assert "literal-secret" not in resp.text

    def test_list_handles_unknown_nested_yaml_with_mixed_key_types(self, client):
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    providers:
      - name: Compatible
        provider: openai
        model: gpt-test
        nested:
          1: one
          text: two
"""
        )

        response = client.get("/api/llm/profiles")

        assert response.status_code == 200
        provider = response.json()["profiles"][0]["providers"][0]
        assert provider["nested"] == {"text": "two"}
        assert provider["_config_token"]

    def test_assistant_profile_round_trip_preserves_secrets_and_fields(self, client):
        Path(".llm_providers.yaml").write_text(
            """
default: prod
profiles:
  prod:
    name: Production
    description: Before
    providers:
      - name: Assistant
        provider: assistant
        model: assistant-model
        workspace_hash: workspace-1
        domain: example.test
        auth:
          api_token: literal-token
          api_secret: literal-secret
          api_url: https://example.test/auth
          future_auth_option: keep-me
        conversations_path: /conversations
        completions_path: /completions
        future_setting: keep-me
        default: true
"""
        )
        listed = client.get("/api/llm/profiles").json()["profiles"][0]
        listed["description"] = "After"

        resp = client.put("/api/llm/profiles/prod", json=listed)

        assert resp.status_code == 200
        saved = yaml.safe_load(Path(".llm_providers.yaml").read_text())
        provider = saved["profiles"]["prod"]["providers"][0]
        assert provider["api_token"] == "literal-token"
        assert provider["api_secret"] == "literal-secret"
        assert provider["api_url"] == "https://example.test/auth"
        assert provider["workspace_hash"] == "workspace-1"
        assert provider["conversations_path"] == "/conversations"
        assert provider["completions_path"] == "/completions"
        assert provider["future_setting"] == "keep-me"
        assert provider["auth"]["future_auth_option"] == "keep-me"
        assert saved["profiles"]["prod"]["description"] == "After"

    def test_nested_assistant_auth_can_rotate_credentials(self, client):
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    providers:
      - name: Assistant
        provider: assistant
        model: assistant-model
        workspace_hash: workspace-1
        domain: example.test
        api_token: old-token
        api_secret: old-secret
        api_url: https://example.test/auth
        conversations_path: /conversations
        completions_path: /completions
"""
        )

        response = client.put(
            "/api/llm/profiles/prod",
            json={
                "name": "Production",
                "providers": [
                    {
                        "name": "Assistant",
                        "provider": "assistant",
                        "model": "assistant-model",
                        "workspace_hash": "workspace-1",
                        "domain": "example.test",
                        "auth": {
                            "api_token": "new-token",
                            "api_secret": "new-secret",
                            "api_url": "https://example.test/auth",
                        },
                        "conversations_path": "/conversations",
                        "completions_path": "/completions",
                    }
                ],
            },
        )

        assert response.status_code == 200
        provider = yaml.safe_load(Path(".llm_providers.yaml").read_text())["profiles"]["prod"][
            "providers"
        ][0]
        assert provider["api_token"] == "new-token"
        assert provider["api_secret"] == "new-secret"
        assert provider["api_url"] == "https://example.test/auth"

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("api_url", "not-a-url", "absolute HTTP(S) URL"),
            ("conversations_path", "conversations", "same-origin path"),
            ("completions_path", "//attacker.example/collect", "same-origin path"),
        ],
    )
    def test_assistant_api_rejects_unusable_endpoint_values(self, client, field, value, message):
        provider = {
            "name": "Assistant",
            "provider": "assistant",
            "model": "assistant-model",
            "workspace_hash": "workspace-1",
            "domain": "example.test",
            "api_token": "token-value",
            "api_secret": "secret-value",
            "api_url": "https://example.test/auth",
            "conversations_path": "/conversations",
            "completions_path": "/completions",
        }
        provider[field] = value

        response = client.post(
            "/api/llm/profiles/assistant",
            json={"name": "Assistant", "providers": [provider]},
        )

        assert response.status_code == 400
        assert message in response.json()["detail"]
        assert not Path(".llm_providers.yaml").exists()

    def test_assistant_path_change_cannot_reuse_masked_credentials(self, client):
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    providers:
      - name: Assistant
        provider: assistant
        model: assistant-model
        workspace_hash: trusted
        domain: example.test
        api_token: saved-token
        api_secret: saved-secret
        api_url: https://example.test/auth
        conversations_path: /conversations
        completions_path: /completions
"""
        )
        listed = client.get("/api/llm/profiles").json()["profiles"][0]
        listed["providers"][0]["conversations_path"] = "//attacker.example/collect"

        response = client.put("/api/llm/profiles/prod", json=listed)

        assert response.status_code == 400
        saved = yaml.safe_load(Path(".llm_providers.yaml").read_text())["profiles"]["prod"][
            "providers"
        ][0]
        assert saved["conversations_path"] == "/conversations"
        assert saved["api_token"] == "saved-token"

    def test_deleting_first_provider_does_not_move_its_secret_to_the_next(self, client):
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    description: Test
    providers:
      - name: Duplicate
        provider: openai
        model: same-model
        api_key: first-secret
      - name: Duplicate
        provider: openai
        model: same-model
        api_key: second-secret
"""
        )
        profile = client.get("/api/llm/profiles").json()["profiles"][0]
        profile["providers"] = profile["providers"][1:]

        resp = client.put("/api/llm/profiles/prod", json=profile)

        assert resp.status_code == 200
        providers = yaml.safe_load(Path(".llm_providers.yaml").read_text())["profiles"]["prod"][
            "providers"
        ]
        assert len(providers) == 1
        assert providers[0]["name"] == "Duplicate"
        assert providers[0]["api_key"] == "second-secret"

    def test_create_rejects_duplicate_profile_without_overwriting(self, client):
        body = {"name": "First", "description": "", "providers": []}
        assert client.post("/api/llm/profiles/duplicate", json=body).status_code == 200

        resp = client.post(
            "/api/llm/profiles/duplicate",
            json={"name": "Replacement", "description": "", "providers": []},
        )

        assert resp.status_code == 409
        saved = yaml.safe_load(Path(".llm_providers.yaml").read_text())
        assert saved["profiles"]["duplicate"]["name"] == "First"

    def test_profile_mutation_rejects_cross_origin_browser(self, client):
        resp = client.post(
            "/api/llm/profiles/cross-origin",
            json={"name": "Blocked", "description": "", "providers": []},
            headers={"Origin": "https://attacker.example"},
        )
        assert resp.status_code == 403
        assert not Path(".llm_providers.yaml").exists()

    def test_dns_rebinding_host_cannot_inject_and_read_environment_values(
        self, client, monkeypatch
    ):
        monkeypatch.setenv("DATABASE_PASSWORD", "must-not-be-exposed")

        created = client.post(
            "/api/llm/profiles/rebinding",
            json={"name": "${DATABASE_PASSWORD}", "description": "", "providers": []},
            headers={
                "Host": "attacker.example:8000",
                "Origin": "http://attacker.example:8000",
            },
        )
        listed = client.get(
            "/api/llm/profiles",
            headers={"Host": "attacker.example:8000"},
        )

        assert created.status_code == 400
        assert listed.status_code == 400
        assert "must-not-be-exposed" not in created.text
        assert "must-not-be-exposed" not in listed.text
        assert not Path(".llm_providers.yaml").exists()

    def test_custom_allowed_host_is_explicitly_configurable(self, client, monkeypatch):
        monkeypatch.setenv("TESTMCPY_ALLOWED_HOSTS", "internal.example")

        response = client.get(
            "/api/llm/profiles",
            headers={"Host": "internal.example:8443"},
        )

        assert response.status_code == 200

    def test_explicitly_allowed_custom_host_trusts_only_its_exact_origin(self, client, monkeypatch):
        monkeypatch.setenv("TESTMCPY_ALLOWED_HOSTS", "attacker.example")

        response = client.post(
            "/api/llm/profiles/custom-host",
            json={"name": "Allowed", "description": "", "providers": []},
            headers={
                "Host": "attacker.example:8000",
                "Origin": "http://attacker.example:8000",
            },
        )

        assert response.status_code == 200

        denied = client.post(
            "/api/llm/profiles/different-origin",
            json={"name": "Blocked", "description": "", "providers": []},
            headers={
                "Host": "attacker.example:8000",
                "Origin": "https://different.example",
            },
        )

        assert denied.status_code == 403
        saved = yaml.safe_load(Path(".llm_providers.yaml").read_text())
        assert "different-origin" not in saved["profiles"]

    @pytest.mark.parametrize("field", ["name", "description"])
    def test_profile_mutation_rejects_new_public_environment_references(
        self, client, monkeypatch, field
    ):
        monkeypatch.setenv("DATABASE_PASSWORD", "must-not-be-exposed")
        body = {"name": "Safe", "description": "Safe", "providers": []}
        body[field] = "${DATABASE_PASSWORD}"

        response = client.post("/api/llm/profiles/env-injection", json=body)

        assert response.status_code == 400
        assert "cannot add an environment reference" in response.json()["detail"]
        assert "must-not-be-exposed" not in response.text
        assert not Path(".llm_providers.yaml").exists()

    @pytest.mark.parametrize(
        "field",
        [
            "name",
            "model",
            "api_key_env",
            "base_url",
            "workspace_hash",
            "domain",
            "api_url",
            "conversations_path",
            "completions_path",
        ],
    )
    def test_provider_mutation_rejects_new_public_environment_references(
        self, client, monkeypatch, field
    ):
        monkeypatch.setenv("DATABASE_PASSWORD", "must-not-be-exposed")
        provider = {
            "name": "OpenAI",
            "provider": "openai",
            "model": "gpt-test",
        }
        provider[field] = "${DATABASE_PASSWORD}"

        response = client.post(
            "/api/llm/profiles/provider-env-injection",
            json={"name": "Safe", "description": "", "providers": [provider]},
        )

        assert response.status_code == 400
        assert "cannot add an environment reference" in response.json()["detail"]
        assert "must-not-be-exposed" not in response.text
        assert not Path(".llm_providers.yaml").exists()

    @pytest.mark.parametrize("field", ["name", "description"])
    def test_profile_update_rejects_new_public_environment_references(
        self, client, monkeypatch, field
    ):
        monkeypatch.setenv("DATABASE_PASSWORD", "must-not-be-exposed")
        original = {"name": "Safe", "description": "Safe", "providers": []}
        assert client.post("/api/llm/profiles/safe", json=original).status_code == 200
        updated = client.get("/api/llm/profiles").json()["profiles"][0]
        updated[field] = "${DATABASE_PASSWORD}"

        response = client.put("/api/llm/profiles/safe", json=updated)

        assert response.status_code == 400
        assert "cannot add an environment reference" in response.json()["detail"]
        saved = yaml.safe_load(Path(".llm_providers.yaml").read_text())["profiles"]["safe"]
        assert saved[field] == original[field]

    @pytest.mark.parametrize(
        "field",
        [
            "name",
            "model",
            "api_key_env",
            "base_url",
            "workspace_hash",
            "domain",
            "api_url",
            "conversations_path",
            "completions_path",
        ],
    )
    def test_provider_update_rejects_new_public_environment_references(
        self, client, monkeypatch, field
    ):
        monkeypatch.setenv("DATABASE_PASSWORD", "must-not-be-exposed")
        provider = {"name": "OpenAI", "provider": "openai", "model": "gpt-test"}
        original = {
            "name": "Safe",
            "description": "",
            "providers": [provider],
        }
        assert client.post("/api/llm/profiles/safe", json=original).status_code == 200
        updated = client.get("/api/llm/profiles").json()["profiles"][0]
        updated["providers"][0][field] = "${DATABASE_PASSWORD}"

        response = client.put("/api/llm/profiles/safe", json=updated)

        assert response.status_code == 400
        assert "cannot add an environment reference" in response.json()["detail"]
        saved = yaml.safe_load(Path(".llm_providers.yaml").read_text())["profiles"]["safe"]
        assert saved["providers"][0].get(field) == provider.get(field)

    def test_explicit_wildcard_origin_allows_llm_mutation(self, client, monkeypatch):
        monkeypatch.setenv("TESTMCPY_CORS_ORIGINS", "*")

        resp = client.post(
            "/api/llm/profiles/wildcard",
            json={"name": "Allowed", "description": "", "providers": []},
            headers={"Origin": "https://configured-client.example"},
        )

        assert resp.status_code == 200

    def test_ipv6_vite_origin_is_allowed_by_default(self, client, monkeypatch):
        monkeypatch.delenv("TESTMCPY_CORS_ORIGINS", raising=False)

        resp = client.post(
            "/api/llm/profiles/ipv6-client",
            json={"name": "Allowed", "description": "", "providers": []},
            headers={"Origin": "http://[::1]:3000"},
        )

        assert resp.status_code == 200

    def test_malformed_config_is_reported_and_never_overwritten(self, client):
        malformed = "profiles:\n  prod:\n    providers:\n      - null\n"
        Path(".llm_providers.yaml").write_text(malformed)

        listed = client.get("/api/llm/profiles")
        created = client.post(
            "/api/llm/profiles/replacement",
            json={"name": "Replacement", "description": "", "providers": []},
        )

        assert listed.status_code == 409
        assert "Invalid .llm_providers.yaml" in listed.json()["detail"]
        assert created.status_code == 409
        assert Path(".llm_providers.yaml").read_text() == malformed

    def test_profile_and_provider_validation(self, client):
        invalid_id = client.post(
            "/api/llm/profiles/INVALID!",
            json={"name": "Invalid", "description": "", "providers": []},
        )
        invalid_timeout = client.post(
            "/api/llm/profiles/valid",
            json={
                "name": "Valid",
                "description": "",
                "providers": [
                    {
                        "name": "Provider",
                        "provider": "openai",
                        "model": "gpt-test",
                        "timeout": -1,
                    }
                ],
            },
        )
        assert invalid_id.status_code == 422
        assert invalid_timeout.status_code == 422

    def test_unknown_credentials_are_not_exposed_but_survive_update(self, client):
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    providers:
      - name: Compatible
        provider: openai
        model: gpt-test
        headers:
          Authorization: Bearer hidden
          X-Custom: hidden-too
        private_key: private-value
        accessKey: access-value
        x-api-key: top-level-key
        harmless_setting: keep-visible
"""
        )

        listed = client.get("/api/llm/profiles").json()["profiles"][0]
        public_provider = listed["providers"][0]
        assert "headers" not in public_provider
        assert "private_key" not in public_provider
        assert "accessKey" not in public_provider
        assert "x-api-key" not in public_provider
        assert public_provider["harmless_setting"] == "keep-visible"

        response = client.put("/api/llm/profiles/prod", json=listed)

        assert response.status_code == 200
        saved_provider = yaml.safe_load(Path(".llm_providers.yaml").read_text())["profiles"][
            "prod"
        ]["providers"][0]
        assert saved_provider["headers"]["Authorization"] == "Bearer hidden"
        assert saved_provider["headers"]["X-Custom"] == "hidden-too"
        assert saved_provider["private_key"] == "private-value"
        assert saved_provider["accessKey"] == "access-value"
        assert saved_provider["x-api-key"] == "top-level-key"

    def test_secret_environment_default_is_masked_and_preserved(self, client):
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-test
        api_key: ${OPENAI_API_KEY:-literal-fallback-secret}
"""
        )

        listed = client.get("/api/llm/profiles").json()["profiles"][0]
        assert listed["providers"][0]["api_key"] == "***"

        response = client.put("/api/llm/profiles/prod", json=listed)

        assert response.status_code == 200
        saved_provider = yaml.safe_load(Path(".llm_providers.yaml").read_text())["profiles"][
            "prod"
        ]["providers"][0]
        assert saved_provider["api_key"] == "${OPENAI_API_KEY:-literal-fallback-secret}"

    def test_list_resolves_environment_referenced_default(self, client, monkeypatch):
        monkeypatch.setenv("LLM_DEFAULT_PROFILE", "prod")
        Path(".llm_providers.yaml").write_text(
            """
default: ${LLM_DEFAULT_PROFILE}
profiles:
  prod:
    name: Production
    providers: []
"""
        )

        response = client.get("/api/llm/profiles")

        assert response.status_code == 200
        assert response.json()["default"] == "prod"
        assert "${LLM_DEFAULT_PROFILE}" in Path(".llm_providers.yaml").read_text()

    def test_saved_masked_provider_test_uses_stored_secret(self, client, monkeypatch):
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    description: Test
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-test
        api_key: saved-secret
"""
        )
        test_connection = AsyncMock(
            return_value={"success": True, "tested": True, "duration": 0.01, "response": "ok"}
        )
        monkeypatch.setattr(
            "testmcpy.llm_testing.test_llm_provider_connection",
            test_connection,
        )

        resp = client.post(
            "/api/llm/test",
            json={
                "provider": "openai",
                "model": "gpt-test",
                "api_key": "***",
                "profile_id": "prod",
                "provider_index": 0,
            },
        )

        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert test_connection.await_args.kwargs["api_key"] == "saved-secret"

    def test_ad_hoc_test_cannot_send_server_key_to_custom_url(self, client, monkeypatch):
        test_connection = AsyncMock()
        monkeypatch.setattr(
            "testmcpy.llm_testing.test_llm_provider_connection",
            test_connection,
        )

        response = client.post(
            "/api/llm/test",
            json={
                "provider": " OpenAI ",
                "model": "gpt-test",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://attacker.example/v1",
            },
        )

        assert response.status_code == 400
        test_connection.assert_not_awaited()

    def test_ad_hoc_test_rejects_arbitrary_environment_name(self, client, monkeypatch):
        test_connection = AsyncMock()
        monkeypatch.setattr(
            "testmcpy.llm_testing.test_llm_provider_connection",
            test_connection,
        )

        response = client.post(
            "/api/llm/test",
            json={
                "provider": "openai",
                "model": "gpt-test",
                "api_key_env": "DATABASE_PASSWORD",
            },
        )

        assert response.status_code == 400
        test_connection.assert_not_awaited()

    def test_ad_hoc_test_allows_caller_key_with_custom_url(self, client, monkeypatch):
        test_connection = AsyncMock(return_value={"success": True, "tested": True})
        monkeypatch.setattr(
            "testmcpy.llm_testing.test_llm_provider_connection",
            test_connection,
        )

        response = client.post(
            "/api/llm/test",
            json={
                "provider": "openai",
                "model": "gpt-test",
                "api_key": "caller-owned-key",
                "base_url": "https://compatible.example/v1",
            },
        )

        assert response.status_code == 200
        assert test_connection.await_args.kwargs["api_key"] == "caller-owned-key"

    def test_forged_provider_index_cannot_transplant_secret(self, client):
        original = """
profiles:
  prod:
    name: Production
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-test
        api_key: saved-secret
"""
        Path(".llm_providers.yaml").write_text(original)
        listed = client.get("/api/llm/profiles").json()["profiles"][0]
        listed["providers"][0]["base_url"] = "https://attacker.example/v1"

        response = client.put("/api/llm/profiles/prod", json=listed)

        assert response.status_code == 400
        saved = yaml.safe_load(Path(".llm_providers.yaml").read_text())
        provider = saved["profiles"]["prod"]["providers"][0]
        assert provider["api_key"] == "saved-secret"
        assert "base_url" not in provider

    def test_forged_index_cannot_swap_same_provider_secrets(self, client):
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    providers:
      - name: Provider A
        provider: openai
        model: model-a
        api_key: secret-a
      - name: Provider B
        provider: openai
        model: model-b
        api_key: secret-b
"""
        )
        listed = client.get("/api/llm/profiles").json()["profiles"][0]
        provider_a = listed["providers"][0]
        provider_a["_config_index"] = 1
        listed["providers"] = [provider_a]

        response = client.put("/api/llm/profiles/prod", json=listed)

        assert response.status_code == 409
        saved_providers = yaml.safe_load(Path(".llm_providers.yaml").read_text())["profiles"][
            "prod"
        ]["providers"]
        assert [provider["api_key"] for provider in saved_providers] == ["secret-a", "secret-b"]

    def test_stale_revision_cannot_erase_redacted_unknown_credentials(self, client):
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    providers:
      - name: Local
        provider: ollama
        model: llama3
        headers:
          Authorization: Bearer saved-secret
"""
        )
        listed = client.get("/api/llm/profiles").json()["profiles"][0]
        assert "headers" not in listed["providers"][0]
        changed = yaml.safe_load(Path(".llm_providers.yaml").read_text())
        changed["profiles"]["prod"]["providers"][0]["timeout"] = 61
        Path(".llm_providers.yaml").write_text(yaml.safe_dump(changed, sort_keys=False))

        response = client.put("/api/llm/profiles/prod", json=listed)

        assert response.status_code == 409
        saved_provider = yaml.safe_load(Path(".llm_providers.yaml").read_text())["profiles"][
            "prod"
        ]["providers"][0]
        assert saved_provider["headers"]["Authorization"] == "Bearer saved-secret"

    def test_assistant_workspace_change_cannot_reuse_masked_secrets(self, client):
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    providers:
      - name: Assistant
        provider: assistant
        model: assistant
        workspace_hash: trusted
        domain: example.test
        api_token: saved-token
        api_secret: saved-secret
"""
        )
        listed = client.get("/api/llm/profiles").json()["profiles"][0]
        listed["providers"][0]["workspace_hash"] = "attacker"

        response = client.put("/api/llm/profiles/prod", json=listed)

        assert response.status_code == 400
        saved_provider = yaml.safe_load(Path(".llm_providers.yaml").read_text())["profiles"][
            "prod"
        ]["providers"][0]
        assert saved_provider["workspace_hash"] == "trusted"
        assert saved_provider["api_token"] == "saved-token"

    @pytest.mark.parametrize(
        ("field", "value"),
        [("name", "Renamed Provider"), ("model", "gpt-new")],
    )
    def test_masked_secret_survives_legitimate_provider_metadata_edit(
        self,
        client,
        field,
        value,
    ):
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-old
        api_key: saved-secret
"""
        )
        listed = client.get("/api/llm/profiles").json()["profiles"][0]
        listed["providers"][0][field] = value

        response = client.put("/api/llm/profiles/prod", json=listed)

        assert response.status_code == 200
        saved_provider = yaml.safe_load(Path(".llm_providers.yaml").read_text())["profiles"][
            "prod"
        ]["providers"][0]
        assert saved_provider[field] == value
        assert saved_provider["api_key"] == "saved-secret"

    def test_ui_noop_edit_preserves_direct_key_and_hidden_provider_fields(self, client):
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-test
        api_key: saved-secret
        custom_token: hidden-future-secret
        custom_option: keep-me
        default: true
"""
        )
        listed = client.get("/api/llm/profiles").json()["profiles"][0]
        provider = listed["providers"][0]
        assert "custom_token" not in provider
        assert provider["_config_token"]

        # ProviderEditorModal keeps fields absent from GET as null instead of
        # changing their meaning to an explicit empty destination.
        provider.update({"api_key_env": None, "base_url": None})
        response = client.put("/api/llm/profiles/prod", json=listed)

        assert response.status_code == 200
        saved_provider = yaml.safe_load(Path(".llm_providers.yaml").read_text())["profiles"][
            "prod"
        ]["providers"][0]
        assert saved_provider["api_key"] == "saved-secret"
        assert saved_provider["custom_token"] == "hidden-future-secret"
        assert saved_provider["custom_option"] == "keep-me"
        assert "api_key_env" not in saved_provider
        assert "base_url" not in saved_provider

    def test_blank_direct_key_does_not_override_environment_key_at_runtime(
        self,
        client,
        monkeypatch,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-test
        api_key_env: OPENAI_API_KEY
"""
        )
        listed = client.get("/api/llm/profiles").json()["profiles"][0]
        listed["providers"][0].update({"api_key": "", "base_url": "  "})

        response = client.put("/api/llm/profiles/prod", json=listed)

        assert response.status_code == 200
        saved_provider = yaml.safe_load(Path(".llm_providers.yaml").read_text())["profiles"][
            "prod"
        ]["providers"][0]
        assert "api_key" not in saved_provider
        assert "base_url" not in saved_provider
        assert saved_provider["api_key_env"] == "OPENAI_API_KEY"

        from testmcpy.llm_profiles import resolve_llm_provider_config

        runtime = resolve_llm_provider_config("openai", "gpt-test", "prod")
        assert runtime["api_key"] == "environment-secret"
        assert runtime["api_key_env"] == "OPENAI_API_KEY"

    def test_legacy_profile_id_can_be_updated_and_deleted(self, client):
        Path(".llm_providers.yaml").write_text(
            """
default: Production_1.0
profiles:
  Production_1.0:
    name: Legacy
    providers: []
"""
        )
        listed = client.get("/api/llm/profiles").json()["profiles"][0]
        listed["description"] = "Updated"

        updated = client.put("/api/llm/profiles/Production_1.0", json=listed)
        deleted = client.delete("/api/llm/profiles/Production_1.0")

        assert updated.status_code == 200
        assert deleted.status_code == 200

    def test_environment_backed_provider_type_round_trips_without_materializing(
        self,
        client,
        monkeypatch,
    ):
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    providers:
      - name: OpenAI
        provider: ${LLM_PROVIDER}
        model: gpt-test
        api_key: saved-secret
"""
        )
        listed = client.get("/api/llm/profiles").json()["profiles"][0]

        assert listed["providers"][0]["provider"] == "openai"
        response = client.put("/api/llm/profiles/prod", json=listed)

        assert response.status_code == 200
        saved_provider = yaml.safe_load(Path(".llm_providers.yaml").read_text())["profiles"][
            "prod"
        ]["providers"][0]
        assert saved_provider["provider"] == "${LLM_PROVIDER}"
        assert saved_provider["api_key"] == "saved-secret"

    def test_environment_backed_profile_fields_survive_provider_edit(
        self,
        client,
        monkeypatch,
    ):
        monkeypatch.setenv("PROFILE_NAME", "Resolved production")
        monkeypatch.setenv("PROFILE_DESCRIPTION", "Resolved description")
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: ${PROFILE_NAME}
    description: ${PROFILE_DESCRIPTION}
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-test
        timeout: 60
"""
        )

        listed = client.get("/api/llm/profiles").json()["profiles"][0]
        assert listed["name"] == "Resolved production"
        assert listed["description"] == "Resolved description"
        listed["providers"][0]["timeout"] = 90

        response = client.put("/api/llm/profiles/prod", json=listed)

        assert response.status_code == 200
        saved = yaml.safe_load(Path(".llm_providers.yaml").read_text())["profiles"]["prod"]
        assert saved["name"] == "${PROFILE_NAME}"
        assert saved["description"] == "${PROFILE_DESCRIPTION}"
        assert saved["providers"][0]["timeout"] == 90

    def test_environment_backed_model_is_resolved_for_ui_and_preserved_on_put(
        self,
        client,
        monkeypatch,
    ):
        monkeypatch.setenv("LLM_MODEL", "gpt-resolved")
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    providers:
      - name: OpenAI
        provider: openai
        model: ${LLM_MODEL}
        api_key: saved-secret
"""
        )

        listed = client.get("/api/llm/profiles").json()["profiles"][0]
        assert listed["providers"][0]["model"] == "gpt-resolved"

        response = client.put("/api/llm/profiles/prod", json=listed)

        assert response.status_code == 200
        saved_provider = yaml.safe_load(Path(".llm_providers.yaml").read_text())["profiles"][
            "prod"
        ]["providers"][0]
        assert saved_provider["model"] == "${LLM_MODEL}"

    def test_environment_backed_custom_key_name_round_trips_unchanged(
        self,
        client,
        monkeypatch,
    ):
        monkeypatch.setenv("KEY_ENV_NAME", "CUSTOM_LOCAL_KEY")
        monkeypatch.setenv("CUSTOM_LOCAL_KEY", "local-secret")
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    providers:
      - name: Compatible
        provider: openai
        model: gpt-test
        api_key_env: ${KEY_ENV_NAME}
"""
        )

        listed = client.get("/api/llm/profiles").json()["profiles"][0]
        assert listed["providers"][0]["api_key_env"] == "CUSTOM_LOCAL_KEY"
        response = client.put("/api/llm/profiles/prod", json=listed)

        assert response.status_code == 200
        saved = yaml.safe_load(Path(".llm_providers.yaml").read_text())["profiles"]["prod"][
            "providers"
        ][0]
        assert saved["api_key_env"] == "${KEY_ENV_NAME}"

    def test_environment_backed_assistant_binding_round_trips_unchanged(
        self,
        client,
        monkeypatch,
    ):
        monkeypatch.setenv("ASSISTANT_WORKSPACE", "workspace-resolved")
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    providers:
      - name: Assistant
        provider: assistant
        model: assistant-model
        workspace_hash: ${ASSISTANT_WORKSPACE}
        domain: example.test
        api_token: saved-token
        api_secret: saved-secret
        api_url: https://example.test/auth
        conversations_path: /conversations
        completions_path: /completions
"""
        )

        listed = client.get("/api/llm/profiles").json()["profiles"][0]
        assert listed["providers"][0]["workspace_hash"] == "workspace-resolved"
        response = client.put("/api/llm/profiles/prod", json=listed)

        assert response.status_code == 200
        saved = yaml.safe_load(Path(".llm_providers.yaml").read_text())["profiles"]["prod"][
            "providers"
        ][0]
        assert saved["workspace_hash"] == "${ASSISTANT_WORKSPACE}"
        assert saved["api_token"] == "saved-token"

    def test_profile_api_rejects_arbitrary_process_secret_reference(self, client):
        response = client.post(
            "/api/llm/profiles/untrusted-env",
            json={
                "name": "Untrusted",
                "description": "",
                "providers": [
                    {
                        "name": "OpenAI",
                        "provider": "openai",
                        "model": "gpt-test",
                        "api_key_env": "DATABASE_PASSWORD",
                    }
                ],
            },
        )

        assert response.status_code == 400
        assert not Path(".llm_providers.yaml").exists()

    def test_saved_local_custom_env_and_url_can_be_tested(self, client, monkeypatch):
        monkeypatch.setenv("CUSTOM_COMPATIBLE_KEY", "local-secret")
        Path(".llm_providers.yaml").write_text(
            """
profiles:
  prod:
    name: Production
    providers:
      - name: Compatible
        provider: openai
        model: gpt-test
        api_key_env: CUSTOM_COMPATIBLE_KEY
        base_url: https://compatible.example/v1
"""
        )
        test_connection = AsyncMock(return_value={"success": True, "tested": True})
        monkeypatch.setattr(
            "testmcpy.llm_testing.test_llm_provider_connection",
            test_connection,
        )

        response = client.post(
            "/api/llm/test",
            json={
                "provider": "ignored",
                "model": "ignored",
                "profile_id": "prod",
                "provider_index": 0,
            },
        )

        assert response.status_code == 200
        assert test_connection.await_args.kwargs["api_key"] == "local-secret"
        assert test_connection.await_args.kwargs["base_url"] == "https://compatible.example/v1"

        listed = client.get("/api/llm/profiles").json()["profiles"][0]["providers"][0]
        assert listed["api_key_env"] == "CUSTOM_COMPATIBLE_KEY"

    def test_cli_provider_test_is_reported_as_not_tested(self, client):
        resp = client.post(
            "/api/llm/test",
            json={"provider": "claude-sdk", "model": "invalid-model"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert resp.json()["tested"] is False

    def test_cost_estimate_rejects_negative_tokens(self, client):
        resp = client.post(
            "/api/llm/estimate-cost",
            json={"model_id": "claude-sonnet-4-6-20260401", "input_tokens": -1, "output_tokens": 0},
        )
        assert resp.status_code == 422
