"""CLI integration tests for `testmcpy badge` + unified gate sections."""

import json

import pytest
import yaml

from testmcpy.src.ci_gate import load_gate_config, load_gate_section
from testmcpy.storage import TestStorage


class TestUnifiedGateConfig:
    def test_sectioned_evals(self, tmp_path):
        path = tmp_path / "gate.yaml"
        path.write_text(
            yaml.dump(
                {
                    "evals": {"min_pass_rate": 92.5, "max_failures": 1},
                    "usability": {"min_score": 75},
                    "conformance": {"required": True, "fail_on_warning": True},
                    "security": {"max_severity": "medium"},
                }
            )
        )
        config = load_gate_config(str(path))
        assert config.min_pass_rate == 92.5
        assert config.max_failures == 1
        assert load_gate_section("usability", str(path)) == {"min_score": 75}
        assert load_gate_section("conformance", str(path))["fail_on_warning"] is True
        assert load_gate_section("security", str(path))["max_severity"] == "medium"

    def test_flat_layout_still_works(self, tmp_path):
        path = tmp_path / "gate.yaml"
        path.write_text(yaml.dump({"min_pass_rate": 70.0}))
        assert load_gate_config(str(path)).min_pass_rate == 70.0
        assert load_gate_section("usability", str(path)) == {}

    def test_missing_file_defaults(self, tmp_path):
        path = str(tmp_path / "nope.yaml")
        assert load_gate_config(path).min_pass_rate == 80.0
        assert load_gate_section("usability", path) == {}


@pytest.fixture
def seeded_db(tmp_path):
    db_path = tmp_path / "results.db"
    storage = TestStorage(db_path=db_path)
    for i, passed in enumerate([True, True, True, False], start=1):
        started = f"2026-06-{i:02d}T10:00:00"
        storage.save_run(
            run_id=f"r{i}",
            test_id="suite-A",
            test_version=1,
            model="m",
            provider="p",
            started_at=started,
        )
        storage.save_question_result(run_id=f"r{i}", question_id="q1", passed=passed, score=1.0)
        storage.complete_run(f"r{i}", started)
    return str(db_path)


class TestBadge:
    def test_pass_rate_badge(self, runner, cli_app, seeded_db):
        result = runner.invoke(cli_app, ["badge", "pass-rate", "--db-path", seeded_db])
        assert result.exit_code == 0
        doc = json.loads(result.stdout)
        assert doc["schemaVersion"] == 1
        assert doc["message"] == "75% pass"
        assert doc["color"] == "yellowgreen"

    def test_pass_rate_no_runs(self, runner, cli_app, tmp_path):
        TestStorage(db_path=tmp_path / "empty.db")
        result = runner.invoke(
            cli_app, ["badge", "pass-rate", "--db-path", str(tmp_path / "empty.db")]
        )
        doc = json.loads(result.stdout)
        assert doc["message"] == "no runs"
        assert doc["color"] == "lightgrey"

    def test_score_badge_from_file(self, runner, cli_app, tmp_path):
        score_file = tmp_path / "score.json"
        score_file.write_text(json.dumps({"score": 91.2, "grade": "A"}))
        result = runner.invoke(cli_app, ["badge", "score", "--from", str(score_file)])
        doc = json.loads(result.stdout)
        assert doc["message"] == "91/100 (A)"
        assert doc["color"] == "brightgreen"

    def test_score_badge_requires_file(self, runner, cli_app):
        result = runner.invoke(cli_app, ["badge", "score"])
        assert result.exit_code == 2

    def test_conformance_badge_failing(self, runner, cli_app, tmp_path):
        checks_file = tmp_path / "checks.json"
        checks_file.write_text(
            json.dumps(
                {
                    "checks": [
                        {"status": "SUCCESS"},
                        {"status": "FAILURE"},
                        {"status": "INFO"},
                    ]
                }
            )
        )
        result = runner.invoke(cli_app, ["badge", "conformance", "--from", str(checks_file)])
        doc = json.loads(result.stdout)
        assert doc["message"] == "1 failing"
        assert doc["color"] == "red"

    def test_conformance_badge_passing(self, runner, cli_app, tmp_path):
        checks_file = tmp_path / "checks.json"
        checks_file.write_text(json.dumps({"checks": [{"status": "SUCCESS"}] * 4}))
        result = runner.invoke(cli_app, ["badge", "conformance", "--from", str(checks_file)])
        doc = json.loads(result.stdout)
        assert doc["message"] == "4 checks passing"
        assert doc["color"] == "brightgreen"

    def test_output_file_and_custom_label(self, runner, cli_app, seeded_db, tmp_path):
        out = tmp_path / "badge.json"
        result = runner.invoke(
            cli_app,
            [
                "badge",
                "pass-rate",
                "--db-path",
                seeded_db,
                "--label",
                "nightly evals",
                "--output",
                str(out),
            ],
        )
        assert result.exit_code == 0
        assert json.loads(out.read_text())["label"] == "nightly evals"

    def test_unknown_type(self, runner, cli_app):
        result = runner.invoke(cli_app, ["badge", "nonsense"])
        assert result.exit_code == 2
