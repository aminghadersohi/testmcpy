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
