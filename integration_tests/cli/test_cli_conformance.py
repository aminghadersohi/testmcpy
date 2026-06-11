"""CLI integration tests for `testmcpy conformance` (subprocess mocked)."""

import json

import pytest


@pytest.fixture
def fake_suite(monkeypatch, tmp_path):
    """Mock shutil.which + subprocess.run to emit a canned checks.json."""
    import testmcpy.cli.commands.conformance as conf_mod

    monkeypatch.setattr(conf_mod.shutil, "which", lambda _: "/usr/bin/npx")

    def install(checks, stderr=""):
        def fake_run(cmd, cwd=None, **kwargs):
            results_dir = conf_mod.Path(cwd) / "results" / "server-initialize-123"
            results_dir.mkdir(parents=True)
            (results_dir / "checks.json").write_text(json.dumps(checks))

            class Proc:
                stdout = ""

            Proc.stderr = stderr
            return Proc()

        monkeypatch.setattr(conf_mod.subprocess, "run", fake_run)

    return install


PASSING = [
    {"id": "init", "name": "ServerInitialize", "status": "SUCCESS"},
    {"id": "info", "name": "ServerInfo", "status": "INFO"},  # ungraded
]
FAILING = PASSING + [
    {
        "id": "auth",
        "name": "OAuthValidation",
        "status": "FAILURE",
        "errorMessage": "missing iss validation",
    }
]
WARNING_ONLY = PASSING + [
    {"id": "sse", "name": "SSERetry", "status": "WARNING", "errorMessage": "slow reconnect"}
]


def test_passing_suite_exits_zero(runner, cli_app, fake_suite):
    fake_suite(PASSING)
    result = runner.invoke(cli_app, ["conformance", "http://localhost:1/mcp"])
    assert result.exit_code == 0
    assert "1/1 passed" in result.stdout


def test_failure_exits_one_with_detail(runner, cli_app, fake_suite):
    fake_suite(FAILING)
    result = runner.invoke(cli_app, ["conformance", "http://localhost:1/mcp"])
    assert result.exit_code == 1
    assert "OAuthValidation" in result.stdout
    assert "missing iss validation" in result.stdout


def test_warning_passes_unless_flagged(runner, cli_app, fake_suite):
    fake_suite(WARNING_ONLY)
    assert runner.invoke(cli_app, ["conformance", "http://x/mcp"]).exit_code == 0
    assert (
        runner.invoke(cli_app, ["conformance", "http://x/mcp", "--fail-on-warning"]).exit_code == 1
    )


def test_json_output(runner, cli_app, fake_suite):
    fake_suite(FAILING)
    result = runner.invoke(cli_app, ["conformance", "http://x/mcp", "--format", "json"])
    data = json.loads(result.stdout)
    assert data["failed"] == 1
    assert data["passed"] == 1
    assert data["total"] == 2  # INFO checks are not graded


def test_output_file_written(runner, cli_app, fake_suite, tmp_path):
    fake_suite(PASSING)
    out = tmp_path / "checks.json"
    result = runner.invoke(cli_app, ["conformance", "http://x/mcp", "--output", str(out)])
    assert result.exit_code == 0
    assert json.loads(out.read_text())["url"] == "http://x/mcp"


def test_missing_npx_exits_two(runner, cli_app, monkeypatch):
    import testmcpy.cli.commands.conformance as conf_mod

    monkeypatch.setattr(conf_mod.shutil, "which", lambda _: None)
    result = runner.invoke(cli_app, ["conformance", "http://x/mcp"])
    assert result.exit_code == 2
    assert "npx not found" in result.stdout


def test_no_checks_shows_node_hint(runner, cli_app, monkeypatch):
    import testmcpy.cli.commands.conformance as conf_mod

    monkeypatch.setattr(conf_mod.shutil, "which", lambda _: "/usr/bin/npx")

    def fake_run(cmd, cwd=None, **kwargs):
        class Proc:
            stdout = ""
            stderr = "SyntaxError: globSync"

        return Proc()

    monkeypatch.setattr(conf_mod.subprocess, "run", fake_run)
    result = runner.invoke(cli_app, ["conformance", "http://x/mcp"])
    assert result.exit_code == 2
    assert "Node.js 22+" in result.stdout
