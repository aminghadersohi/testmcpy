"""
API routes for MCP server health monitoring.

Pings each configured MCP server and returns status + response time.
"""

import asyncio
import time
from typing import Any

from fastapi import APIRouter

from testmcpy.mcp_profiles import get_profile_config

router = APIRouter(prefix="/api/health", tags=["health"])

# Timeout for individual server pings (seconds)
PING_TIMEOUT = 15.0

# Track last successful ping time per server key "{profile_id}:{server_name}"
_last_success: dict[str, str] = {}


async def _ping_server(mcp_server, profile_id: str, profile_name: str) -> dict[str, Any]:
    """Ping a single MCP server by trying to list its tools."""
    from testmcpy.src.mcp_client import MCPClient

    result = {
        "profile_id": profile_id,
        "profile_name": profile_name,
        "server_name": mcp_server.name,
        "server_url": mcp_server.mcp_url,
        "status": "unknown",
        "response_time_ms": None,
        "tool_count": None,
        "error": None,
        "error_class": None,
        "last_success_at": None,
        "checked_at": None,
    }

    server_key = f"{profile_id}:{mcp_server.name}"
    start = time.time()
    client = None
    try:
        auth_dict = mcp_server.auth.to_dict() if mcp_server.auth else None
        client = MCPClient(mcp_server.mcp_url, auth=auth_dict)

        await asyncio.wait_for(client.initialize(), timeout=PING_TIMEOUT)
        tools = await asyncio.wait_for(client.list_tools(), timeout=PING_TIMEOUT)

        elapsed_ms = (time.time() - start) * 1000
        result["status"] = "healthy"
        result["response_time_ms"] = round(elapsed_ms, 1)
        result["tool_count"] = len(tools)

        from datetime import datetime, timezone

        result["checked_at"] = datetime.now(timezone.utc).isoformat()
        _last_success[server_key] = result["checked_at"]
        result["last_success_at"] = result["checked_at"]
        return result

    except asyncio.TimeoutError:
        elapsed_ms = (time.time() - start) * 1000
        result["status"] = "timeout"
        result["response_time_ms"] = round(elapsed_ms, 1)
        result["error"] = f"Timed out after {PING_TIMEOUT}s"
    except (ConnectionError, OSError) as e:
        elapsed_ms = (time.time() - start) * 1000
        result["status"] = "unreachable"
        result["response_time_ms"] = round(elapsed_ms, 1)
        result["error"] = str(e)
    except (RuntimeError, ValueError, TypeError, AttributeError) as e:
        error_class = type(e).__name__
        result["error_class"] = error_class

        # Retry once after a short delay — auth servers may need warmup
        await asyncio.sleep(2.0)

        retry_client = None
        try:
            auth_dict = mcp_server.auth.to_dict() if mcp_server.auth else None
            retry_client = MCPClient(mcp_server.mcp_url, auth=auth_dict)

            await asyncio.wait_for(retry_client.initialize(), timeout=PING_TIMEOUT)
            tools = await asyncio.wait_for(retry_client.list_tools(), timeout=PING_TIMEOUT)

            elapsed_ms = (time.time() - start) * 1000
            result["status"] = "healthy"
            result["response_time_ms"] = round(elapsed_ms, 1)
            result["tool_count"] = len(tools)
            result["error_class"] = None

            from datetime import datetime, timezone

            result["checked_at"] = datetime.now(timezone.utc).isoformat()
            _last_success[server_key] = result["checked_at"]
            result["last_success_at"] = result["checked_at"]
            return result

        except (
            RuntimeError,
            ValueError,
            TypeError,
            AttributeError,
            asyncio.TimeoutError,
            ConnectionError,
            OSError,
        ) as retry_e:
            elapsed_ms = (time.time() - start) * 1000
            result["status"] = "error"
            result["response_time_ms"] = round(elapsed_ms, 1)
            result["error"] = str(retry_e)
            result["error_class"] = error_class
        finally:
            if retry_client is not None:
                try:
                    await retry_client.close()
                except (ConnectionError, OSError, RuntimeError):
                    pass
    finally:
        if client is not None:
            try:
                await client.close()
            except (ConnectionError, OSError, RuntimeError):
                pass

    from datetime import datetime, timezone

    result["checked_at"] = datetime.now(timezone.utc).isoformat()
    result["last_success_at"] = _last_success.get(server_key)
    return result


@router.get("/mcp")
async def check_mcp_health() -> dict[str, Any]:
    """
    Ping each configured MCP server and return health status.

    For each server: tries to call list_tools with a short timeout,
    recording success/latency or error.
    """
    profile_config = get_profile_config()

    if not profile_config.has_profiles():
        return {"servers": [], "total": 0, "healthy": 0, "unhealthy": 0}

    # Gather all servers from all profiles
    tasks = []
    for profile_id in profile_config.list_profiles():
        profile = profile_config.get_profile(profile_id)
        if not profile:
            continue
        for mcp_server in profile.mcps:
            tasks.append(_ping_server(mcp_server, profile_id, profile.name))

    # Run all pings concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)

    servers = []
    for r in results:
        if isinstance(r, dict):
            servers.append(r)
        else:
            # Shouldn't happen but handle gracefully
            servers.append(
                {
                    "status": "error",
                    "error": str(r),
                }
            )

    healthy = sum(1 for s in servers if s.get("status") == "healthy")

    return {
        "servers": servers,
        "total": len(servers),
        "healthy": healthy,
        "unhealthy": len(servers) - healthy,
    }
