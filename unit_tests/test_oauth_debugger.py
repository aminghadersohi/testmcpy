"""Protocol-level tests for the interactive MCP OAuth debugger."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from testmcpy.auth_debugger import (
    AuthDebugger,
    _authorization_server_metadata_urls,
    _extract_www_auth_parameter,
    _protected_resource_metadata_urls,
    _select_token_endpoint_auth_method,
    _validate_oauth_endpoint,
    complete_oauth_authorization_flow,
    discover_oauth_endpoints,
    prepare_oauth_authorization_flow,
)
from testmcpy.auth_flow_recorder import AuthFlowRecorder
from testmcpy.server.routers import auth as auth_router

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def test_debugger_never_retains_credentials_in_trace():
    debugger = AuthDebugger(enabled=True)
    debugger.log_step(
        "Token response",
        {
            "access_token": "access-secret",
            "headers": {"Authorization": "Bearer header-secret"},
            "raw_response": (
                'HTTP/1.1 200 OK\n\n{"refresh_token":"refresh-secret",'
                '"client_secret":"client-secret"}'
            ),
            "nested": [{"id_token": "nested-secret"}],
            "cookie_response": {
                "Set-Cookie": "session=cookie-secret",
                "response_body": "access_token=form-secret",
            },
        },
    )

    serialized = json.dumps(debugger.get_trace())
    for secret in (
        "access-secret",
        "header-secret",
        "refresh-secret",
        "client-secret",
        "nested-secret",
        "cookie-secret",
        "form-secret",
    ):
        assert secret not in serialized
    assert serialized.count("[REDACTED]") >= 5


def test_debug_auth_route_rejects_cross_origin_browser_request():
    app = FastAPI()
    app.include_router(auth_router.router)
    with TestClient(app) as client:
        response = client.post(
            "/api/debug-auth",
            headers={"Origin": "https://attacker.example"},
            json={"auth_type": "oauth", "oauth_auto_discover": True},
        )
    assert response.status_code == 403


def _mock_async_client(transport: httpx.MockTransport):
    def factory(**_kwargs):
        return _REAL_ASYNC_CLIENT(transport=transport)

    return factory


def test_www_auth_and_discovery_url_builders():
    challenge = (
        'Bearer realm="mcp", scope="read write", '
        'resource_metadata="https://mcp.example/.well-known/custom"'
    )
    assert _extract_www_auth_parameter(challenge, "scope") == "read write"
    assert _extract_www_auth_parameter(challenge, "resource_metadata") == (
        "https://mcp.example/.well-known/custom"
    )
    assert _protected_resource_metadata_urls(
        "https://mcp.example/tenant/mcp", "https://mcp.example/.well-known/custom"
    ) == [
        "https://mcp.example/.well-known/custom",
        "https://mcp.example/.well-known/oauth-protected-resource/tenant/mcp",
        "https://mcp.example/.well-known/oauth-protected-resource",
    ]
    assert _authorization_server_metadata_urls(
        "https://login.example/tenant", "https://mcp.example/mcp"
    ) == [
        "https://login.example/.well-known/oauth-authorization-server/tenant",
        "https://login.example/.well-known/openid-configuration/tenant",
        "https://login.example/tenant/.well-known/openid-configuration",
    ]
    assert _authorization_server_metadata_urls(None, "https://mcp.example/mcp") == [
        "https://mcp.example/.well-known/oauth-authorization-server",
        "https://mcp.example/.well-known/openid-configuration",
    ]
    assert (
        _select_token_endpoint_auth_method(
            {"token_endpoint_auth_methods_supported": ["client_secret_basic"]},
            has_client_secret=True,
        )
        == "client_secret_basic"
    )
    assert _select_token_endpoint_auth_method({}, has_client_secret=True) == "client_secret_basic"
    _validate_oauth_endpoint("http://127.0.0.1:8084/token", "token endpoint")
    with pytest.raises(Exception, match="must use HTTPS"):
        _validate_oauth_endpoint("http://auth.example/token", "token endpoint")


@pytest.mark.asyncio
async def test_discovery_uses_www_auth_resource_metadata_and_path_aware_issuer():
    requested_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append((request.method, str(request.url)))
        if request.method == "POST" and request.url.path == "/mcp":
            return httpx.Response(
                401,
                headers={
                    "WWW-Authenticate": (
                        'Bearer scope="mcp:read mcp:write", '
                        'resource_metadata="https://resource.test/custom-metadata"'
                    )
                },
            )
        if request.url.host == "resource.test" and request.url.path == "/custom-metadata":
            return httpx.Response(
                200,
                json={
                    "resource": "https://resource.test/mcp",
                    "authorization_servers": ["https://auth.test/tenant"],
                    "scopes_supported": ["fallback"],
                },
            )
        if request.url.host == "auth.test" and request.url.path == (
            "/.well-known/oauth-authorization-server/tenant"
        ):
            return httpx.Response(
                200,
                json={
                    "issuer": "https://auth.test/tenant",
                    "authorization_endpoint": "https://auth.test/authorize",
                    "token_endpoint": "https://auth.test/token",
                    "registration_endpoint": "https://auth.test/register",
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    debugger = AuthDebugger(enabled=True)
    with patch(
        "testmcpy.auth_debugger.httpx.AsyncClient",
        side_effect=_mock_async_client(transport),
    ):
        metadata = await discover_oauth_endpoints("https://resource.test/mcp", debugger=debugger)

    assert metadata["issuer"] == "https://auth.test/tenant"
    assert metadata["resource"] == "https://resource.test/mcp"
    assert metadata["protected_resource_metadata_url"] == ("https://resource.test/custom-metadata")
    assert metadata["www_authenticate"]["scope"] == "mcp:read mcp:write"
    assert requested_paths[:3] == [
        ("POST", "https://resource.test/mcp"),
        ("GET", "https://resource.test/custom-metadata"),
        ("GET", "https://auth.test/.well-known/oauth-authorization-server/tenant"),
    ]
    assert not debugger.has_failures()


@pytest.mark.asyncio
async def test_discovery_falls_back_from_path_to_root_resource_metadata():
    requested_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.method == "POST":
            return httpx.Response(401, headers={"WWW-Authenticate": "Bearer"})
        if request.url.path == "/.well-known/oauth-protected-resource/mcp":
            return httpx.Response(404)
        if request.url.path == "/.well-known/oauth-protected-resource":
            return httpx.Response(
                200,
                json={
                    "resource": "https://resource.test",
                    "authorization_servers": ["https://auth.test"],
                },
            )
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(
                200,
                json={
                    "issuer": "https://auth.test",
                    "authorization_endpoint": "https://auth.test/authorize",
                    "token_endpoint": "https://auth.test/token",
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    with patch(
        "testmcpy.auth_debugger.httpx.AsyncClient",
        side_effect=_mock_async_client(transport),
    ):
        metadata = await discover_oauth_endpoints("https://resource.test/mcp")

    assert metadata["protected_resource_metadata"]["resource"] == "https://resource.test"
    assert requested_paths[:4] == [
        "/mcp",
        "/.well-known/oauth-protected-resource/mcp",
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-authorization-server",
    ]


@pytest.mark.asyncio
async def test_discovery_without_prm_uses_root_authorization_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(401, headers={"WWW-Authenticate": "Bearer"})
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(
                200,
                json={
                    "issuer": "https://resource.test",
                    "authorization_endpoint": "https://resource.test/authorize",
                    "token_endpoint": "https://resource.test/token",
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    with patch(
        "testmcpy.auth_debugger.httpx.AsyncClient",
        side_effect=_mock_async_client(transport),
    ):
        metadata = await discover_oauth_endpoints("https://resource.test/mcp")

    assert metadata["issuer"] == "https://resource.test"


@pytest.mark.asyncio
async def test_discovery_ignores_protected_metadata_without_resource():
    requested_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.method == "POST":
            return httpx.Response(401, headers={"WWW-Authenticate": "Bearer"})
        if request.url.path.startswith("/.well-known/oauth-protected-resource"):
            return httpx.Response(
                200,
                json={"authorization_servers": ["https://malicious-auth.test"]},
            )
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(
                200,
                json={
                    "issuer": "https://resource.test",
                    "authorization_endpoint": "https://resource.test/authorize",
                    "token_endpoint": "https://resource.test/token",
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    with patch(
        "testmcpy.auth_debugger.httpx.AsyncClient",
        side_effect=_mock_async_client(transport),
    ):
        metadata = await discover_oauth_endpoints("https://resource.test/mcp")

    assert metadata["issuer"] == "https://resource.test"
    assert metadata["protected_resource_metadata"] is None
    assert "/.well-known/oauth-authorization-server" in requested_paths


@pytest.mark.asyncio
async def test_full_dcr_pkce_token_exchange_and_mcp_validation():
    requests: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        requests[f"{request.method} {request.url.path}"] = request
        if request.method == "POST" and request.url.path == "/mcp":
            if request.headers.get("authorization") == "Bearer access-123":
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": 2, "result": {}})
            return httpx.Response(
                401,
                headers={
                    "WWW-Authenticate": ('Bearer resource_metadata="https://resource.test/prm"')
                },
            )
        if request.url.path == "/prm":
            return httpx.Response(
                200,
                json={
                    "resource": "https://resource.test/mcp",
                    "authorization_servers": ["https://auth.test"],
                    "scopes_supported": ["read", "write"],
                },
            )
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(
                200,
                json={
                    "issuer": "https://auth.test",
                    "authorization_endpoint": "https://auth.test/authorize",
                    "token_endpoint": "https://auth.test/token",
                    "registration_endpoint": "https://auth.test/register",
                },
            )
        if request.url.path == "/register":
            return httpx.Response(
                201,
                json={"client_id": "debug-client", "token_endpoint_auth_method": "none"},
            )
        if request.url.path == "/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "access-123",
                    "refresh_token": "refresh-123",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "read write",
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    debugger = AuthDebugger(enabled=True)
    with patch(
        "testmcpy.auth_debugger.httpx.AsyncClient",
        side_effect=_mock_async_client(transport),
    ):
        preparation = await prepare_oauth_authorization_flow(
            "https://resource.test/mcp",
            "http://127.0.0.1:8000/api/oauth-debugger/callback",
            debugger=debugger,
        )
        tokens = await complete_oauth_authorization_flow(
            preparation, "authorization-code", debugger
        )

    authorization_query = parse_qs(urlparse(preparation["authorization_url"]).query)
    assert authorization_query["client_id"] == ["debug-client"]
    assert authorization_query["resource"] == ["https://resource.test/mcp"]
    assert authorization_query["scope"] == ["read write"]
    assert authorization_query["code_challenge_method"] == ["S256"]
    assert authorization_query["state"] == [preparation["state"]]
    assert len(authorization_query["code_challenge"][0]) == 43

    registration = requests["POST /register"].read()
    assert b"testmcpy Auth Debugger" in registration
    token_form = parse_qs(requests["POST /token"].read().decode())
    assert token_form["resource"] == ["https://resource.test/mcp"]
    assert token_form["code"] == ["authorization-code"]
    assert token_form["code_verifier"] == [preparation["code_verifier"]]
    assert tokens["access_token"] == "access-123"
    serialized_trace = json.dumps(debugger.get_trace())
    assert "access-123" not in serialized_trace
    assert "refresh-123" not in serialized_trace
    assert any(step["step"] == "16. OAuth Flow Complete" for step in debugger.steps)
    assert not debugger.has_failures()


@pytest.mark.asyncio
async def test_router_oauth_transaction_callback_and_poll():
    auth_router.oauth_debug_transactions.clear()
    auth_router.oauth_debug_states.clear()
    preparation = {
        "authorization_url": "https://auth.test/authorize?state=expected-state",
        "state": "expected-state",
        "code_verifier": "v" * 43,
        "redirect_uri": "http://127.0.0.1:8000/api/oauth-debugger/callback",
        "resource": "https://resource.test/mcp",
        "mcp_url": "https://resource.test/mcp",
        "token_endpoint": "https://auth.test/token",
        "client_id": "debug-client",
        "client_secret": None,
        "token_endpoint_auth_method": "none",
        "scopes": [],
        "insecure": False,
    }

    with (
        patch.object(
            auth_router,
            "prepare_oauth_authorization_flow",
            new=AsyncMock(return_value=preparation),
        ),
        patch.object(
            auth_router,
            "complete_oauth_authorization_flow",
            new=AsyncMock(return_value={"access_token": "token"}),
        ) as complete,
    ):
        started = await auth_router.debug_auth(
            auth_router.DebugAuthRequest(
                auth_type="oauth",
                oauth_auto_discover=True,
                mcp_url="https://resource.test/mcp",
            ),
            redirect_uri=preparation["redirect_uri"],
        )
        assert started.status == "authorization_required"
        assert started.success is False
        callback = await auth_router.oauth_debugger_callback(
            state="expected-state", code="authorization-code"
        )
        assert callback.status_code == 200
        assert callback.headers["cache-control"] == "no-store"
        assert callback.headers["referrer-policy"] == "no-referrer"
        complete.assert_awaited_once()
        polled = await auth_router.get_oauth_debug_transaction(started.transaction_id)

    assert polled.status == "complete"
    assert polled.success is True
    assert polled.authorization_url is None
    completed = auth_router.oauth_debug_transactions[started.transaction_id]
    assert "preparation" not in completed
    assert completed["expires_at"] > time.time() + 50
    assert completed["cleanup_handle"] is not None


@pytest.mark.asyncio
async def test_oauth_callback_processing_cannot_expire_or_report_success():
    auth_router.oauth_debug_transactions.clear()
    auth_router.oauth_debug_states.clear()
    preparation = {
        "authorization_url": "https://auth.test/authorize?state=processing-state",
        "state": "processing-state",
        "code_verifier": "v" * 43,
        "redirect_uri": "http://127.0.0.1:8000/api/oauth-debugger/callback",
        "resource": "https://resource.test/mcp",
        "mcp_url": "https://resource.test/mcp",
        "token_endpoint": "https://auth.test/token",
        "client_id": "debug-client",
        "client_secret": None,
        "token_endpoint_auth_method": "none",
        "scopes": [],
        "insecure": False,
    }
    exchange_started = asyncio.Event()
    finish_exchange = asyncio.Event()

    async def complete_flow(*_args):
        exchange_started.set()
        await finish_exchange.wait()
        return {"access_token": "token"}

    with (
        patch.object(
            auth_router,
            "prepare_oauth_authorization_flow",
            new=AsyncMock(return_value=preparation),
        ),
        patch.object(
            auth_router,
            "complete_oauth_authorization_flow",
            new=AsyncMock(side_effect=complete_flow),
        ),
    ):
        started = await auth_router.debug_auth(
            auth_router.DebugAuthRequest(
                auth_type="oauth",
                oauth_auto_discover=True,
                mcp_url="https://resource.test/mcp",
            ),
            redirect_uri=preparation["redirect_uri"],
        )
        callback_task = asyncio.create_task(
            auth_router.oauth_debugger_callback(state="processing-state", code="authorization-code")
        )
        await exchange_started.wait()

        transaction = auth_router.oauth_debug_transactions[started.transaction_id]
        assert transaction["status"] == "processing"
        assert transaction["expires_at"] == float("inf")
        assert "cleanup_handle" not in transaction
        auth_router._cleanup_oauth_debug_transactions()
        assert started.transaction_id in auth_router.oauth_debug_transactions
        polled = await auth_router.get_oauth_debug_transaction(started.transaction_id)
        assert polled.status == "processing"
        assert polled.success is False

        finish_exchange.set()
        response = await callback_task

    assert response.status_code == 200
    assert auth_router.oauth_debug_transactions[started.transaction_id]["status"] == "complete"


@pytest.mark.asyncio
async def test_recorded_oauth_transactions_use_isolated_recorders(tmp_path, monkeypatch):
    auth_router.oauth_debug_transactions.clear()
    auth_router.oauth_debug_states.clear()
    monkeypatch.setattr(auth_router, "auth_flow_recorder", AuthFlowRecorder(tmp_path))

    def preparation(state: str) -> dict:
        return {
            "authorization_url": f"https://auth.test/authorize?state={state}",
            "state": state,
            "redirect_uri": "http://127.0.0.1:8000/api/oauth-debugger/callback",
        }

    prepare = AsyncMock(side_effect=[preparation("state-one"), preparation("state-two")])
    with patch.object(auth_router, "prepare_oauth_authorization_flow", new=prepare):
        first = await auth_router.debug_auth(
            auth_router.DebugAuthRequest(
                auth_type="oauth",
                oauth_auto_discover=True,
                mcp_url="https://resource.test/mcp",
            ),
            record=True,
            flow_name="concurrent",
            redirect_uri="http://127.0.0.1:8000/api/oauth-debugger/callback",
        )
        second = await auth_router.debug_auth(
            auth_router.DebugAuthRequest(
                auth_type="oauth",
                oauth_auto_discover=True,
                mcp_url="https://resource.test/mcp",
            ),
            record=True,
            flow_name="concurrent",
            redirect_uri="http://127.0.0.1:8000/api/oauth-debugger/callback",
        )

    first_debugger = auth_router.oauth_debug_transactions[first.transaction_id]["debugger"]
    second_debugger = auth_router.oauth_debug_transactions[second.transaction_id]["debugger"]
    assert first_debugger.recorder is not second_debugger.recorder

    auth_router._expire_oauth_debug_transaction(first.transaction_id)
    assert first_debugger.recorder.current_recording is None
    assert second_debugger.recorder.current_recording is not None
    auth_router._expire_oauth_debug_transaction(second.transaction_id)
    assert len(list(tmp_path.glob("oauth_*.json"))) == 2
