"""Unit tests for the tools router's POST /api/format endpoint."""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from testmcpy.server.routers.tools import router

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
