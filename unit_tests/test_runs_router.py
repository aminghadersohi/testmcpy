"""Unit tests for the /api/runs read + cancel router.

Backs the global "in-flight runs" indicator. The endpoints are thin
wrappers around the in-memory run_registry, so tests just drive the
registry directly and verify what comes back over HTTP.
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from testmcpy.server import run_registry
from testmcpy.server.routers.runs import router


@pytest_asyncio.fixture(autouse=True)
async def _isolated_registry():
    await run_registry.reset_for_tests()
    yield
    await run_registry.reset_for_tests()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Point get_storage() at a temp DB — the GET /api/runs/{id} history
    fallback must never read the developer's real .testmcpy/storage.db."""
    import testmcpy.storage as storage_module
    from testmcpy.storage import TestStorage

    storage = TestStorage(db_path=tmp_path / "runs_router.db")
    monkeypatch.setattr(storage_module, "_storage", storage)
    yield storage
    monkeypatch.setattr(storage_module, "_storage", None)


@pytest_asyncio.fixture
async def client():
    """Async HTTP client driving the FastAPI app via ASGITransport.

    Sync TestClient runs handlers on a worker-thread event loop,
    which can't await on registry locks created on the test's loop.
    The ASGI transport keeps everything on a single loop.
    """
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_list_runs_empty(client):
    r = await client.get("/api/runs")
    assert r.status_code == 200
    assert r.json() == {"runs": []}


@pytest.mark.asyncio
async def test_list_runs_returns_only_active_by_default(client):
    """Default `active_only=true` filters out finished runs. The UI's
    background-runs indicator polls this — surfacing a finished run as
    "in-flight" would be a UI bug."""
    active = await run_registry.create_run(kind="single", meta={"test_path": "/a.yaml"})
    finished = await run_registry.create_run(kind="single", meta={"test_path": "/b.yaml"})
    await run_registry.finalize(finished.run_id, status="completed")

    r = await client.get("/api/runs")
    assert r.status_code == 200
    ids = [run["run_id"] for run in r.json()["runs"]]
    assert active.run_id in ids
    assert finished.run_id not in ids


@pytest.mark.asyncio
async def test_list_runs_active_only_false_includes_finished(client):
    finished = await run_registry.create_run(kind="single", meta={})
    await run_registry.finalize(finished.run_id, status="completed")
    r = await client.get("/api/runs?active_only=false")
    ids = [run["run_id"] for run in r.json()["runs"]]
    assert finished.run_id in ids


@pytest.mark.asyncio
async def test_get_run_serialises_handle_with_meta(client):
    """Indicator labels rely on `meta.folder` / `meta.files` for batches
    and `meta.test_path` for singles — pin the shape so a future
    refactor that drops fields doesn't silently make the UI display
    blank labels."""
    handle = await run_registry.create_run(
        kind="directory",
        meta={
            "folder": "chatbot",
            "files": [
                {"test_path": "/x/C01.yaml", "name": "C01.yaml"},
                {"test_path": "/x/C02.yaml", "name": "C02.yaml"},
            ],
            "model": "claude",
            "provider": "claude-sdk",
        },
    )
    r = await client.get(f"/api/runs/{handle.run_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == handle.run_id
    assert body["kind"] == "directory"
    # Created directly on the registry (no slot acquired) — still queued.
    assert body["status"] == "queued"
    assert body["meta"]["folder"] == "chatbot"
    assert [f["name"] for f in body["meta"]["files"]] == ["C01.yaml", "C02.yaml"]
    assert body["meta"]["model"] == "claude"
    assert body["meta"]["provider"] == "claude-sdk"


@pytest.mark.asyncio
async def test_get_run_404_for_unknown_id(client):
    r = await client.get("/api/runs/does-not-exist")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_stop_run_cancels_task_and_emits_stopping_event(client):
    """The whole point of the endpoint: hitting it cancels the asyncio
    task AND broadcasts a `stopping` event so any client currently
    attached transitions to the "Stopping…" UI."""
    import asyncio

    async def _long_running():
        await asyncio.sleep(60)

    handle = await run_registry.create_run(kind="single", meta={})
    handle.task = asyncio.create_task(_long_running())
    # Let the task actually enter its sleep before we ask to cancel —
    # otherwise the cancel races with task scheduling.
    await asyncio.sleep(0.05)
    queue, _token = await run_registry.attach(handle)

    r = await client.post(f"/api/runs/{handle.run_id}/stop")
    assert r.status_code == 200
    assert r.json()["status"] == "stopping"

    # Awaiting the task directly verifies cancellation propagated.
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(handle.task, timeout=1.0)

    # `stopping` event landed on the attached queue.
    stopping_evt = queue.get_nowait()
    assert stopping_evt == {"type": "stopping", "run_id": handle.run_id}


@pytest.mark.asyncio
async def test_stop_run_on_finished_handle_is_noop(client):
    """A run that already finished (or was already stopped) returns 200
    with `noop: true` instead of trying to re-cancel a dead task. The
    indicator polls this on a 5s interval; a 404 or 500 here would
    spam the user's console."""
    handle = await run_registry.create_run(kind="single", meta={})
    await run_registry.finalize(handle.run_id, status="completed")

    r = await client.post(f"/api/runs/{handle.run_id}/stop")
    assert r.status_code == 200
    assert r.json()["noop"] is True
    assert r.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_stop_run_404_for_unknown_id(client):
    r = await client.post("/api/runs/nope/stop")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# History fallback (registry miss -> results DB)
# ---------------------------------------------------------------------------


def _seed_db_run(storage, run_id, status="completed"):
    from datetime import datetime, timezone

    storage.save_suite(suite_id="suite.yaml", name="suite.yaml", questions=[])
    storage.save_run(
        run_id=run_id,
        test_id="suite.yaml",
        test_version=1,
        model="m1",
        provider="p1",
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    storage.save_question_result(
        run_id=run_id, question_id="t1", passed=True, score=1.0, cost_usd=0.02
    )
    if status != "running":
        storage.finish_run(run_id, status=status)


@pytest.mark.asyncio
async def test_get_run_falls_back_to_db_history(client, isolated_storage):
    """A run GC'd from the registry (or lost to a restart) must resolve
    from the results DB instead of 404ing on a stale tab."""
    _seed_db_run(isolated_storage, "hist_1", status="completed")
    r = await client.get("/api/runs/hist_1")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "history"
    assert body["status"] == "completed"
    assert body["result_count"] == 1
    assert body["meta"]["test_path"] == "suite.yaml"
    assert body["summary"]["passed"] == 1


@pytest.mark.asyncio
async def test_get_run_history_reports_dead_running_row_as_interrupted(client, isolated_storage):
    """status=running in the DB with no registry handle means the server
    died mid-run — the wire status must be interrupted, not a zombie
    'running' that spins forever in the UI."""
    _seed_db_run(isolated_storage, "hist_2", status="running")
    r = await client.get("/api/runs/hist_2")
    assert r.status_code == 200
    assert r.json()["status"] == "interrupted"
