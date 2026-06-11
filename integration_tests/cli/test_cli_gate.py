"""CLI integration tests for `run --gate` / `--min-pass-rate` exit-code wiring."""

import pytest
import yaml

from testmcpy.src.test_runner import TestResult


@pytest.fixture
def suite_file(tmp_path, monkeypatch):
    """Single-test suite in an isolated cwd so run artifacts stay in tmp."""
    monkeypatch.chdir(tmp_path)
    # In real CI this env var points at the live job summary — without
    # this, every invoke here appends a fake report block to it. The
    # step-summary test re-sets it explicitly.
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    path = tmp_path / "suite.yaml"
    path.write_text(
        yaml.dump(
            {
                "tests": [
                    {
                        "name": "t1",
                        "prompt": "say hi",
                        "evaluators": [
                            {"name": "final_answer_contains", "args": {"content": "hi"}}
                        ],
                    }
                ]
            }
        )
    )
    return path


@pytest.fixture
def stub_execution(monkeypatch):
    """Stub out LLM/MCP so the run command exercises only CLI wiring."""
    from testmcpy.server import state
    from testmcpy.src import test_runner as tr

    async def no_mcp_client(profile):
        return None

    monkeypatch.setattr(state, "get_or_create_mcp_client", no_mcp_client)

    def set_outcome(passed: bool):
        async def fake_initialize(self):
            return None

        async def fake_run(self, test_case):
            return TestResult(
                test_name=test_case.name,
                passed=passed,
                score=1.0 if passed else 0.0,
                duration=0.01,
            )

        monkeypatch.setattr(tr.TestRunner, "initialize", fake_initialize)
        monkeypatch.setattr(tr.TestRunner, "_run_test_with_retry", fake_run)

    return set_outcome


def test_failing_run_without_gate_exits_zero(runner, cli_app, suite_file, stub_execution):
    """Without --gate, a failing suite keeps the historical exit-0 contract."""
    stub_execution(passed=False)
    result = runner.invoke(cli_app, ["run", str(suite_file)])
    assert result.exit_code == 0
    assert "CI Gate" not in result.stdout


def test_failing_run_with_gate_exits_one(runner, cli_app, suite_file, stub_execution):
    stub_execution(passed=False)
    result = runner.invoke(cli_app, ["run", str(suite_file), "--gate"])
    assert result.exit_code == 1
    assert "CI Gate" in result.stdout
    assert "FAILED" in result.stdout


def test_passing_run_with_gate_exits_zero(runner, cli_app, suite_file, stub_execution):
    stub_execution(passed=True)
    result = runner.invoke(cli_app, ["run", str(suite_file), "--gate"])
    assert result.exit_code == 0
    assert "CI Gate" in result.stdout
    assert "PASSED" in result.stdout


def test_min_pass_rate_implies_gate(runner, cli_app, suite_file, stub_execution):
    stub_execution(passed=False)
    result = runner.invoke(cli_app, ["run", str(suite_file), "--min-pass-rate", "50"])
    assert result.exit_code == 1
    assert "CI Gate" in result.stdout


def test_gate_config_file_is_honored(runner, cli_app, suite_file, stub_execution, tmp_path):
    stub_execution(passed=True)
    gate_path = tmp_path / "gate.yaml"
    gate_path.write_text(yaml.dump({"min_pass_rate": 100.0}))
    result = runner.invoke(cli_app, ["run", str(suite_file), "--gate-config", str(gate_path)])
    assert result.exit_code == 0
    assert "CI Gate" in result.stdout


def test_missing_gate_config_errors(runner, cli_app, suite_file, stub_execution, tmp_path):
    stub_execution(passed=True)
    result = runner.invoke(
        cli_app, ["run", str(suite_file), "--gate-config", str(tmp_path / "nope.yaml")]
    )
    assert result.exit_code == 1
    assert "gate config does not exist" in result.stdout


def test_github_step_summary_appended(
    runner, cli_app, suite_file, stub_execution, tmp_path, monkeypatch
):
    stub_execution(passed=True)
    summary_path = tmp_path / "step_summary.md"
    summary_path.write_text("existing content\n")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    result = runner.invoke(cli_app, ["run", str(suite_file)])
    assert result.exit_code == 0
    content = summary_path.read_text()
    assert content.startswith("existing content\n")  # appended, not overwritten
    assert "t1" in content


def test_junit_xml_written(runner, cli_app, suite_file, stub_execution, tmp_path):
    import xml.etree.ElementTree as ET

    stub_execution(passed=False)
    junit_path = tmp_path / "reports" / "junit.xml"
    result = runner.invoke(cli_app, ["run", str(suite_file), "--junit-xml", str(junit_path)])
    assert result.exit_code == 0
    root = ET.parse(junit_path).getroot()
    assert root.get("tests") == "1"
    assert root.get("failures") == "1"
    assert root.find("testcase").get("name") == "t1"
