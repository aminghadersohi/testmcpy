"""Tests for API-key protection of state-changing and secret-bearing APIs."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from testmcpy.server.auth_middleware import APIKeyAuthMiddleware


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/api/public")
    async def public():
        return {"ok": True}

    @app.post("/api/secret")
    async def secret():
        return {"ok": True}

    app.add_middleware(APIKeyAuthMiddleware)
    return TestClient(app)


def test_sensitive_post_requires_configured_api_key(monkeypatch):
    monkeypatch.setenv("TESTMCPY_API_KEY", "expected-key")

    with _client() as client:
        assert client.post("/api/secret").status_code == 401
        assert (
            client.post(
                "/api/secret",
                headers={"Authorization": "Bearer wrong-key"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/secret",
                headers={"Authorization": "Bearer expected-key"},
            ).status_code
            == 200
        )


def test_read_only_api_remains_public(monkeypatch):
    monkeypatch.setenv("TESTMCPY_API_KEY", "expected-key")

    with _client() as client:
        assert client.get("/api/public").status_code == 200
