"""CI gate configuration for pass/fail thresholds."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class CIGateConfig:
    min_pass_rate: float = 80.0  # Minimum overall pass rate
    max_failures: int | None = None  # Max allowed failures (None = no limit)
    required_tests: list[str] = field(default_factory=list)  # Tests that MUST pass
    block_on_regression: bool = True  # Fail if regression detected vs baseline

    def evaluate(self, results: list[dict], regressions: list[dict] | None = None) -> dict:
        """Evaluate results against gate config.

        Args:
            results: List of test result dicts with "passed" and "test_name" keys.
            regressions: Optional list of regression dicts (from BaselineStore.compare).

        Returns:
            Dict with passed, pass_rate, failures, total, passed_count.
        """
        total = len(results)
        passed = sum(1 for r in results if r.get("passed"))
        pass_rate = (passed / total * 100) if total > 0 else 0

        failures = []
        if pass_rate < self.min_pass_rate:
            failures.append(f"Pass rate {pass_rate:.1f}% below minimum {self.min_pass_rate}%")
        if self.max_failures is not None and (total - passed) > self.max_failures:
            failures.append(f"{total - passed} failures exceeds max {self.max_failures}")
        if self.required_tests:
            result_map = {r.get("test_name"): r.get("passed") for r in results}
            missing = [t for t in self.required_tests if not result_map.get(t)]
            if missing:
                failures.append(f"Required tests failed: {missing}")
        if self.block_on_regression and regressions:
            failures.append(
                f"{len(regressions)} regression(s) detected: "
                + ", ".join(r.get("test_name", "?") for r in regressions[:5])
            )

        return {
            "passed": len(failures) == 0,
            "pass_rate": pass_rate,
            "failures": failures,
            "total": total,
            "passed_count": passed,
        }


def _load_yaml(path: str) -> dict:
    config_path = Path(path)
    if not config_path.exists():
        return {}
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def load_gate_config(path: str = ".testmcpy-gate.yaml") -> CIGateConfig:
    """Load the evals gate config from YAML.

    Supports both layouts:
      - flat (legacy): min_pass_rate / max_failures / ... at top level
      - sectioned (unified gate): the same keys under an `evals:` block,
        alongside `conformance:` / `usability:` / `security:` sections
        consumed by their respective commands via load_gate_section().
    """
    data = _load_yaml(path)
    evals = data.get("evals") if isinstance(data.get("evals"), dict) else data

    return CIGateConfig(
        min_pass_rate=float(evals.get("min_pass_rate", 80.0)),
        max_failures=evals.get("max_failures"),
        required_tests=evals.get("required_tests") or [],
        block_on_regression=evals.get("block_on_regression", True),
    )


def load_gate_section(section: str, path: str = ".testmcpy-gate.yaml") -> dict:
    """Read one section of the unified gate file.

    Sections: `conformance` (required, fail_on_warning), `usability`
    (min_score), `security` (max_severity). Returns {} when the file or
    section is absent so callers fall back to their CLI defaults.
    """
    data = _load_yaml(path)
    value = data.get(section)
    return value if isinstance(value, dict) else {}
