"""Result emitters for CI systems.

Converts test results (the ``TestResult.to_dict()`` shape) into formats
CI providers ingest natively. JUnit XML is consumed by GitHub Actions
test summaries, Jenkins, GitLab, CircleCI, and Buildkite. SARIF is
consumed by GitHub code scanning and most SAST dashboards.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

# SARIF level for each testmcpy severity (SARIF has no "critical").
_SARIF_LEVELS = {"low": "note", "medium": "warning", "high": "error", "critical": "error"}


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


def to_sarif(findings: list[Any], tool_version: str) -> str:
    """Render `testmcpy scan` findings as a SARIF 2.1.0 document.

    Args:
        findings: :class:`testmcpy.security.scanner.Finding` objects (or
            dicts with the same keys: rule_id, severity, tool_name,
            message, evidence).
        tool_version: testmcpy version for ``tool.driver.version``.

    Returns:
        SARIF JSON as a string. Findings reference logical locations
        (the tool name) rather than physical files, because the scan
        target is a live MCP server, not source code.
    """
    from testmcpy.security.rules import RULES

    finding_dicts = [f if isinstance(f, dict) else f.to_dict() for f in findings]

    rule_ids = sorted({f["rule_id"] for f in finding_dicts})
    rules = []
    for rule_id in rule_ids:
        rule = RULES[rule_id]
        rules.append(
            {
                "id": rule.id,
                "name": rule.name,
                "shortDescription": {"text": rule.short_description},
                "fullDescription": {"text": rule.full_description},
                "helpUri": rule.help_uri,
                "defaultConfiguration": {"level": _SARIF_LEVELS[rule.severity]},
            }
        )

    results = []
    for f in finding_dicts:
        results.append(
            {
                "ruleId": f["rule_id"],
                "level": _SARIF_LEVELS[f["severity"]],
                "message": {"text": f"{f['message']}: {f['evidence']}"},
                "locations": [
                    {
                        "logicalLocations": [
                            {"name": f["tool_name"], "kind": "function"},
                        ]
                    }
                ],
                "properties": {"severity": f["severity"], "toolName": f["tool_name"]},
            }
        )

    document = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "testmcpy-scan",
                        "version": tool_version,
                        "informationUri": "https://github.com/preset-io/testmcpy",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(document, indent=2)
