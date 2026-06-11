"""LLM-usability scoring for MCP tool surfaces.

Grades how usable an MCP server's tool surface is *for LLM agents* —
not for humans. The score is fully deterministic (no LLM calls): it is
computed from the tool names, descriptions, and JSON schemas a server
returns from ``tools/list``.

Rubric (v1, deterministic tier)
===============================

==================  ======  ===========================================================
Dimension           Weight  What it measures
==================  ======  ===========================================================
descriptions        0.25    Every tool has a description; ideal length 20-500 chars
                            (too short = unexplained, too long = token bloat); the
                            description says what the tool does rather than merely
                            restating its name.
schemas             0.25    ``input_schema`` exists and is an object schema; every
                            property has a type and a description; ``required`` is
                            declared; no ``additionalProperties: true`` grab-bags.
naming              0.15    Names are snake_case or kebab-case, consistently across
                            the server; verb_noun style (start with an action verb);
                            no cryptic abbreviations; no collisions after case
                            normalization.
economy             0.20    Tool-count economy (<= 20 tools full credit, 0 at >= 100)
                            and token cost of the serialized tool surface
                            (<= 5,000 estimated tokens full credit, 0 at >= 50,000).
parameter_clarity   0.15    Fraction of parameters server-wide with both a description
                            and a sensible type; tools with > 10 required parameters
                            are penalized as agent-hostile.
==================  ======  ===========================================================

Composite score = sum(dimension_score * weight) * 100, graded
A >= 90, B >= 80, C >= 70, D >= 60, F < 60.

An empty tool list scores 0.0 / F with an explicit "server exposes no
tools" finding on every dimension (a server with nothing for an agent
to call has no usable surface).

Extensibility: the result schema keys dimensions by name, so an
optional LLM-judge tier can later be added as another dimension (e.g.
``llm_judge``) with its own weight — existing consumers keep working as
long as weights are renormalized.

Input: a list of tool dicts shaped like what
:class:`testmcpy.src.mcp_client.MCPTool` exposes::

    {"name": str, "description": str | None, "input_schema": dict | None}
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Rubric constants — every heuristic threshold lives here so the rubric is
# explainable and tunable in one place.
# ---------------------------------------------------------------------------

# Dimension weights (must sum to 1.0).
DIMENSION_WEIGHTS: dict[str, float] = {
    "descriptions": 0.25,
    "schemas": 0.25,
    "naming": 0.15,
    "economy": 0.20,
    "parameter_clarity": 0.15,
}

# Grade boundaries on the 0-100 composite score.
GRADE_BOUNDARIES: list[tuple[float, str]] = [
    (90.0, "A"),
    (80.0, "B"),
    (70.0, "C"),
    (60.0, "D"),
]
FAILING_GRADE = "F"

# --- descriptions ----------------------------------------------------------
DESC_MIN_LEN = 20  # below this a description is too short to explain anything
DESC_IDEAL_MAX_LEN = 500  # above this we start charging for token bloat
DESC_BLOAT_LEN = 2000  # above this the description is serious token bloat
DESC_MISSING_SCORE = 0.0  # missing/empty descriptions are penalized heavily
DESC_TOO_SHORT_SCORE = 0.3  # present but under DESC_MIN_LEN
DESC_LONG_SCORE = 0.8  # between ideal max and bloat threshold
DESC_BLOATED_SCORE = 0.5  # past the bloat threshold
DESC_NAME_RESTATED_SCORE = 0.3  # description merely restates the tool name

# --- schemas ---------------------------------------------------------------
SCHEMA_NOT_OBJECT_PENALTY = 0.3  # schema exists but `type` is not "object"
SCHEMA_UNTYPED_PROPS_PENALTY = 0.35  # max penalty when no property has a type
SCHEMA_UNDESCRIBED_PROPS_PENALTY = 0.35  # max penalty when no property described
SCHEMA_NO_REQUIRED_PENALTY = 0.1  # properties exist but `required` undeclared
SCHEMA_ADDITIONAL_PROPS_PENALTY = 0.1  # explicit additionalProperties: true
# Property is "typed" if it has any of these keys (type, enum, or composition).
TYPED_PROPERTY_KEYS = ("type", "enum", "anyOf", "oneOf", "allOf", "$ref")

# --- naming ----------------------------------------------------------------
# Extensible list of action verbs a well-named tool starts with (verb_noun).
NAME_ACTION_VERBS = frozenset(
    {
        "add",
        "apply",
        "build",
        "cancel",
        "check",
        "clear",
        "clone",
        "close",
        "compare",
        "compute",
        "convert",
        "copy",
        "count",
        "create",
        "delete",
        "describe",
        "download",
        "execute",
        "export",
        "fetch",
        "filter",
        "find",
        "generate",
        "get",
        "import",
        "insert",
        "inspect",
        "install",
        "list",
        "load",
        "lookup",
        "merge",
        "move",
        "open",
        "parse",
        "patch",
        "post",
        "publish",
        "pull",
        "push",
        "put",
        "query",
        "read",
        "refresh",
        "remove",
        "rename",
        "render",
        "reset",
        "resolve",
        "restart",
        "retrieve",
        "run",
        "save",
        "scan",
        "search",
        "send",
        "set",
        "show",
        "start",
        "stop",
        "submit",
        "sync",
        "test",
        "trigger",
        "update",
        "upload",
        "validate",
        "verify",
        "write",
    }
)
NAME_MIN_LEN = 4  # full names shorter than this are cryptic abbreviations
NAME_CRYPTIC_PENALTY = 0.5  # e.g. a tool literally named `q`
NAME_NO_VERB_PENALTY = 0.3  # does not start with an action verb
NAME_BAD_CASE_PENALTY = 0.3  # not snake_case or kebab-case (e.g. camelCase)
NAME_INCONSISTENT_CASE_FACTOR = 0.85  # server mixes naming styles
NAME_COLLISION_PENALTY = 0.2  # per colliding name group after normalization
# Valid snake_case or kebab-case identifier (single separator style).
_SNAKE_RE = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*$")
_KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# --- economy ---------------------------------------------------------------
TOOL_COUNT_FULL_CREDIT = 20  # <= this many tools: full count credit
TOOL_COUNT_ZERO_CREDIT = 100  # >= this many tools: zero count credit
CHARS_PER_TOKEN = 4  # rough token estimate: len(serialized chars) / 4
TOKENS_FULL_CREDIT = 5_000  # <= this many estimated tokens: full credit
TOKENS_ZERO_CREDIT = 50_000  # >= this many estimated tokens: zero credit
ECONOMY_COUNT_WEIGHT = 0.5  # tool-count share of the economy dimension
ECONOMY_TOKEN_WEIGHT = 0.5  # token-cost share of the economy dimension

# --- parameter_clarity -----------------------------------------------------
MAX_REQUIRED_PARAMS = 10  # > this many required params is agent-hostile
PARAM_CLARITY_WEIGHT = 0.85  # share for described+typed parameter fraction
PARAM_HOSTILITY_WEIGHT = 0.15  # share for not exceeding MAX_REQUIRED_PARAMS


@dataclass
class DimensionResult:
    """Score for a single rubric dimension."""

    score: float  # 0.0 - 1.0
    weight: float
    findings: list[str] = field(default_factory=list)


@dataclass
class UsabilityScore:
    """Full LLM-usability score for an MCP server's tool surface."""

    score: float  # 0 - 100
    grade: str  # A-F
    dimensions: dict[str, DimensionResult]
    tool_count: int
    estimated_tokens: int
    per_tool: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "grade": self.grade,
            "dimensions": {
                name: {"score": d.score, "weight": d.weight, "findings": d.findings}
                for name, d in self.dimensions.items()
            },
            "tool_count": self.tool_count,
            "estimated_tokens": self.estimated_tokens,
            "per_tool": self.per_tool,
        }


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _grade_for(score: float) -> str:
    for boundary, grade in GRADE_BOUNDARIES:
        if score >= boundary:
            return grade
    return FAILING_GRADE


# ---------------------------------------------------------------------------
# Per-tool scorers (each returns score 0-1 plus specific, actionable issues)
# ---------------------------------------------------------------------------


def _score_description(name: str, description: str | None) -> tuple[float, list[str]]:
    desc = (description or "").strip()
    if not desc:
        return DESC_MISSING_SCORE, [f"tool `{name}` has no description"]

    issues: list[str] = []
    # A description that just restates the tool name explains nothing.
    normalized_desc = re.sub(r"[\s_\-.]+", " ", desc.lower()).strip()
    normalized_name = re.sub(r"[\s_\-.]+", " ", name.lower()).strip()
    if normalized_desc == normalized_name:
        issues.append(f"description of `{name}` merely restates the tool name")
        return DESC_NAME_RESTATED_SCORE, issues

    if len(desc) < DESC_MIN_LEN:
        issues.append(
            f"description of `{name}` is too short ({len(desc)} chars, "
            f"minimum useful length is {DESC_MIN_LEN})"
        )
        return DESC_TOO_SHORT_SCORE, issues
    if len(desc) > DESC_BLOAT_LEN:
        issues.append(
            f"description of `{name}` is token bloat ({len(desc)} chars, "
            f"aim for <= {DESC_IDEAL_MAX_LEN})"
        )
        return DESC_BLOATED_SCORE, issues
    if len(desc) > DESC_IDEAL_MAX_LEN:
        issues.append(
            f"description of `{name}` is long ({len(desc)} chars, aim for <= {DESC_IDEAL_MAX_LEN})"
        )
        return DESC_LONG_SCORE, issues
    return 1.0, issues


def _score_schema(name: str, schema: dict[str, Any] | None) -> tuple[float, list[str]]:
    if not schema or not isinstance(schema, dict):
        return 0.0, [f"tool `{name}` has no input schema"]

    issues: list[str] = []
    score = 1.0

    if schema.get("type") != "object":
        score -= SCHEMA_NOT_OBJECT_PENALTY
        issues.append(f"input schema of `{name}` is not declared as an object schema")

    props = schema.get("properties") or {}
    if isinstance(props, dict) and props:
        untyped = [p for p, s in props.items() if not _is_typed(s)]
        undescribed = [
            p
            for p, s in props.items()
            if not (isinstance(s, dict) and str(s.get("description") or "").strip())
        ]
        score -= SCHEMA_UNTYPED_PROPS_PENALTY * (len(untyped) / len(props))
        score -= SCHEMA_UNDESCRIBED_PROPS_PENALTY * (len(undescribed) / len(props))
        for p in untyped:
            issues.append(f"parameter `{p}` of `{name}` is untyped")
        for p in undescribed:
            issues.append(f"parameter `{p}` of `{name}` has no description")
        if "required" not in schema:
            score -= SCHEMA_NO_REQUIRED_PENALTY
            issues.append(f"`{name}` does not declare which parameters are required")

    if schema.get("additionalProperties") is True:
        score -= SCHEMA_ADDITIONAL_PROPS_PENALTY
        issues.append(f"`{name}` allows untyped additionalProperties (schema grab-bag)")

    return _clamp(score), issues


def _is_typed(prop_schema: Any) -> bool:
    return isinstance(prop_schema, dict) and any(k in prop_schema for k in TYPED_PROPERTY_KEYS)


def _name_case_style(name: str) -> str:
    """Classify a tool name's case style.

    Returns "snake", "kebab", "plain" (single lowercase word — compatible
    with either style), or "other" (camelCase, UPPER, mixed separators...).
    """
    if _SNAKE_RE.match(name):
        return "snake" if "_" in name else "plain"
    if _KEBAB_RE.match(name):
        return "kebab"
    return "other"


def _score_name(name: str) -> tuple[float, list[str]]:
    issues: list[str] = []
    score = 1.0

    if len(name) < NAME_MIN_LEN:
        score -= NAME_CRYPTIC_PENALTY
        issues.append(f"tool name `{name}` is a cryptic abbreviation (< {NAME_MIN_LEN} chars)")

    style = _name_case_style(name)
    if style == "other":
        score -= NAME_BAD_CASE_PENALTY
        issues.append(f"tool name `{name}` is not snake_case or kebab-case")

    first_word = re.split(r"[_\-]", name.lower(), maxsplit=1)[0]
    if style == "other":
        # For camelCase etc., take the leading lowercase run as the first word.
        match = re.match(r"[a-z]+", name)
        first_word = match.group(0) if match else name.lower()
    if first_word not in NAME_ACTION_VERBS:
        score -= NAME_NO_VERB_PENALTY
        issues.append(
            f"tool name `{name}` does not start with an action verb (e.g. get/list/create)"
        )

    return _clamp(score), issues


def _score_params(name: str, schema: dict[str, Any] | None) -> tuple[float, list[str], int, int]:
    """Per-tool parameter clarity.

    Returns (score, issues, clear_param_count, total_param_count).
    """
    issues: list[str] = []
    props = (schema or {}).get("properties") or {}
    props = props if isinstance(props, dict) else {}
    total = len(props)
    clear = sum(
        1
        for s in props.values()
        if _is_typed(s) and isinstance(s, dict) and str(s.get("description") or "").strip()
    )
    clarity = (clear / total) if total else 1.0

    required = (schema or {}).get("required") or []
    hostile = isinstance(required, list) and len(required) > MAX_REQUIRED_PARAMS
    if hostile:
        issues.append(
            f"`{name}` has {len(required)} required parameters "
            f"(> {MAX_REQUIRED_PARAMS} is agent-hostile)"
        )

    score = PARAM_CLARITY_WEIGHT * clarity + PARAM_HOSTILITY_WEIGHT * (0.0 if hostile else 1.0)
    return _clamp(score), issues, clear, total


# ---------------------------------------------------------------------------
# Server-level scoring
# ---------------------------------------------------------------------------


def estimate_tool_surface_tokens(tools: list[dict[str, Any]]) -> int:
    """Estimate the token cost of presenting all tools to an LLM."""
    serialized = json.dumps(
        [
            {
                "name": t.get("name", ""),
                "description": t.get("description") or "",
                "input_schema": t.get("input_schema") or {},
            }
            for t in tools
        ]
    )
    return len(serialized) // CHARS_PER_TOKEN


def _linear_credit(value: float, full_at: float, zero_at: float) -> float:
    """1.0 at <= full_at, 0.0 at >= zero_at, linear in between."""
    if value <= full_at:
        return 1.0
    if value >= zero_at:
        return 0.0
    return (zero_at - value) / (zero_at - full_at)


def _score_economy(tools: list[dict[str, Any]], estimated_tokens: int) -> tuple[float, list[str]]:
    findings: list[str] = []
    count = len(tools)

    count_credit = _linear_credit(count, TOOL_COUNT_FULL_CREDIT, TOOL_COUNT_ZERO_CREDIT)
    if count_credit < 1.0:
        findings.append(
            f"server exposes {count} tools (> {TOOL_COUNT_FULL_CREDIT} degrades "
            f"agent tool selection; 0 credit at {TOOL_COUNT_ZERO_CREDIT}+)"
        )

    token_credit = _linear_credit(estimated_tokens, TOKENS_FULL_CREDIT, TOKENS_ZERO_CREDIT)
    if token_credit < 1.0:
        findings.append(
            f"tool surface costs ~{estimated_tokens} tokens "
            f"(full credit <= {TOKENS_FULL_CREDIT}, 0 credit at {TOKENS_ZERO_CREDIT}+)"
        )

    score = ECONOMY_COUNT_WEIGHT * count_credit + ECONOMY_TOKEN_WEIGHT * token_credit
    return _clamp(score), findings


def score_tools(tools: list[dict[str, Any]]) -> UsabilityScore:
    """Score an MCP server's tool surface for LLM usability.

    ``tools`` is a list of dicts with keys ``name``, ``description``
    (str or None), and ``input_schema`` (dict or None) — the shape
    :class:`testmcpy.src.mcp_client.MCPTool` exposes from ``list_tools``.

    Returns a :class:`UsabilityScore`. An empty list scores 0.0 / F with
    explicit "no tools" findings (documented choice: an empty surface is
    unusable, not vacuously perfect).
    """
    if not tools:
        no_tools = "server exposes no tools"
        return UsabilityScore(
            score=0.0,
            grade=FAILING_GRADE,
            dimensions={
                name: DimensionResult(score=0.0, weight=weight, findings=[no_tools])
                for name, weight in DIMENSION_WEIGHTS.items()
            },
            tool_count=0,
            estimated_tokens=0,
            per_tool=[],
        )

    estimated_tokens = estimate_tool_surface_tokens(tools)

    desc_scores: list[float] = []
    schema_scores: list[float] = []
    name_scores: list[float] = []
    param_scores: list[float] = []
    desc_findings: list[str] = []
    schema_findings: list[str] = []
    name_findings: list[str] = []
    param_findings: list[str] = []
    per_tool: list[dict[str, Any]] = []
    total_params = 0
    clear_params = 0
    hostile_tools = 0
    case_styles: Counter[str] = Counter()

    for tool in tools:
        name = str(tool.get("name") or "")
        schema = tool.get("input_schema")

        d_score, d_issues = _score_description(name, tool.get("description"))
        s_score, s_issues = _score_schema(name, schema)
        n_score, n_issues = _score_name(name)
        p_score, p_issues, clear, total = _score_params(name, schema)

        desc_scores.append(d_score)
        schema_scores.append(s_score)
        name_scores.append(n_score)
        param_scores.append(p_score)
        desc_findings.extend(d_issues)
        schema_findings.extend(s_issues)
        name_findings.extend(n_issues)
        param_findings.extend(p_issues)
        clear_params += clear
        total_params += total
        if p_issues:
            hostile_tools += 1
        case_styles[_name_case_style(name)] += 1

        issues = d_issues + s_issues + n_issues + p_issues
        per_tool.append(
            {
                "name": name,
                "score": round((d_score + s_score + n_score + p_score) / 4, 4),
                "issues": issues,
            }
        )

    n = len(tools)

    # descriptions: mean of per-tool description scores.
    descriptions_score = sum(desc_scores) / n

    # schemas: mean of per-tool schema scores.
    schemas_score = sum(schema_scores) / n

    # naming: mean of per-tool name scores, then server-level adjustments.
    naming_score = sum(name_scores) / n
    definite_styles = {s for s in case_styles if s in ("snake", "kebab")}
    if len(definite_styles) > 1:
        naming_score *= NAME_INCONSISTENT_CASE_FACTOR
        name_findings.append(
            "naming style is inconsistent across the server (mixes snake_case and kebab-case)"
        )
    normalized = Counter(str(t.get("name") or "").lower().replace("-", "_") for t in tools)
    collisions = [norm for norm, c in normalized.items() if c > 1]
    for norm in collisions:
        naming_score -= NAME_COLLISION_PENALTY
        name_findings.append(f"multiple tools collide on the normalized name `{norm}`")
    naming_score = _clamp(naming_score)

    # economy: tool count + token cost of the serialized surface.
    economy_score, economy_findings = _score_economy(tools, estimated_tokens)

    # parameter_clarity: server-wide clear-parameter fraction + hostility.
    clarity_fraction = (clear_params / total_params) if total_params else 1.0
    hostility_fraction = hostile_tools / n
    parameter_clarity_score = _clamp(
        PARAM_CLARITY_WEIGHT * clarity_fraction
        + PARAM_HOSTILITY_WEIGHT * (1.0 - hostility_fraction)
    )
    if total_params and clarity_fraction < 1.0:
        param_findings.insert(
            0,
            f"{clear_params}/{total_params} parameters server-wide have "
            "both a type and a description",
        )

    dimensions = {
        "descriptions": DimensionResult(
            round(descriptions_score, 4), DIMENSION_WEIGHTS["descriptions"], desc_findings
        ),
        "schemas": DimensionResult(
            round(schemas_score, 4), DIMENSION_WEIGHTS["schemas"], schema_findings
        ),
        "naming": DimensionResult(
            round(naming_score, 4), DIMENSION_WEIGHTS["naming"], name_findings
        ),
        "economy": DimensionResult(
            round(economy_score, 4), DIMENSION_WEIGHTS["economy"], economy_findings
        ),
        "parameter_clarity": DimensionResult(
            round(parameter_clarity_score, 4),
            DIMENSION_WEIGHTS["parameter_clarity"],
            param_findings,
        ),
    }

    composite = round(sum(d.score * d.weight for d in dimensions.values()) * 100, 2)

    return UsabilityScore(
        score=composite,
        grade=_grade_for(composite),
        dimensions=dimensions,
        tool_count=n,
        estimated_tokens=estimated_tokens,
        per_tool=per_tool,
    )
