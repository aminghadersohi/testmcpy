"""Result emitters for CI systems.

Converts test results (the ``TestResult.to_dict()`` shape) into formats
CI providers ingest natively. JUnit XML is consumed by GitHub Actions
test summaries, Jenkins, GitLab, CircleCI, and Buildkite.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any


def to_junit_xml(results: list[dict[str, Any]], suite_name: str = "testmcpy") -> str:
    """Render test results as a JUnit XML document.

    Args:
        results: List of ``TestResult.to_dict()`` dicts (keys: test_name,
            passed, score, duration, reason, error, evaluations, cost,
            token_usage).
        suite_name: Name for the ``<testsuite>`` element.

    Returns:
        JUnit XML as a string, including the XML declaration.
    """
    failures = sum(1 for r in results if not r.get("passed") and not r.get("error"))
    errors = sum(1 for r in results if r.get("error"))
    total_time = sum(float(r.get("duration") or 0.0) for r in results)
    total_cost = sum(float(r.get("cost") or 0.0) for r in results)

    suite = ET.Element(
        "testsuite",
        name=suite_name,
        tests=str(len(results)),
        failures=str(failures),
        errors=str(errors),
        time=f"{total_time:.3f}",
    )

    properties = ET.SubElement(suite, "properties")
    ET.SubElement(properties, "property", name="total_cost_usd", value=f"{total_cost:.6f}")

    for r in results:
        case = ET.SubElement(
            suite,
            "testcase",
            name=str(r.get("test_name", "unknown")),
            classname=suite_name,
            time=f"{float(r.get('duration') or 0.0):.3f}",
        )

        if r.get("error"):
            error_el = ET.SubElement(case, "error", message=str(r["error"]))
            error_el.text = str(r["error"])
        elif not r.get("passed"):
            failure_el = ET.SubElement(
                case, "failure", message=str(r.get("reason") or "Test failed")
            )
            failed_evals = [
                f"{e.get('name', 'evaluator')}: {e.get('reason', 'failed')}"
                for e in r.get("evaluations") or []
                if not e.get("passed")
            ]
            failure_el.text = "\n".join(failed_evals) or str(r.get("reason") or "Test failed")

        metrics = [f"score: {float(r.get('score') or 0.0):.2f}"]
        if r.get("cost"):
            metrics.append(f"cost_usd: {float(r['cost']):.6f}")
        token_usage = r.get("token_usage") or {}
        if token_usage.get("total"):
            metrics.append(f"tokens: {token_usage['total']}")
        system_out = ET.SubElement(case, "system-out")
        system_out.text = " | ".join(metrics)

    tree = ET.ElementTree(suite)
    ET.indent(tree)
    return ET.tostring(suite, encoding="unicode", xml_declaration=True)
