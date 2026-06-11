"""Unit tests for the deterministic LLM-usability scoring rubric."""

from testmcpy.src.usability_score import (
    DIMENSION_WEIGHTS,
    estimate_tool_surface_tokens,
    score_tools,
)


def make_tool(name, description=None, properties=None, required=None):
    """Build a well-formed tool dict; properties is {name: (type, desc)}."""
    properties = properties or {}
    schema = {
        "type": "object",
        "properties": {p: {"type": t, "description": d} for p, (t, d) in properties.items()},
        "required": required if required is not None else [],
        "additionalProperties": False,
    }
    return {"name": name, "description": description, "input_schema": schema}


PERFECT_TOOLS = [
    make_tool(
        "list_dashboards",
        "List dashboards in the workspace with optional pagination and filters.",
        {"page": ("integer", "1-based page number"), "query": ("string", "Filter text")},
        required=["page"],
    ),
    make_tool(
        "get_chart_data",
        "Fetch the underlying data for a chart by its numeric ID.",
        {"chart_id": ("integer", "The chart's numeric ID")},
        required=["chart_id"],
    ),
    make_tool(
        "create_dataset",
        "Create a new dataset from a database table and return its metadata.",
        {
            "table": ("string", "Fully qualified table name"),
            "database_id": ("integer", "Target database connection ID"),
        },
        required=["table", "database_id"],
    ),
]


class TestWeights:
    def test_weights_sum_to_one(self):
        assert abs(sum(DIMENSION_WEIGHTS.values()) - 1.0) < 1e-9


class TestPerfectServer:
    def test_scores_a_grade(self):
        result = score_tools(PERFECT_TOOLS)
        assert result.score >= 90
        assert result.grade == "A"

    def test_all_dimensions_full(self):
        result = score_tools(PERFECT_TOOLS)
        for name, dim in result.dimensions.items():
            assert dim.score == 1.0, f"{name}: {dim.findings}"

    def test_result_dict_shape(self):
        d = score_tools(PERFECT_TOOLS).to_dict()
        assert set(d) == {
            "score",
            "grade",
            "dimensions",
            "tool_count",
            "estimated_tokens",
            "per_tool",
        }
        assert d["tool_count"] == 3
        assert d["estimated_tokens"] > 0
        for dim in d["dimensions"].values():
            assert set(dim) == {"score", "weight", "findings"}


class TestEmptyToolList:
    """Documented choice: an empty surface scores 0 / F, not vacuously perfect."""

    def test_scores_zero_f(self):
        result = score_tools([])
        assert result.score == 0.0
        assert result.grade == "F"
        assert result.tool_count == 0
        assert result.per_tool == []

    def test_explicit_no_tools_finding(self):
        result = score_tools([])
        for dim in result.dimensions.values():
            assert "server exposes no tools" in dim.findings


class TestDescriptions:
    def test_missing_description_scores_poorly_with_finding(self):
        tools = [
            {"name": "get_data", "description": None, "input_schema": {"type": "object"}},
            {"name": "list_items", "description": "", "input_schema": {"type": "object"}},
        ]
        result = score_tools(tools)
        dim = result.dimensions["descriptions"]
        assert dim.score == 0.0
        assert "tool `get_data` has no description" in dim.findings
        assert "tool `list_items` has no description" in dim.findings

    def test_too_short_description_flagged(self):
        tools = [make_tool("get_data", "Gets data.")]
        dim = score_tools(tools).dimensions["descriptions"]
        assert dim.score < 1.0
        assert any("too short" in f for f in dim.findings)

    def test_name_restatement_flagged(self):
        tools = [make_tool("get_chart_data", "get chart data")]
        dim = score_tools(tools).dimensions["descriptions"]
        assert dim.score < 0.5
        assert any("restates the tool name" in f for f in dim.findings)

    def test_bloated_description_flagged(self):
        tools = [make_tool("get_data", "Fetch data. " + "x" * 2500)]
        dim = score_tools(tools).dimensions["descriptions"]
        assert dim.score < 1.0
        assert any("token bloat" in f for f in dim.findings)


class TestSchemas:
    def test_missing_schema_flagged(self):
        tools = [
            {
                "name": "get_data",
                "description": "Fetch data from the warehouse.",
                "input_schema": None,
            }
        ]
        dim = score_tools(tools).dimensions["schemas"]
        assert dim.score == 0.0
        assert "tool `get_data` has no input schema" in dim.findings

    def test_untyped_and_undescribed_params_flagged(self):
        tools = [
            {
                "name": "get_data",
                "description": "Fetch data from the warehouse by key.",
                "input_schema": {
                    "type": "object",
                    "properties": {"x": {}},
                    "required": [],
                },
            }
        ]
        dim = score_tools(tools).dimensions["schemas"]
        assert dim.score < 1.0
        assert "parameter `x` of `get_data` is untyped" in dim.findings
        assert "parameter `x` of `get_data` has no description" in dim.findings

    def test_missing_required_declaration_flagged(self):
        tools = [
            {
                "name": "get_data",
                "description": "Fetch data from the warehouse by key.",
                "input_schema": {
                    "type": "object",
                    "properties": {"x": {"type": "string", "description": "Key"}},
                },
            }
        ]
        dim = score_tools(tools).dimensions["schemas"]
        assert any("does not declare which parameters are required" in f for f in dim.findings)

    def test_additional_properties_grab_bag_flagged(self):
        tools = [
            {
                "name": "run_query",
                "description": "Execute an arbitrary SQL query and return rows.",
                "input_schema": {"type": "object", "additionalProperties": True},
            }
        ]
        dim = score_tools(tools).dimensions["schemas"]
        assert any("additionalProperties" in f for f in dim.findings)

    def test_perfect_schema_full_credit(self):
        dim = score_tools(PERFECT_TOOLS).dimensions["schemas"]
        assert dim.score == 1.0
        assert dim.findings == []


class TestNaming:
    def test_inconsistent_case_styles_flagged(self):
        tools = [
            make_tool("get_data", "Fetch data rows for the given identifier."),
            make_tool("listItems", "List the items available in the catalog."),
        ]
        dim = score_tools(tools).dimensions["naming"]
        assert dim.score < 1.0
        assert any("listItems" in f and "not snake_case" in f for f in dim.findings)

    def test_snake_kebab_mix_flagged_server_wide(self):
        tools = [
            make_tool("get_data", "Fetch data rows for the given identifier."),
            make_tool("list-items", "List the items available in the catalog."),
        ]
        dim = score_tools(tools).dimensions["naming"]
        assert any("inconsistent" in f for f in dim.findings)

    def test_cryptic_name_flagged(self):
        tools = [make_tool("q", "Run a query against the configured database.")]
        dim = score_tools(tools).dimensions["naming"]
        assert any("cryptic abbreviation" in f for f in dim.findings)

    def test_non_verb_name_flagged(self):
        tools = [make_tool("dashboard_info", "Return metadata about a dashboard by ID.")]
        dim = score_tools(tools).dimensions["naming"]
        assert any("does not start with an action verb" in f for f in dim.findings)

    def test_name_collision_after_normalization_flagged(self):
        tools = [
            make_tool("get_data", "Fetch data rows for the given identifier."),
            make_tool("get-data", "Fetch data rows for the given identifier too."),
        ]
        dim = score_tools(tools).dimensions["naming"]
        assert any("collide on the normalized name `get_data`" in f for f in dim.findings)


class TestEconomy:
    def test_150_tool_server_gets_zero_count_credit(self):
        tools = [
            make_tool(
                f"get_item_{i}",
                "Fetch a specific item from the catalog by position.",
                {"item_id": ("integer", "Item identifier")},
                required=["item_id"],
            )
            for i in range(150)
        ]
        result = score_tools(tools)
        dim = result.dimensions["economy"]
        assert dim.score <= 0.5  # count credit is 0; only token credit remains
        assert any("150 tools" in f for f in dim.findings)

    def test_moderate_overage_gets_linear_penalty(self):
        tools = [
            make_tool(f"get_item_{i}", "Fetch a specific item from the catalog.") for i in range(60)
        ]
        dim = score_tools(tools).dimensions["economy"]
        assert 0.5 < dim.score < 1.0

    def test_token_bloat_penalized(self):
        # 25 tools, each with a ~6000-char description: ~37k tokens.
        tools = [
            make_tool(f"get_item_{i}", "Fetch the item. " + ("very detailed docs " * 300))
            for i in range(25)
        ]
        result = score_tools(tools)
        dim = result.dimensions["economy"]
        assert result.estimated_tokens > 5000
        assert dim.score < 1.0
        assert any("tokens" in f for f in dim.findings)

    def test_small_server_full_credit(self):
        dim = score_tools(PERFECT_TOOLS).dimensions["economy"]
        assert dim.score == 1.0
        assert dim.findings == []

    def test_token_estimate_is_chars_over_four(self):
        tools = [{"name": "get_data", "description": "abc", "input_schema": {}}]
        import json

        expected = (
            len(json.dumps([{"name": "get_data", "description": "abc", "input_schema": {}}])) // 4
        )
        assert estimate_tool_surface_tokens(tools) == expected


class TestParameterClarity:
    def test_unclear_params_lower_score(self):
        tools = [
            {
                "name": "get_data",
                "description": "Fetch data from the warehouse by key.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "good": {"type": "string", "description": "Well documented"},
                        "bad": {},
                    },
                    "required": [],
                },
            }
        ]
        dim = score_tools(tools).dimensions["parameter_clarity"]
        assert dim.score < 1.0
        assert any("1/2 parameters" in f for f in dim.findings)

    def test_too_many_required_params_flagged(self):
        props = {f"p{i}": ("string", f"Parameter {i}") for i in range(12)}
        tools = [
            make_tool(
                "create_report",
                "Create a report from the given twelve configuration values.",
                props,
                required=list(props),
            )
        ]
        dim = score_tools(tools).dimensions["parameter_clarity"]
        assert dim.score < 1.0
        assert any("agent-hostile" in f for f in dim.findings)


class TestPerTool:
    def test_per_tool_issues_populated(self):
        tools = [
            {"name": "q", "description": None, "input_schema": None},
            make_tool(
                "list_dashboards",
                "List dashboards in the workspace with optional filters.",
                {"page": ("integer", "1-based page number")},
                required=[],
            ),
        ]
        result = score_tools(tools)
        per_tool = {t["name"]: t for t in result.per_tool}
        bad = per_tool["q"]
        assert bad["score"] < 0.5
        assert "tool `q` has no description" in bad["issues"]
        assert "tool `q` has no input schema" in bad["issues"]
        good = per_tool["list_dashboards"]
        assert good["score"] == 1.0
        assert good["issues"] == []

    def test_per_tool_scores_in_range(self):
        result = score_tools(
            PERFECT_TOOLS + [{"name": "x", "description": None, "input_schema": None}]
        )
        for t in result.per_tool:
            assert 0.0 <= t["score"] <= 1.0


class TestGrades:
    def test_grade_boundaries(self):
        # Drive composite scores via a mix of perfect and broken tools and
        # just assert grade consistency with the numeric score.
        broken = {"name": "q", "description": None, "input_schema": None}
        for tools in (PERFECT_TOOLS, PERFECT_TOOLS + [broken], [broken]):
            result = score_tools(tools)
            if result.score >= 90:
                assert result.grade == "A"
            elif result.score >= 80:
                assert result.grade == "B"
            elif result.score >= 70:
                assert result.grade == "C"
            elif result.score >= 60:
                assert result.grade == "D"
            else:
                assert result.grade == "F"

    def test_all_broken_server_fails(self):
        broken = [{"name": "q", "description": None, "input_schema": None}] * 1
        result = score_tools(broken)
        assert result.grade in ("D", "F")
        assert result.score < 70
