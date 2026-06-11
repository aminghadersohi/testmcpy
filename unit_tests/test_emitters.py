"""Tests for testmcpy.src.emitters (JUnit XML)."""

import xml.etree.ElementTree as ET

from testmcpy.src.emitters import to_junit_xml


def _result(**overrides):
    base = {
        "test_name": "t1",
        "passed": True,
        "score": 1.0,
        "duration": 1.5,
        "reason": None,
        "error": None,
        "evaluations": [],
        "cost": 0.0012,
        "token_usage": {"total": 345},
    }
    base.update(overrides)
    return base


def test_passing_suite_structure():
    xml = to_junit_xml([_result(), _result(test_name="t2")], suite_name="my_suite")
    root = ET.fromstring(xml)
    assert root.tag == "testsuite"
    assert root.get("name") == "my_suite"
    assert root.get("tests") == "2"
    assert root.get("failures") == "0"
    assert root.get("errors") == "0"
    cases = root.findall("testcase")
    assert [c.get("name") for c in cases] == ["t1", "t2"]
    assert all(c.find("failure") is None for c in cases)


def test_failure_includes_evaluator_reasons():
    failing = _result(
        test_name="bad",
        passed=False,
        score=0.0,
        reason="evaluators failed",
        evaluations=[
            {"name": "was_mcp_tool_called", "passed": False, "reason": "tool not called"},
            {"name": "final_answer_contains", "passed": True, "reason": "ok"},
        ],
    )
    root = ET.fromstring(to_junit_xml([failing]))
    assert root.get("failures") == "1"
    failure = root.find("testcase/failure")
    assert failure is not None
    assert failure.get("message") == "evaluators failed"
    assert "was_mcp_tool_called: tool not called" in failure.text
    assert "final_answer_contains" not in failure.text


def test_error_counted_separately_from_failure():
    errored = _result(test_name="boom", passed=False, error="connection refused")
    root = ET.fromstring(to_junit_xml([errored]))
    assert root.get("failures") == "0"
    assert root.get("errors") == "1"
    error = root.find("testcase/error")
    assert error is not None
    assert "connection refused" in error.get("message")


def test_metrics_in_system_out_and_suite_properties():
    root = ET.fromstring(to_junit_xml([_result()]))
    out = root.find("testcase/system-out").text
    assert "score: 1.00" in out
    assert "cost_usd: 0.001200" in out
    assert "tokens: 345" in out
    prop = root.find("properties/property[@name='total_cost_usd']")
    assert prop is not None
    assert prop.get("value") == "0.001200"


def test_special_characters_are_escaped():
    nasty = _result(
        test_name='quote " <tag> & amp',
        passed=False,
        reason='said "<hello>" & left',
    )
    xml = to_junit_xml([nasty])
    root = ET.fromstring(xml)  # would raise if not well-formed
    assert root.find("testcase").get("name") == 'quote " <tag> & amp'


def test_handles_missing_optional_fields():
    minimal = {"test_name": "bare", "passed": False}
    root = ET.fromstring(to_junit_xml([minimal]))
    case = root.find("testcase")
    assert case.get("time") == "0.000"
    assert case.find("failure").get("message") == "Test failed"
