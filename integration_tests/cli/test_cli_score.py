"""CLI integration tests for `testmcpy score` (MCP client layer mocked)."""

import json

import pytest

PERFECT_TOOLS = [
    {
        "name": "list_dashboards",
        "description": "List dashboards in the workspace with optional filters.",
        "input_schema": {
            "type": "object",
            "properties": {"page": {"type": "integer", "description": "1-based page number"}},
            "required": ["page"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_chart_data",
        "description": "Fetch the underlying data for a chart by its numeric ID.",
        "input_schema": {
            "type": "object",
            "properties": {"chart_id": {"type": "integer", "description": "Chart ID"}},
            "required": ["chart_id"],
            "additionalProperties": False,
        },
    },
]

BROKEN_TOOLS = [
    {"name": "q", "description": None, "input_schema": None},
    {"name": "doStuff", "description": "", "input_schema": None},
]


@pytest.fixture
def fake_tools(monkeypatch):
    """Replace the command's MCP fetch with canned tool lists."""
    import testmcpy.cli.commands.score as score_mod

    def install(tools):
        async def fake_fetch(mcp_url, auth_config):
            return tools

        monkeypatch.setattr(score_mod, "_fetch_tools", fake_fetch)

    return install


def test_table_output_shows_grade(runner, cli_app, fake_tools):
    fake_tools(PERFECT_TOOLS)
    result = runner.invoke(cli_app, ["score", "--mcp-url", "http://x/mcp"])
    assert result.exit_code == 0
    assert "grade A" in result.stdout
    assert "Dimensions" in result.stdout


def test_table_output_shows_worst_tools(runner, cli_app, fake_tools):
    fake_tools(BROKEN_TOOLS)
    result = runner.invoke(cli_app, ["score", "--mcp-url", "http://x/mcp"])
    assert result.exit_code == 0
    assert "Worst" in result.stdout
    assert "no description" in result.stdout


def test_json_output_parses_clean(runner, cli_app, fake_tools):
    fake_tools(PERFECT_TOOLS)
    result = runner.invoke(cli_app, ["score", "--mcp-url", "http://x/mcp", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["grade"] == "A"
    assert data["score"] >= 90
    assert data["tool_count"] == 2
    assert set(data["dimensions"]) == {
        "descriptions",
        "schemas",
        "naming",
        "economy",
        "parameter_clarity",
    }


def test_min_score_gates_exit_code(runner, cli_app, fake_tools):
    fake_tools(BROKEN_TOOLS)
    failing = runner.invoke(cli_app, ["score", "--mcp-url", "http://x/mcp", "--min-score", "90"])
    assert failing.exit_code == 1
    assert "below --min-score" in failing.stdout

    passing = runner.invoke(cli_app, ["score", "--mcp-url", "http://x/mcp", "--min-score", "10"])
    assert passing.exit_code == 0


def test_min_score_gate_in_json_mode_keeps_stdout_clean(runner, cli_app, fake_tools):
    fake_tools(BROKEN_TOOLS)
    result = runner.invoke(
        cli_app,
        ["score", "--mcp-url", "http://x/mcp", "--min-score", "90", "--format", "json"],
    )
    assert result.exit_code == 1
    json.loads(result.stdout)  # stdout is still pure JSON


def test_output_file_written(runner, cli_app, fake_tools, tmp_path):
    fake_tools(PERFECT_TOOLS)
    out = tmp_path / "score.json"
    result = runner.invoke(cli_app, ["score", "--mcp-url", "http://x/mcp", "--output", str(out)])
    assert result.exit_code == 0
    data = json.loads(out.read_text())
    assert data["grade"] == "A"
    assert len(data["per_tool"]) == 2


def test_unreachable_server_exits_nonzero(runner, cli_app, monkeypatch):
    import testmcpy.cli.commands.score as score_mod
    from testmcpy.src.mcp_client import MCPConnectionError

    async def fail_fetch(mcp_url, auth_config):
        raise MCPConnectionError("Failed to connect to MCP service: connection refused")

    monkeypatch.setattr(score_mod, "_fetch_tools", fail_fetch)
    result = runner.invoke(cli_app, ["score", "--mcp-url", "http://localhost:1/mcp"])
    assert result.exit_code == 2
    # rich may wrap long lines, so assert on short substrings
    assert "Error connecting to MCP service" in result.stdout
    assert "refused" in result.stdout


def test_no_server_specified_exits_nonzero(runner, cli_app, monkeypatch):
    import testmcpy.cli.commands.score as score_mod

    monkeypatch.setattr(
        score_mod, "_resolve_connection", lambda mcp_url, profile: (None, None, None)
    )
    result = runner.invoke(cli_app, ["score"])
    assert result.exit_code == 2
    assert "No MCP server specified" in result.stdout


def test_empty_tool_list_scores_zero(runner, cli_app, fake_tools):
    fake_tools([])
    result = runner.invoke(cli_app, ["score", "--mcp-url", "http://x/mcp", "--format", "json"])
    data = json.loads(result.stdout)
    assert data["score"] == 0.0
    assert data["grade"] == "F"
