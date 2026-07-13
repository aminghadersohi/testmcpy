"""Authentication debugging and flow recording endpoints."""

import asyncio
import html
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from testmcpy.auth_debugger import (
    AuthDebugger,
    complete_oauth_authorization_flow,
    debug_bearer_token,
    debug_jwt_flow,
    debug_oauth_flow,
    prepare_oauth_authorization_flow,
)
from testmcpy.auth_flow_recorder import AuthFlowRecorder

router = APIRouter(prefix="/api", tags=["auth"])

# Global auth flow recorder instance
auth_flow_recorder = AuthFlowRecorder()

# OAuth authorization is split across a browser redirect. This in-memory
# transaction store intentionally holds PKCE/client material only until the
# callback completes. The web server currently runs as a single process; a
# future multi-worker deployment should replace this with shared encrypted
# storage.
_OAUTH_TRANSACTION_TTL_SECONDS = 300
_OAUTH_COMPLETED_RETENTION_SECONDS = 60
_OAUTH_MAX_TRANSACTIONS = 128
oauth_debug_transactions: dict[str, dict[str, Any]] = {}
oauth_debug_states: dict[str, str] = {}


# Pydantic models
class DebugAuthRequest(BaseModel):
    auth_type: str  # "oauth", "jwt", "bearer"
    mcp_url: str | None = None  # MCP endpoint to test token against
    # OAuth fields
    client_id: str | None = None
    client_secret: str | None = None
    token_url: str | None = None
    scopes: list[str] | None = None
    oauth_auto_discover: bool = False  # Use RFC 8414 auto-discovery for OAuth
    # JWT fields
    api_url: str | None = None
    api_token: str | None = None
    api_secret: str | None = None
    insecure: bool = False  # Skip SSL verification
    # Bearer fields
    token: str | None = None


class DebugAuthResponse(BaseModel):
    success: bool
    auth_type: str
    steps: list[dict[str, Any]]
    total_time: float
    error: str | None = None
    status: str = "complete"
    transaction_id: str | None = None
    authorization_url: str | None = None


class AuthFlowListItem(BaseModel):
    filepath: str
    filename: str
    recording_id: str
    flow_name: str
    auth_type: str
    created_at: str
    duration: float
    success: bool | None
    step_count: int


class AuthFlowCompareRequest(BaseModel):
    filepath1: str
    filepath2: str


async def debug_auth(
    request: DebugAuthRequest,
    record: bool = False,
    flow_name: str | None = None,
    redirect_uri: str | None = None,
):
    """Debug authentication flow with detailed step-by-step logging."""
    try:
        # Create debugger with optional recorder
        # Each request needs independent mutable recording state. The global
        # recorder remains the index over their shared storage directory.
        recorder = AuthFlowRecorder(storage_dir=auth_flow_recorder.storage_dir) if record else None
        debugger = AuthDebugger(enabled=True, recorder=recorder)

        # Start recording if enabled
        if record:
            recording_name = flow_name or f"{request.auth_type}_debug"
            debugger.start_flow_recording(
                flow_name=recording_name,
                auth_type=request.auth_type,
                protocol_version="OAuth 2.0" if request.auth_type == "oauth" else None,
            )

        error = None
        transaction_id = None
        authorization_url = None
        status = "complete"
        recording_filename = f"auth_{secrets.token_urlsafe(16)}.json" if record else None

        try:
            if request.auth_type == "oauth":
                if request.oauth_auto_discover:
                    if not request.mcp_url:
                        raise HTTPException(
                            status_code=400,
                            detail="OAuth auto-discovery requires mcp_url",
                        )
                    if redirect_uri:
                        preparation = await prepare_oauth_authorization_flow(
                            mcp_url=request.mcp_url,
                            redirect_uri=redirect_uri,
                            scopes=request.scopes,
                            client_id=request.client_id,
                            client_secret=request.client_secret,
                            debugger=debugger,
                            insecure=request.insecure,
                        )
                        _cleanup_oauth_debug_transactions()
                        if len(oauth_debug_transactions) >= _OAUTH_MAX_TRANSACTIONS:
                            evictable_ids = [
                                item
                                for item, pending in oauth_debug_transactions.items()
                                if pending["status"] != "processing"
                            ]
                            if not evictable_ids:
                                raise Exception(
                                    "Too many OAuth callbacks are currently being processed"
                                )
                            oldest_id = min(
                                evictable_ids,
                                key=lambda item: oauth_debug_transactions[item]["created_at"],
                            )
                            _expire_oauth_debug_transaction(oldest_id)
                        transaction_id = secrets.token_urlsafe(24)
                        oauth_debug_transactions[transaction_id] = {
                            "transaction_id": transaction_id,
                            "created_at": time.time(),
                            "expires_at": time.time() + _OAUTH_TRANSACTION_TTL_SECONDS,
                            "status": "authorization_required",
                            "preparation": preparation,
                            "debugger": debugger,
                            "record": record,
                            "auth_type": "oauth",
                        }
                        oauth_debug_states[preparation["state"]] = transaction_id
                        _schedule_oauth_debug_cleanup(
                            transaction_id, _OAUTH_TRANSACTION_TTL_SECONDS
                        )
                        authorization_url = preparation["authorization_url"]
                        status = "authorization_required"
                    else:
                        from testmcpy.auth_debugger import debug_oauth_auto_discover_flow

                        await debug_oauth_auto_discover_flow(
                            mcp_url=request.mcp_url,
                            debugger=debugger,
                            insecure=request.insecure,
                        )
                elif not all([request.client_id, request.client_secret, request.token_url]):
                    raise HTTPException(
                        status_code=400,
                        detail="OAuth requires client_id, client_secret, and token_url (or enable oauth_auto_discover)",
                    )
                else:
                    # Token is captured by debugger trace, not returned directly
                    await debug_oauth_flow(
                        client_id=request.client_id,
                        client_secret=request.client_secret,
                        token_url=request.token_url,
                        scopes=request.scopes,
                        debugger=debugger,
                    )
            elif request.auth_type == "jwt":
                if not all([request.api_url, request.api_token, request.api_secret]):
                    raise HTTPException(
                        status_code=400, detail="JWT requires api_url, api_token, and api_secret"
                    )
                # Token is captured by debugger trace, not returned directly
                await debug_jwt_flow(
                    api_url=request.api_url,
                    api_token=request.api_token,
                    api_secret=request.api_secret,
                    debugger=debugger,
                )
            elif request.auth_type == "bearer":
                if not request.token:
                    raise HTTPException(status_code=400, detail="Bearer auth requires token")
                # Token is captured by debugger trace, not returned directly
                await debug_bearer_token(
                    token=request.token, mcp_url=request.mcp_url, debugger=debugger
                )
            else:
                raise HTTPException(
                    status_code=400, detail=f"Unsupported auth type: {request.auth_type}"
                )

        except Exception as e:
            error = str(e)

        # Save recording if enabled
        if record and status != "authorization_required":
            debugger.save_flow_recording(
                success=error is None and not debugger.has_failures(),
                error=error,
                filename=recording_filename,
            )

        trace = debugger.get_trace()

        return DebugAuthResponse(
            success=status == "complete" and not debugger.has_failures() and error is None,
            auth_type=request.auth_type,
            steps=trace["steps"],
            total_time=trace["total_time"],
            error=error,
            status=status,
            transaction_id=transaction_id,
            authorization_url=authorization_url,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to debug auth: {str(e)}")


@router.post("/debug-auth", response_model=DebugAuthResponse)
async def debug_auth_endpoint(
    request: DebugAuthRequest,
    http_request: Request,
    record: bool = Query(False, description="Record the auth flow for later replay"),
    flow_name: str | None = Query(None, description="Name for the recorded flow"),
):
    """API endpoint for debug_auth."""
    _require_same_origin(http_request)
    redirect_uri = str(http_request.url_for("oauth_debugger_callback"))
    return await debug_auth(request, record, flow_name, redirect_uri=redirect_uri)


@router.get("/oauth-debugger/callback", response_class=HTMLResponse)
async def oauth_debugger_callback(
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    """Complete a pending debugger PKCE flow without exposing tokens in HTML."""
    _cleanup_oauth_debug_transactions()
    transaction_id = oauth_debug_states.pop(state, None) if state else None
    transaction = oauth_debug_transactions.get(transaction_id or "")
    if not transaction or not state:
        return _oauth_callback_response(
            "OAuth callback rejected", "Unknown or expired state.", status_code=400
        )

    preparation = transaction["preparation"]
    debugger: AuthDebugger = transaction["debugger"]
    _mark_oauth_debug_transaction_processing(transaction)
    if not secrets.compare_digest(state, preparation["state"]):
        _finish_oauth_debug_transaction(transaction, "OAuth state mismatch")
        return _oauth_callback_response(
            "OAuth callback rejected", "State validation failed.", status_code=400
        )

    callback_error = error_description or error
    if callback_error:
        debugger.log_step(
            "11. Authorization Server Returned an Error",
            {"error": error, "error_description": error_description},
            success=False,
            step_type="error",
        )
        _finish_oauth_debug_transaction(transaction, callback_error)
        return _oauth_callback_response(
            "OAuth authorization failed", callback_error, status_code=400
        )
    if not code:
        debugger.log_step(
            "11. Authorization Callback Missing Code",
            {"error": "No authorization code was returned"},
            success=False,
            step_type="error",
        )
        _finish_oauth_debug_transaction(transaction, "No authorization code was returned")
        return _oauth_callback_response(
            "OAuth authorization failed",
            "No authorization code was returned.",
            status_code=400,
        )

    try:
        await complete_oauth_authorization_flow(preparation, code, debugger)
        _finish_oauth_debug_transaction(transaction, None)
    except Exception as exc:
        message = str(exc)
        if not debugger.has_failures():
            debugger.log_step(
                "ERROR: OAuth Authorization Flow Failed",
                {"error": message, "error_type": type(exc).__name__},
                success=False,
                step_type="error",
            )
        _finish_oauth_debug_transaction(transaction, message)
        return _oauth_callback_response("OAuth authorization failed", message, status_code=400)

    return _oauth_callback_response(
        "OAuth authorization complete",
        "The access token was accepted by the MCP server. You can close this window.",
    )


@router.get(
    "/oauth-debugger/transactions/{transaction_id}",
    response_model=DebugAuthResponse,
)
async def get_oauth_debug_transaction(transaction_id: str):
    """Poll a pending browser authorization flow for its final trace."""
    _cleanup_oauth_debug_transactions()
    transaction = oauth_debug_transactions.get(transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="OAuth debug transaction not found or expired")

    debugger: AuthDebugger = transaction["debugger"]
    trace = debugger.get_trace()
    status = transaction["status"]
    return DebugAuthResponse(
        success=status == "complete" and not debugger.has_failures(),
        auth_type="oauth",
        steps=trace["steps"],
        total_time=trace["total_time"],
        error=transaction.get("error"),
        status=status,
        transaction_id=transaction_id,
        authorization_url=(
            transaction.get("preparation", {}).get("authorization_url")
            if status == "authorization_required"
            else None
        ),
    )


def _finish_oauth_debug_transaction(transaction: dict[str, Any], error: str | None) -> None:
    transaction["status"] = "failed" if error else "complete"
    transaction["error"] = error
    transaction.pop("preparation", None)
    transaction["expires_at"] = time.time() + _OAUTH_COMPLETED_RETENTION_SECONDS
    _schedule_oauth_debug_cleanup(transaction["transaction_id"], _OAUTH_COMPLETED_RETENTION_SECONDS)
    if transaction.get("record"):
        debugger: AuthDebugger = transaction["debugger"]
        if debugger.recorder and debugger.recorder.current_recording:
            debugger.save_flow_recording(
                success=error is None and not debugger.has_failures(),
                error=error,
                filename=f"oauth_{transaction['transaction_id']}.json",
            )


def _mark_oauth_debug_transaction_processing(transaction: dict[str, Any]) -> None:
    """Protect a valid callback from pending expiry while network I/O runs."""
    transaction["status"] = "processing"
    transaction["expires_at"] = float("inf")
    handle = transaction.pop("cleanup_handle", None)
    if handle:
        handle.cancel()


def _cleanup_oauth_debug_transactions() -> None:
    now = time.time()
    expired_ids = [
        transaction_id
        for transaction_id, transaction in oauth_debug_transactions.items()
        if transaction["status"] != "processing" and transaction["expires_at"] <= now
    ]
    for transaction_id in expired_ids:
        _expire_oauth_debug_transaction(transaction_id)


def _schedule_oauth_debug_cleanup(transaction_id: str, delay: float) -> None:
    transaction = oauth_debug_transactions.get(transaction_id)
    if not transaction:
        return
    previous = transaction.pop("cleanup_handle", None)
    if previous:
        previous.cancel()
    transaction["cleanup_handle"] = asyncio.get_running_loop().call_later(
        delay,
        _expire_oauth_debug_transaction,
        transaction_id,
    )


def _expire_oauth_debug_transaction(transaction_id: str) -> None:
    transaction = oauth_debug_transactions.pop(transaction_id, None)
    if not transaction:
        return
    preparation = transaction.get("preparation") or {}
    state = preparation.get("state")
    if state:
        oauth_debug_states.pop(state, None)
    if transaction.get("record"):
        debugger: AuthDebugger = transaction["debugger"]
        if debugger.recorder and debugger.recorder.current_recording:
            debugger.save_flow_recording(
                success=False,
                error="OAuth debug transaction expired",
                filename=f"oauth_{transaction_id}.json",
            )
    handle = transaction.get("cleanup_handle")
    if handle:
        handle.cancel()


def _oauth_callback_page(title: str, message: str) -> str:
    return f"""<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>{html.escape(title)}</title></head>
  <body style="font-family: sans-serif; max-width: 42rem; margin: 4rem auto; padding: 1rem">
    <h1>{html.escape(title)}</h1>
    <p>{html.escape(message)}</p>
    <script>setTimeout(() => window.close(), 1200);</script>
  </body>
</html>"""


def _oauth_callback_response(
    title: str,
    message: str,
    *,
    status_code: int = 200,
) -> HTMLResponse:
    return HTMLResponse(
        _oauth_callback_page(title, message),
        status_code=status_code,
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
        },
    )


def _require_same_origin(request: Request) -> None:
    """Block cross-site browsers from driving localhost auth requests."""
    origin = request.headers.get("origin")
    expected_origin = str(request.base_url).rstrip("/")
    if origin and origin.rstrip("/") != expected_origin:
        raise HTTPException(status_code=403, detail="Cross-origin authentication denied")


@router.post("/mcp/profiles/{profile_id}/debug-auth", response_model=DebugAuthResponse)
async def debug_profile_auth(profile_id: str, http_request: Request):
    """Debug authentication for a specific MCP profile."""
    from testmcpy.mcp_profiles import get_profile_config

    try:
        _require_same_origin(http_request)
        profile_config = get_profile_config()

        if not profile_config.has_profiles():
            raise HTTPException(status_code=404, detail="No profiles configured")

        profile = profile_config.get_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")

        if not profile.mcps:
            raise HTTPException(
                status_code=400, detail=f"Profile '{profile_id}' has no MCP servers configured"
            )

        # Get auth from first MCP server
        mcp_server = profile.mcps[0]
        auth = mcp_server.auth
        if not auth or not auth.auth_type:
            raise HTTPException(
                status_code=400, detail=f"Profile '{profile_id}' has no authentication configured"
            )

        # Build request from resolved auth config
        auth_type = auth.auth_type.lower()

        if auth_type == "oauth":
            request = DebugAuthRequest(
                auth_type="oauth",
                client_id=auth.client_id,
                client_secret=auth.client_secret,
                token_url=auth.token_url,
                scopes=auth.scopes or [],
                oauth_auto_discover=auth.oauth_auto_discover,
                mcp_url=mcp_server.mcp_url,
                insecure=auth.insecure,
            )
        elif auth_type == "jwt":
            request = DebugAuthRequest(
                auth_type="jwt",
                api_url=auth.api_url,
                api_token=auth.api_token,
                api_secret=auth.api_secret,
            )
        elif auth_type == "bearer":
            request = DebugAuthRequest(
                auth_type="bearer", token=auth.token, mcp_url=mcp_server.mcp_url
            )
        else:
            raise HTTPException(
                status_code=400, detail=f"Unsupported auth type in profile: {auth_type}"
            )

        redirect_uri = str(http_request.url_for("oauth_debugger_callback"))
        return await debug_auth(request, redirect_uri=redirect_uri)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to debug profile auth: {str(e)}")


# Auth Flow Recording API endpoints


@router.get("/auth-flows", response_model=list[AuthFlowListItem])
async def list_auth_flows(
    auth_type: str | None = Query(None, description="Filter by auth type (oauth, jwt, bearer)"),
    limit: int | None = Query(None, description="Maximum number of recordings to return"),
):
    """List all saved authentication flow recordings."""
    try:
        recordings = auth_flow_recorder.list_recordings(auth_type=auth_type, limit=limit)
        return recordings
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list auth flows: {str(e)}")


@router.get("/auth-flows/{filename}")
async def get_auth_flow(filename: str):
    """Get a specific authentication flow recording."""
    try:
        filepath = auth_flow_recorder.storage_dir / filename
        if not filepath.exists():
            raise HTTPException(
                status_code=404, detail=f"Auth flow recording '{filename}' not found"
            )

        recording = auth_flow_recorder.load_recording(filepath)
        return recording.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load auth flow: {str(e)}")


@router.delete("/auth-flows/{filename}")
async def delete_auth_flow(filename: str):
    """Delete an authentication flow recording."""
    try:
        filepath = auth_flow_recorder.storage_dir / filename
        if not filepath.exists():
            raise HTTPException(
                status_code=404, detail=f"Auth flow recording '{filename}' not found"
            )

        auth_flow_recorder.delete_recording(filepath)
        return {"message": f"Auth flow '{filename}' deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete auth flow: {str(e)}")


@router.post("/auth-flows/compare")
async def compare_auth_flows(request: AuthFlowCompareRequest):
    """Compare two authentication flow recordings."""
    try:
        # Load both recordings
        filepath1 = Path(request.filepath1)
        filepath2 = Path(request.filepath2)

        if not filepath1.exists():
            raise HTTPException(
                status_code=404, detail=f"Recording 1 not found: {request.filepath1}"
            )
        if not filepath2.exists():
            raise HTTPException(
                status_code=404, detail=f"Recording 2 not found: {request.filepath2}"
            )

        recording1 = auth_flow_recorder.load_recording(filepath1)
        recording2 = auth_flow_recorder.load_recording(filepath2)

        # Compare recordings
        comparison = auth_flow_recorder.compare_recordings(recording1, recording2)
        return comparison
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to compare auth flows: {str(e)}")


@router.post("/auth-flows/{filename}/export")
async def export_auth_flow(
    filename: str, sanitize: bool = Query(True, description="Remove sensitive data")
):
    """Export an authentication flow recording as JSON (optionally sanitized)."""
    try:
        filepath = auth_flow_recorder.storage_dir / filename
        if not filepath.exists():
            raise HTTPException(
                status_code=404, detail=f"Auth flow recording '{filename}' not found"
            )

        recording = auth_flow_recorder.load_recording(filepath)

        if sanitize:
            recording = auth_flow_recorder.sanitize_recording(recording)

        return recording.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to export auth flow: {str(e)}")
