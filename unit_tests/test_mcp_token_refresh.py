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
async def test_tool_calls_execute_concurrently():
    client = MCPClient("https://mcp.example.com/mcp")
    connected_client = AsyncMock()
    both_started = asyncio.Event()
    release_calls = asyncio.Event()
    started = 0

    async def call_tool(_name, _arguments):
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await release_calls.wait()
        return SimpleNamespace(content=["ok"], isError=False)

    connected_client.call_tool.side_effect = call_tool
    client.client = connected_client

    tasks = [
        asyncio.create_task(
            client.call_tool(MCPToolCall(name=f"tool-{index}", arguments={}, id=str(index)))
        )
        for index in range(2)
    ]
    await asyncio.wait_for(both_started.wait(), timeout=0.5)
    release_calls.set()
    results = await asyncio.gather(*tasks)

    assert all(not result.is_error for result in results)
    assert connected_client.call_tool.await_count == 2


@pytest.mark.asyncio
async def test_close_has_priority_over_new_tool_calls():
    client = MCPClient("https://mcp.example.com/mcp")
    connected_client = AsyncMock()
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    release_first = asyncio.Event()

    async def call_tool(name, _arguments):
        if name == "first":
            first_started.set()
            await release_first.wait()
        else:
            second_started.set()
        return SimpleNamespace(content=["ok"], isError=False)

    connected_client.call_tool.side_effect = call_tool
    client.client = connected_client

    first_task = asyncio.create_task(
        client.call_tool(MCPToolCall(name="first", arguments={}, id="call-1"))
    )
    await first_started.wait()
    close_task = asyncio.create_task(client.close())
    for _ in range(100):
        if client._lifecycle_guard._waiting_writers:
            break
        await asyncio.sleep(0)
    assert client._lifecycle_guard._waiting_writers == 1

    second_task = asyncio.create_task(
        client.call_tool(MCPToolCall(name="second", arguments={}, id="call-2"))
    )
    await asyncio.sleep(0)
    assert not second_started.is_set()

    release_first.set()
    assert (await first_task).is_error is False
    await close_task
    second_result = await second_task

    assert second_result.is_error is True
    assert "not initialized" in second_result.error_message
    assert not second_started.is_set()


@pytest.mark.asyncio
async def test_cancelled_tool_call_releases_lifecycle_lease():
    client = MCPClient("https://mcp.example.com/mcp")
    connected_client = AsyncMock()
    call_started = asyncio.Event()
    never_finish = asyncio.Event()

    async def call_tool(_name, _arguments):
        call_started.set()
        await never_finish.wait()

    connected_client.call_tool.side_effect = call_tool
    client.client = connected_client

    task = asyncio.create_task(
        client.call_tool(MCPToolCall(name="slow", arguments={}, id="call-1"))
    )
    await call_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.wait_for(client.close(), timeout=0.5)
    connected_client.__aexit__.assert_awaited_once_with(None, None, None)


@pytest.mark.asyncio
async def test_concurrent_401_refresh_is_single_flight():
    client = MCPClient("https://mcp.example.com/mcp")
    original = AsyncMock()
    replacement = AsyncMock()
    both_started = asyncio.Event()
    started = 0

    async def unauthorized(_name, _arguments):
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await both_started.wait()
        raise Exception("401 Unauthorized")

    original.call_tool.side_effect = unauthorized
    replacement.call_tool.return_value = SimpleNamespace(content=["ok"], isError=False)
    client.client = original
    client._tools_cache = []
    token_manager = SimpleNamespace(
        refresh=AsyncMock(),
        access_token="refreshed-access-token",
    )
    client._token_manager = token_manager

    async def reconnect(_auth, _timeout):
        client.client = replacement

    client._connect_with_auth = AsyncMock(side_effect=reconnect)

    results = await asyncio.gather(
        client.call_tool(MCPToolCall(name="first", arguments={}, id="call-1")),
        client.call_tool(MCPToolCall(name="second", arguments={}, id="call-2")),
    )

    assert all(not result.is_error for result in results)
    token_manager.refresh.assert_awaited_once_with(force=True)
    original.__aexit__.assert_awaited_once_with(None, None, None)
    client._connect_with_auth.assert_awaited_once()
    assert replacement.call_tool.await_count == 2


@pytest.mark.asyncio
async def test_concurrent_401_refresh_failure_is_single_flight():
    client = MCPClient("https://mcp.example.com/mcp")
    connected_client = AsyncMock()
    both_started = asyncio.Event()
    started = 0

    async def unauthorized(_name, _arguments):
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await both_started.wait()
        raise Exception("401 Unauthorized")

    connected_client.call_tool.side_effect = unauthorized
    client.client = connected_client
    token_manager = SimpleNamespace(
        refresh=AsyncMock(side_effect=MCPConnectionError("identity provider offline")),
        access_token="unchanged-access-token",
    )
    client._token_manager = token_manager

    results = await asyncio.gather(
        client.call_tool(MCPToolCall(name="first", arguments={}, id="call-1")),
        client.call_tool(MCPToolCall(name="second", arguments={}, id="call-2")),
    )

    assert all(result.is_error for result in results)
    assert all("identity provider offline" in result.error_message for result in results)
    token_manager.refresh.assert_awaited_once_with(force=True)

    # A later 401 starts a new attempt rather than permanently caching failure.
    later = await client.call_tool(MCPToolCall(name="later", arguments={}, id="call-3"))
    assert later.is_error is True
    assert "identity provider offline" in later.error_message
    assert token_manager.refresh.await_count == 2


@pytest.mark.asyncio
async def test_tool_call_timeout_includes_waiting_for_lifecycle_guard():
    client = MCPClient("https://mcp.example.com/mcp")
    client.client = AsyncMock()
    guard_entered = asyncio.Event()
    release_guard = asyncio.Event()

    async def hold_exclusive_guard():
        async with client._lifecycle_guard.exclusive():
            guard_entered.set()
            await release_guard.wait()

    guard_task = asyncio.create_task(hold_exclusive_guard())
    await guard_entered.wait()

    try:
        result = await client.call_tool(
            MCPToolCall(name="ping", arguments={}, id="call-1"), timeout=0.01
        )
    finally:
        release_guard.set()
        await guard_task

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
