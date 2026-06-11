"""`testmcpy score` — LLM-usability score for an MCP server's tool surface.

Connects to a server, lists its tools, and grades how usable that tool
surface is for LLM agents (naming, descriptions, schemas, token cost)
on a 0-100 scale with a letter grade and a per-dimension breakdown.
The rubric lives in :mod:`testmcpy.src.usability_score`.
"""

import asyncio
import json
from pathlib import Path
from typing import Any, Optional

import typer
from rich.panel import Panel
from rich.table import Table

from testmcpy.cli.app import DEFAULT_MCP_URL, app, console

# How many of the lowest-scoring tools to surface in table output.
WORST_TOOLS_SHOWN = 5
# How many findings to show per dimension in table output.
FINDINGS_PER_DIMENSION = 3

_GRADE_STYLES = {"A": "green", "B": "green", "C": "yellow", "D": "yellow", "F": "red"}


async def _fetch_tools(mcp_url: str, auth_config: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Connect to the MCP server and return tool dicts for scoring."""
    from testmcpy.src.mcp_client import MCPClient

    async with MCPClient(mcp_url, auth=auth_config) as client:
        tools = await client.list_tools()
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


def _resolve_connection(
    mcp_url: Optional[str], profile: Optional[str]
) -> tuple[Optional[str], Optional[dict[str, Any]], Optional[str]]:
    """Resolve effective MCP URL + auth from --mcp-url/--profile (same as `tools`)."""
    from testmcpy.mcp_profiles import get_profile_config

    profile_config = get_profile_config()
    effective_profile = profile

    if profile:
        prof = profile_config.get_profile(profile)
    else:
        default_profile_id = profile_config.default_profile
        if default_profile_id:
            prof = profile_config.get_profile(default_profile_id)
            effective_profile = default_profile_id
        else:
            prof = None

    if prof and prof.mcps:
        mcp_server = prof.mcps[0]
        effective_mcp_url = mcp_url or mcp_server.mcp_url
        auth_config = mcp_server.auth.to_dict() if mcp_server.auth else None
    else:
        effective_mcp_url = mcp_url or DEFAULT_MCP_URL
        auth_config = None

    return effective_mcp_url, auth_config, effective_profile


@app.command()
def score(
    mcp_url: Optional[str] = typer.Option(
        None, "--mcp-url", help="MCP service URL (overrides profile)"
    ),
    profile: Optional[str] = typer.Option(
        None, "--profile", help="MCP service profile from .mcp_services.yaml"
    ),
    output_format: str = typer.Option("table", "--format", help="table or json"),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write full result JSON to this path"
    ),
    min_score: Optional[float] = typer.Option(
        None, "--min-score", help="Exit 1 if the score is below this value (CI gate)"
    ),
    gate: bool = typer.Option(
        False,
        "--gate",
        help="Read usability.min_score from .testmcpy-gate.yaml (unified gate)",
    ),
):
    """Grade an MCP server's tool surface for LLM usability (0-100, A-F)."""
    from testmcpy.src.mcp_client import MCPError
    from testmcpy.src.usability_score import score_tools

    if gate and min_score is None:
        from testmcpy.src.ci_gate import load_gate_section

        section_value = load_gate_section("usability").get("min_score")
        if section_value is not None:
            min_score = float(section_value)

    effective_mcp_url, auth_config, effective_profile = _resolve_connection(mcp_url, profile)

    if not effective_mcp_url:
        console.print(
            "[red]No MCP server specified.[/red] "
            "Use --mcp-url or --profile (or configure a default profile)."
        )
        raise typer.Exit(2)

    if output_format != "json":
        # Keep stdout pure JSON in --format json so CI can pipe it.
        console.print(
            Panel.fit(
                f"[bold cyan]LLM-Usability Score[/bold cyan]\n"
                f"Service: {effective_mcp_url}\n"
                f"Profile: {effective_profile or 'none'}",
                border_style="cyan",
            )
        )

    try:
        tools = asyncio.run(_fetch_tools(effective_mcp_url, auth_config))
    except (MCPError, OSError) as e:
        console.print(f"[red]Error connecting to MCP service:[/red] {e}")
        raise typer.Exit(2) from None

    result = score_tools(tools)
    result_dict = result.to_dict()

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result_dict, indent=2))
        if output_format != "json":
            console.print(f"[dim]Full result written to {output}[/dim]")

    if output_format == "json":
        console.print_json(json.dumps(result_dict))
    else:
        _render_table(result_dict)

    if min_score is not None and result.score < min_score:
        if output_format != "json":
            console.print(f"\n[red]Score {result.score} is below the minimum of {min_score}[/red]")
        raise typer.Exit(1)


def _render_table(result: dict[str, Any]) -> None:
    """Render the score result as rich panels/tables."""
    grade = result["grade"]
    style = _GRADE_STYLES.get(grade, "red")
    console.print(
        Panel.fit(
            f"[bold {style}]{result['score']:.1f} / 100  —  grade {grade}[/bold {style}]\n"
            f"[dim]{result['tool_count']} tools, "
            f"~{result['estimated_tokens']} tokens of tool surface[/dim]",
            title="[bold]LLM-Usability Score[/bold]",
            border_style=style,
        )
    )

    table = Table(show_header=True, header_style="bold cyan", title="Dimensions")
    table.add_column("Dimension")
    table.add_column("Score", justify="right")
    table.add_column("Weight", justify="right")
    table.add_column("Top findings", overflow="fold")
    for name, dim in result["dimensions"].items():
        findings = dim["findings"][:FINDINGS_PER_DIMENSION]
        more = len(dim["findings"]) - len(findings)
        text = "\n".join(findings) + (f"\n[dim]... and {more} more[/dim]" if more > 0 else "")
        table.add_row(
            name,
            f"{dim['score'] * 100:.0f}%",
            f"{dim['weight']:.2f}",
            text or "[dim]none[/dim]",
        )
    console.print(table)

    worst = sorted(result["per_tool"], key=lambda t: t["score"])[:WORST_TOOLS_SHOWN]
    worst = [t for t in worst if t["issues"]]
    if worst:
        worst_table = Table(
            show_header=True, header_style="bold cyan", title=f"Worst {len(worst)} Tools"
        )
        worst_table.add_column("Tool")
        worst_table.add_column("Score", justify="right")
        worst_table.add_column("Issues", overflow="fold")
        for t in worst:
            worst_table.add_row(t["name"], f"{t['score'] * 100:.0f}%", "\n".join(t["issues"]))
        console.print(worst_table)
