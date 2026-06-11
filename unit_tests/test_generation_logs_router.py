"""Unit tests for the generation-logs router (save/list/get/delete/clear)."""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from testmcpy.server.routers.generation_logs import router
from testmcpy.storage import TestStorage


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Point the get_storage() singleton at an isolated temp database."""
    import testmcpy.storage as storage_module

    storage = TestStorage(db_path=tmp_path / "test_generation_logs.db")
    monkeypatch.setattr(storage_module, "_storage", storage)
    yield storage
    monkeypatch.setattr(storage_module, "_storage", None)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _make_log(tool_name="list_dashboards"):
    return {
        "metadata": {
            "tool_name": tool_name,
            "tool_description": "List dashboards",
            "coverage_level": "basic",
            "provider": "anthropic",
            "model": "claude-sonnet-4-5",
            "timestamp": "2025-01-01T00:00:00",
            "success": True,
            "test_count": 2,
            "total_cost": 0.01,
        },
        "tool_schema": {"type": "object", "properties": {}},
        "llm_calls": [],
        "logs": ["generated"],
    }


class TestSaveGenerationLog:
    def test_save_returns_log_id(self, client):
        resp = client.post("/api/generation-logs/save", json=_make_log())
        assert resp.status_code == 200
        data = resp.json()
        assert data["saved"] is True
        assert data["log_id"]


class TestListGenerationLogs:
    def test_list_empty(self, client):
        resp = client.get("/api/generation-logs/list")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_after_save(self, client):
        client.post("/api/generation-logs/save", json=_make_log())
        resp = client.get("/api/generation-logs/list")
        data = resp.json()
        assert data["total"] == 1
        assert data["logs"][0]["tool_name"] == "list_dashboards"

    def test_list_filter_by_tool_name(self, client):
        client.post("/api/generation-logs/save", json=_make_log(tool_name="tool_a"))
        client.post("/api/generation-logs/save", json=_make_log(tool_name="tool_b"))
        resp = client.get("/api/generation-logs/list", params={"tool_name": "tool_a"})
        data = resp.json()
        assert data["total"] == 1
        assert data["logs"][0]["tool_name"] == "tool_a"


class TestGetGenerationLog:
    def test_get_existing_log(self, client):
        log_id = client.post("/api/generation-logs/save", json=_make_log()).json()["log_id"]
        resp = client.get(f"/api/generation-logs/log/{log_id}")
        assert resp.status_code == 200

    def test_get_missing_log_returns_404(self, client):
        resp = client.get("/api/generation-logs/log/nonexistent")
        assert resp.status_code == 404


class TestGeneratedTools:
    def test_tools_after_saves(self, client):
        client.post("/api/generation-logs/save", json=_make_log(tool_name="tool_a"))
        client.post("/api/generation-logs/save", json=_make_log(tool_name="tool_a"))
        resp = client.get("/api/generation-logs/tools")
        data = resp.json()
        assert data["total"] == 1
        assert data["tools"][0]["name"] == "tool_a"
        assert data["tools"][0]["generation_count"] == 2


class TestDeleteGenerationLog:
    def test_delete_existing(self, client):
        log_id = client.post("/api/generation-logs/save", json=_make_log()).json()["log_id"]
        resp = client.delete(f"/api/generation-logs/log/{log_id}")
        assert resp.status_code == 200
        assert client.get(f"/api/generation-logs/log/{log_id}").status_code == 404

    def test_delete_missing_returns_404(self, client):
        resp = client.delete("/api/generation-logs/log/nonexistent")
        assert resp.status_code == 404

    def test_clear_all(self, client):
        client.post("/api/generation-logs/save", json=_make_log())
        client.post("/api/generation-logs/save", json=_make_log())
        resp = client.delete("/api/generation-logs/clear")
        assert resp.json()["deleted"] == 2
        assert client.get("/api/generation-logs/list").json()["total"] == 0
