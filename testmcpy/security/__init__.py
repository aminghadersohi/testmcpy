"""Static security scanning for MCP servers.

Inspects tool *metadata* (names, descriptions, input schemas) for
tool-poisoning patterns and compares snapshots for rug-pull changes.
It never executes tools or sends attack payloads — this is supply-chain
scanning of what a server advertises, not penetration testing.
"""

from testmcpy.security.rules import RULES, Rule, severity_exceeds, severity_rank
from testmcpy.security.scanner import Finding, scan_rug_pull, scan_tools

__all__ = [
    "RULES",
    "Rule",
    "Finding",
    "scan_rug_pull",
    "scan_tools",
    "severity_exceeds",
    "severity_rank",
]
