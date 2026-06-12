"""Unit tests for the tools router's POST /api/format endpoint."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from testmcpy.mcp_profiles import AuthConfig, MCPProfile, MCPServer
from testmcpy.server.routers.tools import router
from testmcpy.src.mcp_client import MCPToolCall

SCHEMA = {
    "type": "object",
    "properties": {"dashboard_id": {"type": "string", "description": "Dashboard ID"}},
    "required": ["dashboard_id"],
}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _format_request(fmt):
    return {"schema": SCHEMA, "tool_name": "get_dashboard", "format": fmt}


class TestFormatSchema:
    @pytest.mark.parametrize("fmt", ["json", "yaml", "typescript", "python"])
    def test_pure_conversion_formats(self, client, fmt):
        resp = client.post("/api/format", json=_format_request(fmt))
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["format"] == fmt
        assert data["code"]
        assert data["language"]

    def test_unsupported_format_returns_400(self, client):
        resp = client.post("/api/format", json=_format_request("cobol"))
        assert resp.status_code == 400
        assert "Unsupported format" in resp.json()["detail"]

    def test_client_format_uses_explicit_mcp_url(self, client):
        payload = _format_request("python_client")
        payload["mcp_url"] = "http://mcp.example.com/mcp"
        resp = client.post("/api/format", json=payload)
        assert resp.status_code == 200
        assert "http://mcp.example.com/mcp" in resp.json()["code"]

    def test_missing_required_fields_returns_422(self, client):
        resp = client.post("/api/format", json={"format": "json"})
        assert resp.status_code == 422


def _profile(mcp_name="srv"):
    server = MCPServer(
        name=mcp_name,
        mcp_url="https://example.com/mcp/",
        auth=AuthConfig(auth_type="none"),
    )
    return MCPProfile(name="p", profile_id="p", description="", mcps=[server])


def _tool_result(content="ok", is_error=False, error_message=None):
    return SimpleNamespace(content=content, is_error=is_error, error_message=error_message)


class TestCompareTools:
    def test_runs_iterations(self, client):
        instance = AsyncMock()
        instance.call_tool.return_value = _tool_result(content="hello")
        with (
            patch("testmcpy.server.routers.tools.load_profile", return_value=_profile()),
            patch("testmcpy.server.routers.tools.MCPClient", return_value=instance) as mock_cls,
        ):
            res = client.post(
                "/api/tools/compare",
                json={
                    "tool_name": "list_charts",
                    "profile1": "p:srv",
                    "profile2": "p:srv",
                    "parameters": {"limit": 5},
                    "iterations": 1,
                },
            )
        assert res.status_code == 200
        iteration = res.json()["results1"][0]
        assert iteration["success"] is True
        assert iteration["result"] == "hello"
        # Client constructed with base_url + auth dict (not mcp_url=/AuthConfig kwargs)
        _, kwargs = mock_cls.call_args
        assert kwargs["base_url"] == "https://example.com/mcp/"
        assert kwargs["auth"] == {"type": "none"}
        # call_tool received an MCPToolCall, not (name=..., arguments=...) kwargs
        tool_call = instance.call_tool.await_args.args[0]
        assert isinstance(tool_call, MCPToolCall)
        assert tool_call.name == "list_charts"
        assert tool_call.arguments == {"limit": 5}
        instance.close.assert_awaited()

    def test_reports_tool_error(self, client):
        instance = AsyncMock()
        instance.call_tool.return_value = _tool_result(is_error=True, error_message="boom")
        with (
            patch("testmcpy.server.routers.tools.load_profile", return_value=_profile()),
            patch("testmcpy.server.routers.tools.MCPClient", return_value=instance),
        ):
            res = client.post(
                "/api/tools/compare",
                json={
                    "tool_name": "list_charts",
                    "profile1": "p:srv",
                    "profile2": "p:srv",
                    "iterations": 1,
                },
            )
        assert res.status_code == 200
        iteration = res.json()["results1"][0]
        assert iteration["success"] is False
        assert iteration["error"] == "boom"


class TestToolDebug:
    def test_uses_cached_client(self, client):
        fake = AsyncMock()
        fake.call_tool.return_value = _tool_result(content=[SimpleNamespace(text="result text")])
        with patch("testmcpy.server.routers.tools.get_mcp_clients", return_value={"default": fake}):
            res = client.post("/api/tools/my_tool/debug", json={"parameters": {"x": 1}})
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["response"] == "result text"
        tool_call = fake.call_tool.await_args.args[0]
        assert isinstance(tool_call, MCPToolCall)
        assert tool_call.name == "my_tool"
        assert tool_call.arguments == {"x": 1}

    def test_reports_tool_error(self, client):
        fake = AsyncMock()
        fake.call_tool.return_value = _tool_result(is_error=True, error_message="tool exploded")
        with patch("testmcpy.server.routers.tools.get_mcp_clients", return_value={"default": fake}):
            res = client.post("/api/tools/my_tool/debug", json={"parameters": {}})
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is False
        assert "tool exploded" in data["error"]
