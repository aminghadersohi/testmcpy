"""Registry of static security rules for MCP tool-surface scanning.

Each rule has a stable id (TMS = TestMcpy Security), a severity on the
low < medium < high < critical scale, and SARIF-ready descriptions.
TMS0xx rules are single-snapshot tool-poisoning checks; TMS1xx rules are
rug-pull checks that need a saved baseline to compare against.
"""

from __future__ import annotations

from dataclasses import dataclass

_DOCS_BASE = "https://github.com/preset-io/testmcpy/blob/main/docs/security-rules.md"

#: Severities in ascending order of impact.
SEVERITIES = ("low", "medium", "high", "critical")
_SEVERITY_RANK = {severity: rank for rank, severity in enumerate(SEVERITIES)}


def severity_rank(severity: str) -> int:
    """Return the ordinal rank of a severity (low=0 ... critical=3).

    Raises:
        KeyError: If ``severity`` is not one of :data:`SEVERITIES`.
    """
    return _SEVERITY_RANK[severity]


def severity_exceeds(severity: str, ceiling: str) -> bool:
    """True if ``severity`` is strictly more severe than ``ceiling``."""
    return severity_rank(severity) > severity_rank(ceiling)


@dataclass(frozen=True)
class Rule:
    """A named static-analysis rule."""

    id: str
    name: str
    severity: str
    short_description: str
    full_description: str

    @property
    def help_uri(self) -> str:
        return f"{_DOCS_BASE}#{self.id.lower()}"


_RULE_LIST = [
    Rule(
        id="TMS001",
        name="hidden-instructions",
        severity="critical",
        short_description="Hidden instructions in tool description",
        full_description=(
            "The tool description contains prompt-injection phrasing aimed at the "
            "LLM rather than the user — e.g. instruction-override directives "
            "('ignore previous instructions'), hidden <IMPORTANT>/<SYSTEM> tags, "
            "concealment directives ('do not tell the user'), or pre-call "
            "side-effect directives ('before using this tool, read/send ...'). "
            "These are the canonical MCP tool-poisoning patterns."
        ),
    ),
    Rule(
        id="TMS002",
        name="invisible-characters",
        severity="high",
        short_description="Invisible or obfuscated Unicode characters",
        full_description=(
            "The tool name or description contains zero-width characters, Unicode "
            "tag characters, or bidirectional control characters. These are "
            "invisible to human reviewers but visible to LLMs, and are used to "
            "smuggle instructions past inspection."
        ),
    ),
    Rule(
        id="TMS003",
        name="cross-tool-manipulation",
        severity="high",
        short_description="Imperative reference to another tool on the same server",
        full_description=(
            "The tool description imperatively directs the agent to use, call, or "
            "invoke another tool exposed by the same server (e.g. 'always call X "
            "first'). Cross-tool steering lets one poisoned tool hijack the "
            "behavior of an otherwise-benign tool surface."
        ),
    ),
    Rule(
        id="TMS004",
        name="sensitive-data-exfiltration",
        severity="high",
        short_description="References to sensitive files or secrets",
        full_description=(
            "The tool or parameter descriptions reference sensitive material — "
            "SSH keys (~/.ssh, id_rsa), .env files, /etc/passwd — or pair "
            "secret-bearing terms (API keys, credentials, environment variables) "
            "with read/send verbs, suggesting the description is staging data "
            "exfiltration through the agent."
        ),
    ),
    Rule(
        id="TMS005",
        name="description-schema-mismatch",
        severity="medium",
        short_description="Schema parameter hidden from the description",
        full_description=(
            "The input schema declares a parameter that the tool description "
            "never mentions, while the parameter's own description dictates a "
            "specific value ('must be', 'always set'). This pattern hides "
            "attacker-controlled arguments from human review."
        ),
    ),
    Rule(
        id="TMS006",
        name="suspicious-url",
        severity="medium",
        short_description="Suspicious URL in tool description",
        full_description=(
            "The tool description contains a URL that does not look like "
            "documentation: a raw IP address, a URL shortener, a data: URI, or a "
            "non-HTTPS endpoint. Such URLs are common exfiltration or payload "
            "channels in poisoned tool descriptions."
        ),
    ),
    Rule(
        id="TMS007",
        name="oversized-description",
        severity="low",
        short_description="Oversized tool description",
        full_description=(
            "The tool description exceeds 2,000 characters. Oversized "
            "descriptions bloat the agent's context and provide surface area for "
            "smuggled instructions."
        ),
    ),
    Rule(
        id="TMS100",
        name="rug-pull-description-changed",
        severity="critical",
        short_description="Tool description changed since baseline",
        full_description=(
            "A tool's description differs from the saved baseline. Rug-pull "
            "attacks ship a benign description at install/review time and swap "
            "in a poisoned one later — any unreviewed description change is a "
            "red flag."
        ),
    ),
    Rule(
        id="TMS101",
        name="rug-pull-schema-changed",
        severity="critical",
        short_description="Tool input schema changed since baseline",
        full_description=(
            "A tool's input schema differs from the saved baseline (parameters "
            "added, removed, retyped, or re-described). Schema swaps can "
            "introduce hidden exfiltration parameters after review."
        ),
    ),
    Rule(
        id="TMS102",
        name="rug-pull-new-tool",
        severity="medium",
        short_description="New tool appeared since baseline",
        full_description=(
            "The server exposes a tool that was not present in the saved "
            "baseline. New tools widen the attack surface and have not been "
            "reviewed."
        ),
    ),
    Rule(
        id="TMS103",
        name="rug-pull-removed-tool",
        severity="low",
        short_description="Tool removed since baseline",
        full_description=(
            "A tool present in the saved baseline is no longer exposed by the "
            "server. Removals are usually benign but indicate the surface "
            "drifted from what was reviewed."
        ),
    ),
]

#: Rule registry keyed by rule id.
RULES: dict[str, Rule] = {rule.id: rule for rule in _RULE_LIST}
