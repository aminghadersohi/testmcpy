"""Regression tests for manual OAuth token refresh and transport rebuilds."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from testmcpy.src.mcp_client import MCPClient, MCPConnectionError, MCPToolCall


@pytest.mark.asyncio
async def test_401_refresh_reconnects_transport_before_retry():
    client = MCPClient("https://mcp.example.com/mcp")
    original = AsyncMock()
    original.call_tool.side_effect = Exception("401 Unauthorized")
    replacement = AsyncMock()
    replacement.call_tool.return_value = SimpleNamespace(content=["ok"], isError=False)
    client.client = original
    client._tools_cache = []
    token_manager = SimpleNamespace(
        refresh=AsyncMock(),
        access_token="refreshed-access-token",
    )
    client._token_manager = token_manager

    async def reconnect(auth, timeout):
        client.client = replacement

    client._connect_with_auth = AsyncMock(side_effect=reconnect)

    result = await client.call_tool(MCPToolCall(name="ping", arguments={}, id="call-1"))

    assert result.is_error is False
    assert result.content == ["ok"]
    token_manager.refresh.assert_awaited_once_with(force=True)
    original.__aexit__.assert_awaited_once()
    client._connect_with_auth.assert_awaited_once()
    refreshed_auth = client._connect_with_auth.await_args.args[0]
    assert refreshed_auth.token == "refreshed-access-token"
    replacement.call_tool.assert_awaited_once_with("ping", {})
    assert client._token_manager is token_manager


@pytest.mark.asyncio
async def test_refresh_reconnect_failure_is_returned_as_tool_error():
    client = MCPClient("https://mcp.example.com/mcp")
    original = AsyncMock()
    original.call_tool.side_effect = Exception("401 Unauthorized")
    client.client = original
    client._token_manager = SimpleNamespace(
        refresh=AsyncMock(),
        access_token="refreshed-access-token",
    )
    client._connect_with_auth = AsyncMock(side_effect=MCPConnectionError("offline"))

    result = await client.call_tool(MCPToolCall(name="ping", arguments={}, id="call-1"))

    assert result.is_error is True
    assert "refresh/reconnect failed" in result.error_message
    assert "offline" in result.error_message
    assert client.client is None


@pytest.mark.asyncio
async def test_tool_call_timeout_includes_waiting_for_refresh_lock():
    client = MCPClient("https://mcp.example.com/mcp")
    client.client = AsyncMock()
    await client._operation_lock.acquire()

    try:
        result = await client.call_tool(
            MCPToolCall(name="ping", arguments={}, id="call-1"), timeout=0.01
        )
    finally:
        client._operation_lock.release()

    assert result.is_error is True
    assert result.error_message == "Tool call 'ping' timed out after 0.01s"
    client.client.call_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_cleans_up_client_when_enter_is_cancelled():
    client = MCPClient("https://mcp.example.com/mcp")
    partial_client = AsyncMock()
    partial_client.__aenter__.side_effect = asyncio.CancelledError

    with patch("testmcpy.src.mcp_client.Client", return_value=partial_client):
        with pytest.raises(asyncio.CancelledError):
            await client._connect_with_auth(None, timeout=1.0)

    partial_client.__aexit__.assert_awaited_once_with(None, None, None)
    assert client.client is None


@pytest.mark.asyncio
async def test_initialize_ping_timeout_closes_connected_client():
    client = MCPClient("https://mcp.example.com/mcp")
    connected_client = AsyncMock()
    connected_client.ping.side_effect = asyncio.TimeoutError

    async def connect(_auth, _timeout):
        client.client = connected_client

    client._setup_auth = AsyncMock(return_value=None)
    client._connect_with_auth = AsyncMock(side_effect=connect)

    with pytest.raises(Exception, match="MCP ping timed out"):
        await client.initialize(timeout=0.01)

    connected_client.__aexit__.assert_awaited_once_with(None, None, None)
    assert client.client is None


@pytest.mark.asyncio
async def test_close_waits_for_active_resource_operation():
    client = MCPClient("https://mcp.example.com/mcp")
    connected_client = AsyncMock()
    operation_started = asyncio.Event()
    finish_operation = asyncio.Event()

    async def list_resources():
        operation_started.set()
        await finish_operation.wait()
        return []

    connected_client.list_resources.side_effect = list_resources
    client.client = connected_client

    resource_task = asyncio.create_task(client.list_resources())
    await operation_started.wait()
    close_task = asyncio.create_task(client.close())
    await asyncio.sleep(0)

    connected_client.__aexit__.assert_not_awaited()
    finish_operation.set()
    assert await resource_task == []
    await close_task

    connected_client.__aexit__.assert_awaited_once_with(None, None, None)
