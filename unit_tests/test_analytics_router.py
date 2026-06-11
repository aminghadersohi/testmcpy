"""Unit tests for the /api/analytics router (FastAPI TestClient)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from testmcpy.server.routers import analytics as analytics_router
from testmcpy.storage import TestStorage


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient with an isolated seeded DB behind get_storage()."""
    storage = TestStorage(db_path=tmp_path / "router.db")
    for i, passed in enumerate([True, False, True], start=1):
        started = f"2026-06-{i:02d}T10:00:00"
        storage.save_run(
            run_id=f"r{i}",
            test_id="suite-A",
            test_version=1,
            model="claude-sonnet-4-5",
            provider="anthropic",
            started_at=started,
            mcp_profile_id="staging",
        )
        storage.save_question_result(
            run_id=f"r{i}", question_id="q1", passed=passed, score=1.0, cost_usd=0.01
        )
        storage.complete_run(f"r{i}", started)

    monkeypatch.setattr(analytics_router, "get_storage", lambda: storage)
    app = FastAPI()
    app.include_router(analytics_router.router)
    return TestClient(app)


def test_matrix_endpoint(client):
    res = client.get("/api/analytics/matrix", params={"suite_id": "suite-A"})
    assert res.status_code == 200
    data = res.json()
    cell = data["rows"][0]["cells"]["anthropic/claude-sonnet-4-5 @ staging"]
    assert cell["n"] == 3
    assert cell["flaky"] is True


def test_leaderboard_endpoint(client):
    res = client.get("/api/analytics/leaderboard")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["configs"][0]["n_runs"] == 3


def test_flaky_endpoint(client):
    res = client.get("/api/analytics/flaky")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["flaky"][0]["question_id"] == "q1"


def test_question_history_endpoint(client):
    res = client.get("/api/analytics/question-history", params={"question_id": "q1"})
    assert res.status_code == 200
    data = res.json()
    assert [p["passed"] for p in data["points"]] == [True, False, True]


def test_question_history_requires_question_id(client):
    res = client.get("/api/analytics/question-history")
    assert res.status_code == 422
