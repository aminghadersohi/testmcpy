"""Static scanner for MCP tool-poisoning and rug-pull patterns.

Operates purely on tool metadata dicts (``{"name", "description",
"input_schema"}`` — the shape ``testmcpy score`` fetches). Nothing here
connects to a server or executes a tool.

Rug-pull detection reuses :func:`testmcpy.src.schema_diff.diff_tool_schemas`,
which already compares two tool snapshots (descriptions + parameters) and
accepts both ``input_schema`` and ``inputSchema`` keys.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from testmcpy.security.rules import RULES
from testmcpy.src.schema_diff import diff_tool_schemas

#: Max length of the ``evidence`` snippet attached to a finding.
EVIDENCE_MAX_CHARS = 200

#: TMS007 threshold — descriptions longer than this are flagged.
MAX_DESCRIPTION_CHARS = 2_000


@dataclass
class Finding:
    """A single security finding against one tool."""

    rule_id: str
    severity: str
    tool_name: str
    message: str
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "tool_name": self.tool_name,
            "message": self.message,
            "evidence": self.evidence,
        }


def _truncate(text: str, limit: int = EVIDENCE_MAX_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _finding(rule_id: str, tool_name: str, message: str, evidence: str) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=RULES[rule_id].severity,
        tool_name=tool_name,
        message=message,
        evidence=_truncate(evidence),
    )


# ---------------------------------------------------------------------------
# TMS001 — hidden instructions
# ---------------------------------------------------------------------------
# Each pattern targets a documented tool-poisoning idiom. Broad phrases from
# the research literature ("instead of", "you must always") are anchored to
# agent-directed context to keep false positives low — e.g. bare "instead of"
# is normal English, but "instead of telling the user" is a bypass directive.
_HIDDEN_INSTRUCTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"ignore\s+(?:all\s+|any\s+)?(?:previous|prior|above)\s+instructions", re.IGNORECASE
        ),
        "instruction-override directive",
    ),
    (re.compile(r"<\s*important\s*>", re.IGNORECASE), "hidden <IMPORTANT> tag"),
    (re.compile(r"<\s*system\s*>", re.IGNORECASE), "hidden <SYSTEM> tag"),
    (
        re.compile(
            r"do\s+not\s+(?:tell|inform|mention|reveal)[^.!?]{0,80}?\b(?:user|human)",
            re.IGNORECASE,
        ),
        "concealment directive (hide behavior from the user)",
    ),
    (
        re.compile(
            r"before\s+(?:using|calling)\s+this\s+tool[^.!?]{0,120}?\b(?:read|fetch|send)",
            re.IGNORECASE,
        ),
        "pre-call side-effect directive",
    ),
    (
        re.compile(
            r"instead\s+of\s+(?:asking|telling|informing|notifying|showing)\s+the\s+"
            r"(?:user|human)",
            re.IGNORECASE,
        ),
        "user-bypass directive",
    ),
    (re.compile(r"\byou\s+must\s+always\b", re.IGNORECASE), "coercive always-directive"),
]


def _check_hidden_instructions(tool: dict[str, Any]) -> list[Finding]:
    description = tool.get("description") or ""
    findings = []
    for pattern, label in _HIDDEN_INSTRUCTION_PATTERNS:
        match = pattern.search(description)
        if match:
            findings.append(
                _finding(
                    "TMS001",
                    tool["name"],
                    f"Description contains a {label}",
                    match.group(0),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# TMS002 — invisible / obfuscated characters
# ---------------------------------------------------------------------------
_INVISIBLE_RANGES: list[tuple[int, int, str]] = [
    (0x200B, 0x200F, "zero-width/invisible-format character"),
    (0xFEFF, 0xFEFF, "zero-width no-break space (BOM)"),
    (0x202A, 0x202E, "bidirectional control character"),
    (0x2066, 0x2069, "bidirectional isolate character"),
    (0xE0000, 0xE007F, "Unicode tag character"),
]


def _invisible_chars(text: str) -> list[tuple[str, str]]:
    """Return (codepoint, label) for each invisible character occurrence."""
    hits = []
    for char in text:
        code = ord(char)
        for low, high, label in _INVISIBLE_RANGES:
            if low <= code <= high:
                hits.append((f"U+{code:04X}", label))
                break
    return hits


def _check_invisible_characters(tool: dict[str, Any]) -> list[Finding]:
    findings = []
    for field, text in (("name", tool["name"]), ("description", tool.get("description") or "")):
        hits = _invisible_chars(text)
        if hits:
            unique = sorted({f"{code} ({label})" for code, label in hits})
            findings.append(
                _finding(
                    "TMS002",
                    tool["name"],
                    f"Tool {field} contains {len(hits)} invisible/obfuscated character(s)",
                    "; ".join(unique),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# TMS003 — cross-tool manipulation
# ---------------------------------------------------------------------------
def _check_cross_tool_manipulation(
    tool: dict[str, Any], other_tool_names: set[str]
) -> list[Finding]:
    description = tool.get("description") or ""
    findings = []
    for other in sorted(other_tool_names):
        # Imperative steering only: "use X first", "call X", "always invoke X
        # before". A mere mention of another tool is not flagged.
        pattern = re.compile(
            rf"\b(?:always\s+)?(?:use|call|invoke)\s+(?:the\s+)?[`'\"]?{re.escape(other)}"
            rf"[`'\"]?(?![\w])",
            re.IGNORECASE,
        )
        match = pattern.search(description)
        if match:
            findings.append(
                _finding(
                    "TMS003",
                    tool["name"],
                    f"Description imperatively directs the agent to another tool ('{other}')",
                    match.group(0),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# TMS004 — sensitive-data exfiltration hints
# ---------------------------------------------------------------------------
# Path-like indicators are suspicious on their own — legitimate tool docs
# rarely reference SSH keys or /etc/passwd.
_SENSITIVE_PATH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"~?/?\.ssh\b", re.IGNORECASE), "SSH key directory (~/.ssh)"),
    (re.compile(r"\bid_(?:rsa|ed25519|ecdsa|dsa)\b", re.IGNORECASE), "SSH private key file"),
    (re.compile(r"(?<![\w.])\.env\b", re.IGNORECASE), ".env file"),
    (re.compile(r"/etc/passwd\b"), "/etc/passwd"),
]
# Term-based indicators ("api key", "credentials", "environment variables")
# appear in legitimate auth docs, so they only fire when the same text also
# contains a read/send-style verb suggesting collection or exfiltration.
_SENSITIVE_TERM_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bapi[_ ]?keys?\b", re.IGNORECASE), "API key"),
    (re.compile(r"\bcredentials?\b", re.IGNORECASE), "credentials"),
    (re.compile(r"\benvironment\s+variables?\b", re.IGNORECASE), "environment variables"),
]
_EXFIL_VERB_PATTERN = re.compile(
    r"\b(?:read|send|upload|post|transmit|forward|collect|include|attach|exfiltrate)\b",
    re.IGNORECASE,
)


def _param_descriptions(tool: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (param_name, param_description) pairs from the input schema."""
    schema = tool.get("input_schema") or tool.get("inputSchema") or {}
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        return []
    return [
        (name, prop.get("description", ""))
        for name, prop in properties.items()
        if isinstance(prop, dict)
    ]


def _check_sensitive_data(tool: dict[str, Any]) -> list[Finding]:
    texts = [("description", tool.get("description") or "")]
    texts += [(f"parameter '{name}' description", desc) for name, desc in _param_descriptions(tool)]

    findings = []
    for where, text in texts:
        if not text:
            continue
        for pattern, label in _SENSITIVE_PATH_PATTERNS:
            match = pattern.search(text)
            if match:
                findings.append(
                    _finding(
                        "TMS004",
                        tool["name"],
                        f"{where.capitalize()} references {label}",
                        match.group(0),
                    )
                )
        if _EXFIL_VERB_PATTERN.search(text):
            for pattern, label in _SENSITIVE_TERM_PATTERNS:
                match = pattern.search(text)
                if match:
                    findings.append(
                        _finding(
                            "TMS004",
                            tool["name"],
                            f"{where.capitalize()} pairs '{label}' with a read/send verb",
                            match.group(0),
                        )
                    )
    return findings


# ---------------------------------------------------------------------------
# TMS005 — description/schema mismatch
# ---------------------------------------------------------------------------
_IMPERATIVE_VALUE_PATTERN = re.compile(
    r"\b(?:must\s+(?:always\s+)?be|always\s+set|must\s+be\s+set\s+to|set\s+this\s+to)\b",
    re.IGNORECASE,
)


def _check_schema_mismatch(tool: dict[str, Any]) -> list[Finding]:
    description = (tool.get("description") or "").lower()
    findings = []
    for name, param_desc in _param_descriptions(tool):
        if name.lower() in description:
            continue  # parameter is documented — not hidden
        match = _IMPERATIVE_VALUE_PATTERN.search(param_desc)
        if match:
            findings.append(
                _finding(
                    "TMS005",
                    tool["name"],
                    f"Parameter '{name}' is absent from the description but its own "
                    f"description dictates a value",
                    param_desc,
                )
            )
    return findings


# ---------------------------------------------------------------------------
# TMS006 — suspicious URLs
# ---------------------------------------------------------------------------
_URL_PATTERN = re.compile(r"\b(?:https?|data):[^\s)\"'<>\]]+", re.IGNORECASE)
_RAW_IP_HOST_PATTERN = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_URL_SHORTENER_HOSTS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "ow.ly", "rb.gy"}


def _suspicious_url_reason(url: str) -> str | None:
    lowered = url.lower()
    if lowered.startswith("data:"):
        return "data: URI"
    host = re.sub(r"^https?://", "", lowered, count=1).split("/")[0].split(":")[0]
    if _RAW_IP_HOST_PATTERN.match(host):
        return "raw IP address"
    if host in _URL_SHORTENER_HOSTS:
        return "URL shortener"
    if lowered.startswith("http://") and host not in ("localhost", "127.0.0.1"):
        return "non-HTTPS URL"
    return None


def _check_suspicious_urls(tool: dict[str, Any]) -> list[Finding]:
    description = tool.get("description") or ""
    findings = []
    for match in _URL_PATTERN.finditer(description):
        url = match.group(0).rstrip(".,;")
        reason = _suspicious_url_reason(url)
        if reason:
            findings.append(
                _finding(
                    "TMS006",
                    tool["name"],
                    f"Description contains a suspicious URL ({reason})",
                    url,
                )
            )
    return findings


# ---------------------------------------------------------------------------
# TMS007 — oversized description
# ---------------------------------------------------------------------------
def _check_oversized_description(tool: dict[str, Any]) -> list[Finding]:
    description = tool.get("description") or ""
    if len(description) <= MAX_DESCRIPTION_CHARS:
        return []
    return [
        _finding(
            "TMS007",
            tool["name"],
            f"Description is {len(description):,} chars "
            f"(> {MAX_DESCRIPTION_CHARS:,} char threshold)",
            description[:EVIDENCE_MAX_CHARS],
        )
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def scan_tools(tools: list[dict[str, Any]]) -> list[Finding]:
    """Run all single-snapshot (TMS0xx) rules over a tool list.

    Args:
        tools: Tool dicts with ``name``, ``description``, ``input_schema``.

    Returns:
        Findings ordered by tool, then rule.
    """
    all_names = {t["name"] for t in tools}
    findings: list[Finding] = []
    for tool in tools:
        other_names = all_names - {tool["name"]}
        findings.extend(_check_hidden_instructions(tool))
        findings.extend(_check_invisible_characters(tool))
        findings.extend(_check_cross_tool_manipulation(tool, other_names))
        findings.extend(_check_sensitive_data(tool))
        findings.extend(_check_schema_mismatch(tool))
        findings.extend(_check_suspicious_urls(tool))
        findings.extend(_check_oversized_description(tool))
    return findings


def scan_rug_pull(
    baseline_tools: list[dict[str, Any]], current_tools: list[dict[str, Any]]
) -> list[Finding]:
    """Compare a saved baseline against the current tool list (TMS1xx rules).

    Args:
        baseline_tools: The reviewed/trusted snapshot.
        current_tools: What the server advertises now.

    Returns:
        Findings for changed descriptions (TMS100), changed schemas
        (TMS101), new tools (TMS102), and removed tools (TMS103).
    """
    diff = diff_tool_schemas(baseline_tools, current_tools)
    findings: list[Finding] = []

    for change in diff.changed:
        if change.description_changed:
            findings.append(
                _finding(
                    "TMS100",
                    change.tool_name,
                    "Tool description changed since baseline (possible rug pull)",
                    f"was: {change.old_description!r} -> now: {change.new_description!r}",
                )
            )
        if change.param_changes:
            summary = "; ".join(f"{p.param_name}: {p.change_type}" for p in change.param_changes)
            findings.append(
                _finding(
                    "TMS101",
                    change.tool_name,
                    "Tool input schema changed since baseline (possible rug pull)",
                    summary,
                )
            )

    for change in diff.added:
        findings.append(
            _finding(
                "TMS102",
                change.tool_name,
                "New tool not present in baseline",
                change.tool_name,
            )
        )

    for change in diff.removed:
        findings.append(
            _finding(
                "TMS103",
                change.tool_name,
                "Tool removed since baseline",
                change.tool_name,
            )
        )

    return findings
