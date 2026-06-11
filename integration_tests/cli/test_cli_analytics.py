"""CLI integration tests for matrix / leaderboard / flaky commands."""

import json

import pytest

from testmcpy.storage import TestStorage


@pytest.fixture
def seeded_db(tmp_path):
    """Temp results DB: claude 3 runs (q1 pass, q2 flaky 2/3), gpt 1 run."""
    db_path = tmp_path / "results.db"
    storage = TestStorage(db_path=db_path)
    for i, q2_passed in enumerate([True, True, False], start=1):
        started = f"2026-06-{i:02d}T10:00:00"
        storage.save_run(
            run_id=f"c{i}",
            test_id="suite-A",
            test_version=1,
            model="claude-sonnet-4-5",
            provider="anthropic",
            started_at=started,
            mcp_profile_id="staging",
        )
        storage.save_question_result(
            run_id=f"c{i}", question_id="q1", passed=True, score=1.0, cost_usd=0.01
        )
        storage.save_question_result(
            run_id=f"c{i}", question_id="q2", passed=q2_passed, score=1.0, cost_usd=0.01
        )
        storage.complete_run(f"c{i}", started)
    storage.save_run(
        run_id="g1",
        test_id="suite-A",
        test_version=1,
        model="gpt-4o",
        provider="openai",
        started_at="2026-06-01T11:00:00",
        mcp_profile_id="staging",
    )
    storage.save_question_result(run_id="g1", question_id="q1", passed=False, score=0.0)
    storage.complete_run("g1", "2026-06-01T11:00:00")
    return str(db_path)


def test_matrix_table_output(runner, cli_app, seeded_db):
    result = runner.invoke(cli_app, ["matrix", "--db-path", seeded_db])
    assert result.exit_code == 0
    assert "q1" in result.stdout
    assert "q2" in result.stdout
    assert "claude-sonnet-4-5" in result.stdout
    assert "n=3" in result.stdout


def test_matrix_json_output(runner, cli_app, seeded_db):
    result = runner.invoke(cli_app, ["matrix", "--db-path", seeded_db, "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert {r["question_id"] for r in data["rows"]} == {"q1", "q2"}
    assert len(data["configs"]) == 2


def test_matrix_fail_below_exits_one(runner, cli_app, seeded_db):
    # gpt config is at 0% — gate on 50%
    result = runner.invoke(cli_app, ["matrix", "--db-path", seeded_db, "--fail-below", "0.5"])
    assert result.exit_code == 1
    assert "openai/gpt-4o" in result.stdout


def test_matrix_fail_below_passes(runner, cli_app, seeded_db):
    # The worst config (gpt) is at exactly 0% — a 0.0 threshold passes
    result = runner.invoke(cli_app, ["matrix", "--db-path", seeded_db, "--fail-below", "0.0"])
    assert result.exit_code == 0


def test_matrix_fail_below_scoped_to_suite(runner, cli_app, seeded_db):
    # Filtering to a nonexistent suite yields no configs — gate passes
    result = runner.invoke(
        cli_app,
        ["matrix", "--db-path", seeded_db, "--suite", "no-such-suite", "--fail-below", "0.99"],
    )
    assert result.exit_code == 0


def test_leaderboard_ranks_claude_first(runner, cli_app, seeded_db):
    result = runner.invoke(cli_app, ["leaderboard", "--db-path", seeded_db, "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["configs"][0]["key"] == "anthropic/claude-sonnet-4-5 @ staging"


def test_flaky_detects_q2(runner, cli_app, seeded_db):
    result = runner.invoke(cli_app, ["flaky", "--db-path", seeded_db, "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert len(data["flaky"]) == 1
    assert data["flaky"][0]["question_id"] == "q2"


def test_flaky_fail_on_flaky(runner, cli_app, seeded_db):
    result = runner.invoke(cli_app, ["flaky", "--db-path", seeded_db, "--fail-on-flaky"])
    assert result.exit_code == 1


def test_matrix_empty_db(runner, cli_app, tmp_path):
    TestStorage(db_path=tmp_path / "empty.db")
    result = runner.invoke(cli_app, ["matrix", "--db-path", str(tmp_path / "empty.db")])
    assert result.exit_code == 0
    assert "No completed runs" in result.stdout
