"""Security regressions for dynamically acquired MCP credentials."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from testmcpy.scrubber import REDACTED, reset_cache, scrub_text
from testmcpy.src.mcp_client import MCPClient, MCPConnectionError, MCPToolCall


@pytest.mark.parametrize(
    ("method_name", "args", "payload"),
    [
        (
            "_fetch_jwt_token",
            ("https://auth.example.com/jwt", "client-name", "client-secret"),
            {"payload": {"access_token": "dynamic-jwt-access-token-12345"}},
        ),
        (
            "_fetch_oauth_token",
            ("client-id", "client-secret", "https://auth.example.com/oauth"),
            {"access_token": "dynamic-oauth-access-token-12345"},
        ),
    ],
)
@pytest.mark.asyncio
async def test_dynamic_mcp_token_fetch_registers_access_token(method_name, args, payload):
    token = payload.get("access_token") or payload["payload"]["access_token"]
    response = Mock(status_code=200, headers={})
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    http_client = AsyncMock()
    http_client.post.return_value = response
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=http_client)
    client_context.__aexit__ = AsyncMock(return_value=None)
    client = MCPClient("https://mcp.example.com/mcp")
    reset_cache()
    try:
        with patch("testmcpy.src.mcp_client.httpx.AsyncClient", return_value=client_context):
            fetched = await getattr(client, method_name)(*args)

        assert fetched == token
        assert scrub_text(f"echo {token}") == f"echo {REDACTED}"
    finally:
        reset_cache()


@pytest.mark.asyncio
@pytest.mark.parametrize(("insecure", "expected_verify"), [(False, True), (True, False)])
async def test_oauth_client_credentials_honors_insecure_tls_flag(
    insecure,
    expected_verify,
):
    response = Mock(status_code=200, headers={})
    response.json.return_value = {"access_token": "oauth-access-token"}
    response.raise_for_status.return_value = None
    http_client = AsyncMock()
    http_client.post.return_value = response
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=http_client)
    client_context.__aexit__ = AsyncMock(return_value=None)
    client = MCPClient(
        "https://mcp.example.com/mcp",
        auth={"type": "oauth", "insecure": insecure},
    )

    with patch(
        "testmcpy.src.mcp_client.httpx.AsyncClient",
        return_value=client_context,
    ) as async_client:
        token = await client._fetch_oauth_token(
            "client-id",
            "client-secret",
            "https://auth.example.com/token",
        )

    assert token == "oauth-access-token"
    async_client.assert_called_once_with(verify=expected_verify)


@pytest.mark.asyncio
async def test_mcp_401_refresh_registers_rotated_access_and_refresh_tokens():
    access_token = "rotated-mcp-access-token-12345"
    refresh_token = "rotated-mcp-refresh-token-12345"
    client = MCPClient("https://mcp.example.com/mcp")
    original = AsyncMock()
    original.call_tool.side_effect = Exception("401 Unauthorized")
    client.client = original
    client._token_manager = SimpleNamespace(
        refresh=AsyncMock(),
        access_token=access_token,
        refresh_token=refresh_token,
    )
    client._connect_with_auth = AsyncMock(side_effect=MCPConnectionError("offline"))
    reset_cache()
    try:
        result = await client.call_tool(MCPToolCall(name="ping", arguments={}, id="call-1"))

        assert result.is_error is True
        assert scrub_text(f"echo {access_token}") == f"echo {REDACTED}"
        assert scrub_text(f"echo {refresh_token}") == f"echo {REDACTED}"
    finally:
        reset_cache()
