"""CLI integration tests for `testmcpy bench` planning and arg handling."""

import pytest
import yaml


@pytest.fixture
def suite_file(tmp_path):
    path = tmp_path / "suite.yaml"
    path.write_text(yaml.dump({"tests": [{"name": "t1", "prompt": "hi", "evaluators": []}]}))
    return path


def test_dry_run_plans_cross_product(runner, cli_app, suite_file):
    result = runner.invoke(
        cli_app,
        [
            "bench",
            str(suite_file),
            "--models",
            "claude-sonnet-4-5,gpt-4o",
            "--providers",
            "anthropic,openai",
            "--profiles",
            "staging,prod",
            "--repeat",
            "3",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "= 12 runs" in result.stdout  # 2 models x 2 profiles x 3 repeats
    assert "anthropic/claude-sonnet-4-5 @ staging" in result.stdout
    assert "openai/gpt-4o @ prod" in result.stdout


def test_single_provider_broadcasts(runner, cli_app, suite_file):
    result = runner.invoke(
        cli_app,
        [
            "bench",
            str(suite_file),
            "--models",
            "a,b",
            "--providers",
            "anthropic",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "anthropic/a" in result.stdout
    assert "anthropic/b" in result.stdout


def test_provider_count_mismatch_errors(runner, cli_app, suite_file):
    result = runner.invoke(
        cli_app,
        ["bench", str(suite_file), "--models", "a,b,c", "--providers", "x,y", "--dry-run"],
    )
    assert result.exit_code == 1
    assert "providers" in result.stdout


def test_missing_path_errors(runner, cli_app, tmp_path):
    result = runner.invoke(
        cli_app, ["bench", str(tmp_path / "nope.yaml"), "--models", "a", "--dry-run"]
    )
    assert result.exit_code == 1


def test_bench_invokes_run_subprocesses(runner, cli_app, suite_file, monkeypatch):
    """Without --dry-run, bench spawns one `run` subprocess per combo."""
    import testmcpy.cli.commands.bench as bench_mod

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)

        class Proc:
            returncode = 0

        return Proc()

    monkeypatch.setattr(bench_mod.subprocess, "run", fake_run)
    result = runner.invoke(
        cli_app,
        ["bench", str(suite_file), "--models", "m1,m2", "--repeat", "2"],
    )
    assert result.exit_code == 0
    assert len(calls) == 4  # 2 models x 1 profile x 2 repeats
    # Every subprocess shares the same session id
    session_ids = {cmd[cmd.index("--session-id") + 1] for cmd in calls}
    assert len(session_ids) == 1
    assert all("--model" in cmd for cmd in calls)
    assert "testmcpy matrix" in result.stdout
