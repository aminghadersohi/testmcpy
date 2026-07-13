"""
Unit tests for the standalone /api/mcp/test-connection endpoint (Add MCP wizard).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from testmcpy.src.mcp_client import MCPConnectionError


@pytest.fixture
def client():
    from testmcpy.server.routers.mcp_profiles import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _mock_mcp_client(tools=None, init_error=None):
    instance = AsyncMock()
    if init_error is not None:
        instance.initialize.side_effect = init_error
    instance.list_tools.return_value = tools or []
    return instance


def test_test_connection_success(client):
    tools = [SimpleNamespace(name="list_charts"), SimpleNamespace(name="run_sql")]
    instance = _mock_mcp_client(tools=tools)
    with patch("testmcpy.server.routers.mcp_profiles.MCPClient", return_value=instance) as mock_cls:
        res = client.post(
            "/api/mcp/test-connection",
            json={
                "mcp_url": "https://mcp.example.com/mcp/",
                "transport": "sse",
                "auth": {"type": "bearer", "token": "abc123"},
                "timeout": 10,
            },
        )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["tool_count"] == 2
    assert data["tools"] == ["list_charts", "run_sql"]
    mock_cls.assert_called_once_with(
        "https://mcp.example.com/mcp/",
        auth={
            "type": "bearer",
            "token": "abc123",
            "insecure": False,
            "oauth_auto_discover": False,
        },
    )
    instance.close.assert_awaited()


def test_test_connection_failure_returns_error_payload(client):
    instance = _mock_mcp_client(init_error=MCPConnectionError("connection refused"))
    with patch("testmcpy.server.routers.mcp_profiles.MCPClient", return_value=instance):
        res = client.post(
            "/api/mcp/test-connection",
            json={"mcp_url": "https://mcp.example.com/mcp/", "auth": {"type": "none"}},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is False
    assert "Connection failed" in data["message"]
    instance.close.assert_awaited()


def test_test_connection_stdio_uses_stdio_client(client):
    tools = [SimpleNamespace(name="echo")]
    instance = _mock_mcp_client(tools=tools)
    with patch(
        "testmcpy.server.routers.mcp_profiles.StdioMCPClient", return_value=instance
    ) as mock_cls:
        res = client.post(
            "/api/mcp/test-connection",
            json={
                "mcp_url": "stdio://npx",
                "transport": "stdio",
                "command": "npx",
                "args": ["-y", "some-mcp-server"],
            },
        )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["tools"] == ["echo"]
    mock_cls.assert_called_once_with(command="npx", args=["-y", "some-mcp-server"])


def test_test_connection_stdio_missing_command(client):
    res = client.post(
        "/api/mcp/test-connection",
        json={"mcp_url": "stdio://", "transport": "stdio"},
    )
    assert res.status_code == 400


class TestResolveSecret:
    """Editing an MCP must not wipe its stored secret when the client sends
    back the masked value (regression: token/secret cleared on edit)."""

    def _resolve(self, incoming, existing):
        from testmcpy.server.routers.mcp_profiles import _resolve_secret

        return _resolve_secret(incoming, existing)

    def test_star_mask_preserves_existing(self):
        assert self._resolve("***", "realsecretvalue") == "realsecretvalue"

    def test_truncated_mask_preserves_existing(self):
        existing = "abcdefgh1234567890"  # len > 12
        assert self._resolve(f"{existing[:8]}...", existing) == existing

    def test_none_clears_the_secret(self):
        assert self._resolve(None, "realsecretvalue") is None

    def test_new_value_overwrites(self):
        assert self._resolve("brand-new-token", "old-token") == "brand-new-token"

    def test_star_with_no_existing_is_none(self):
        assert self._resolve("***", None) is None

    def test_env_var_reference_passthrough(self):
        assert self._resolve("${MY_TOKEN}", "${MY_TOKEN}") == "${MY_TOKEN}"


class TestRedactExportSecrets:
    def test_redacts_nested_literal_credentials(self):
        from testmcpy.server.routers.mcp_profiles import _redact_export_secrets

        value = {
            "mcps": [
                {
                    "auth": {
                        "type": "oauth",
                        "client_secret": "secret",
                        "refresh_token": "refresh",
                    }
                }
            ]
        }

        redacted = _redact_export_secrets(value)
        assert redacted["mcps"][0]["auth"]["client_secret"] == "<redacted>"
        assert redacted["mcps"][0]["auth"]["refresh_token"] == "<redacted>"

    def test_preserves_environment_references(self):
        from testmcpy.server.routers.mcp_profiles import _redact_export_secrets

        value = {"auth": {"token": "${MCP_TOKEN}"}}
        assert _redact_export_secrets(value) == value

    def test_redacts_api_keys_and_custom_headers(self):
        from testmcpy.server.routers.mcp_profiles import _redact_export_secrets

        value = {
            "auth": {
                "api_key": "literal-api-key",
                "headers": {
                    "Authorization": "Bearer literal-token",
                    "X-From-Env": "${CUSTOM_HEADER}",
                },
            }
        }
        assert _redact_export_secrets(value) == {
            "auth": {
                "api_key": "<redacted>",
                "headers": {
                    "Authorization": "<redacted>",
                    "X-From-Env": "${CUSTOM_HEADER}",
                },
            }
        }

    def test_malformed_environment_reference_is_redacted(self):
        from testmcpy.server.routers.mcp_profiles import _redact_export_secrets

        value = {"auth": {"token": "${TOKEN}-suffix"}}
        assert _redact_export_secrets(value)["auth"]["token"] == "<redacted>"
