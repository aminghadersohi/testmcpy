"""Unit tests for testmcpy.server.run_persistence (incremental run records).

RunRecord is the crash-safety layer for UI-triggered runs: the run row is
created at start, each test result lands in the DB the moment it completes,
and the terminal status is stamped exactly once. These tests pin:

- begin/append/finish lifecycle produces the same DB shape as the legacy
  end-of-run save_test_run_to_file path.
- finish() is idempotent and first-status-wins.
- append/finish before begin are safe no-ops.
- A DB failure marks the record broken (reported once) without raising
  into the caller — a persistence hiccup must never kill a live run.
"""

import pytest
from sqlalchemy.exc import SQLAlchemyError

from testmcpy.server.run_persistence import RunRecord, mint_run_id, question_result_kwargs
from testmcpy.storage import TestStorage


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Point the get_storage() singleton at an isolated temp database."""
    import testmcpy.storage as storage_module

    storage = TestStorage(db_path=tmp_path / "test_run_persistence.db")
    monkeypatch.setattr(storage_module, "_storage", storage)
    yield storage
    monkeypatch.setattr(storage_module, "_storage", None)


def _result(name="t1", passed=True, cost=0.01):
    return {
        "test_name": name,
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "response": "answer text",
        "tool_calls": [{"name": "list_charts"}],
        "token_usage": {"input": 10, "output": 20},
        "duration": 1.5,
        "evaluations": [{"evaluator": "contains", "passed": passed}],
        "error": None,
        "cost": cost,
    }


def test_question_result_kwargs_mapping():
    kwargs = question_result_kwargs(_result())
    assert kwargs["question_id"] == "t1"
    assert kwargs["passed"] is True
    assert kwargs["answer"] == "answer text"
    assert kwargs["tokens_input"] == 10
    assert kwargs["tokens_output"] == 20
    assert kwargs["duration_ms"] == 1500
    assert kwargs["cost_usd"] == 0.01


def test_lifecycle_creates_incremental_rows(isolated_storage):
    record = RunRecord()
    record.begin(test_file="suite.yaml", model="m1", provider="p1", mcp_profile="prof")

    run = isolated_storage.get_run(record.run_id)
    assert run is not None
    assert run["question_results"] == []

    record.append(_result("t1", passed=True))
    mid = isolated_storage.get_run(record.run_id)
    assert len(mid["question_results"]) == 1
    assert mid["completed_at"] is None  # still in flight

    record.append(_result("t2", passed=False))
    record.finish("completed")

    final = isolated_storage.get_run(record.run_id)
    assert len(final["question_results"]) == 2
    assert final["completed_at"] is not None
    assert final["summary"]["passed"] == 1
    assert final["mcp_profile_id"] == "prof"


def test_finish_first_status_wins(isolated_storage):
    record = RunRecord()
    record.begin(test_file="suite.yaml", model="m1", provider="p1")
    record.append(_result())
    record.finish("stopped")
    record.finish("completed")  # late finalizer must not overwrite

    with isolated_storage.session() as session:
        from testmcpy.models import TestRunModel

        row = session.query(TestRunModel).filter_by(run_id=record.run_id).one()
        assert row.status == "stopped"


def test_append_and_finish_before_begin_are_noops(isolated_storage):
    record = RunRecord()
    record.append(_result())
    record.finish("completed")
    assert isolated_storage.get_run(record.run_id) is None


def test_db_error_marks_broken_without_raising(isolated_storage, monkeypatch):
    logs: list[str] = []
    record = RunRecord(log=logs.append)
    record.begin(test_file="suite.yaml", model="m1", provider="p1")

    def _boom(*args, **kwargs):
        raise SQLAlchemyError("disk on fire")

    monkeypatch.setattr(isolated_storage, "save_question_result", _boom)
    record.append(_result())  # must not raise
    assert any("Results DB unavailable" in line for line in logs)

    # Broken record: subsequent calls no-op (no second report, no raise).
    record.append(_result("t2"))
    record.finish("completed")
    assert len([line for line in logs if "Results DB unavailable" in line]) == 1


def test_explicit_run_id_is_honored(isolated_storage):
    rid = mint_run_id()
    record = RunRecord(run_id=rid)
    record.begin(test_file="suite.yaml", model="m1", provider="p1")
    assert isolated_storage.get_run(rid) is not None


def test_storage_finish_run_statuses(isolated_storage):
    for status in ("error", "stopped", "interrupted"):
        rid = mint_run_id()
        record = RunRecord(run_id=rid)
        record.begin(test_file="suite.yaml", model="m1", provider="p1")
        record.finish(status)
        with isolated_storage.session() as session:
            from testmcpy.models import TestRunModel

            row = session.query(TestRunModel).filter_by(run_id=rid).one()
            assert row.status == status
            assert row.completed_at is not None
