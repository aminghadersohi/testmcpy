"""Read-only + cancel endpoints for in-flight runs in the run registry.

Backs the global "background runs" indicator in the UI: any page can
poll ``GET /api/runs`` to see what's still going, and POST
``/api/runs/{run_id}/stop`` to kill a run without having to navigate
back to /tests and re-attach a WebSocket. SC-108217.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from testmcpy.server import run_registry
from testmcpy.server.run_persistence import wire_status_for_db_status
from testmcpy.storage import get_storage

router = APIRouter(prefix="/api", tags=["runs"])


def _serialise(handle: run_registry.RunHandle) -> dict[str, Any]:
    """Public view of a RunHandle. Strips the asyncio task / queue / log
    buffer — those are server-internals."""
    return {
        "run_id": handle.run_id,
        "kind": handle.kind,
        "status": handle.status,
        "started_at": handle.started_at.isoformat(),
        "finished_at": handle.finished_at.isoformat() if handle.finished_at else None,
        # `meta` carries the original command's `test_path` / `files` etc.
        # so the UI can show a meaningful label (e.g. "chatbot 4 files"
        # rather than just the opaque run_id).
        "meta": {
            "test_path": handle.meta.get("test_path"),
            "test_name": handle.meta.get("test_name"),
            "folder": handle.meta.get("folder"),
            "files": [
                {"name": f.get("name"), "test_path": f.get("test_path")}
                for f in (handle.meta.get("files") or [])
            ],
            "model": handle.meta.get("model"),
            "provider": handle.meta.get("provider"),
        },
        "summary": handle.summary,
        "result_count": len(handle.results),
        "log_count": len(handle.log_buffer),
        "is_attached": handle.attached_queue is not None,
    }


@router.get("/runs")
async def list_runs(active_only: bool = True) -> dict[str, Any]:
    """List runs in the registry. By default returns only in-flight runs;
    pass ``?active_only=false`` to also include recently-finished ones
    (within the registry's cleanup TTL)."""
    if active_only:
        handles = await run_registry.list_active()
    else:
        # No "list all" helper today — peek at the module dict under the
        # lock so we don't race with create_run.
        async with run_registry._lock:  # noqa: SLF001 — module-internal access
            handles = list(run_registry._runs.values())
    return {"runs": [_serialise(h) for h in handles]}


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    handle = await run_registry.get_run(run_id)
    if handle is not None:
        return _serialise(handle)
    # Registry miss (GC'd after CLEANUP_TTL, or a server restart) — fall
    # back to the results DB so a stale tab asking about its run gets the
    # final state instead of a 404. ``source: history`` tells the client
    # this is a finished record, not a live handle.
    record = get_storage().get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    status = wire_status_for_db_status(record.get("status"))
    return {
        "run_id": run_id,
        "kind": "single",
        "status": status,
        "started_at": record.get("started_at"),
        "finished_at": record.get("completed_at"),
        "meta": {
            "test_path": record.get("test_id"),
            "model": record.get("model"),
            "provider": record.get("provider"),
        },
        "summary": record.get("summary"),
        "result_count": len(record.get("question_results") or []),
        "is_attached": False,
        "source": "history",
    }


@router.post("/runs/{run_id}/stop")
async def stop_run(run_id: str) -> dict[str, Any]:
    """Fire-and-forget cancellation. Returns immediately after signalling
    the task — the actual cancellation propagates at the next await point
    in the runner (LLM call boundary). The UI should poll
    ``GET /api/runs/{run_id}`` (or attach via WebSocket) to see the
    transition to ``status=stopped``."""
    handle = await run_registry.get_run(run_id)
    if handle is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    if handle.is_finished:
        return {"run_id": run_id, "status": handle.status, "noop": True}
    if handle.task is None:
        # Pathological — a handle without a task should never have been
        # created by the dispatcher.
        raise HTTPException(status_code=500, detail="Run has no associated task")
    handle.task.cancel()
    # Mirror the WebSocket "stopping" ack so any client currently attached
    # transitions to its "stopping…" UI state.
    run_registry.event(handle, {"type": "stopping", "run_id": handle.run_id})
    run_registry.log(handle, "🛑 Stop requested via /api/runs — cancelling…")
    return {"run_id": run_id, "status": "stopping"}
