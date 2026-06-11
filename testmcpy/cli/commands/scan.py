"""`testmcpy scan` — static security scan of an MCP server's tool surface.

Connects to a server, lists its tools, and runs static tool-poisoning
checks (hidden instructions, invisible characters, cross-tool steering,
exfiltration hints, suspicious URLs, ...) over the tool METADATA. With a
saved baseline it also detects rug pulls (descriptions/schemas changed
after review). Nothing is executed against the server beyond listing
tools. Rules live in :mod:`testmcpy.security.rules`.
"""

import asyncio
import json
from pathlib import Path
from typing import Optional

import typer
from rich.panel import Panel
from rich.table import Table

from testmcpy.cli.app import app, console

# Imported as module-level names so tests can monkeypatch them, same as score.
from testmcpy.cli.commands.score import _fetch_tools, _resolve_connection

_SEVERITY_STYLES = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "dim",
}


@app.command()
def scan(
    mcp_url: Optional[str] = typer.Option(
        None, "--mcp-url", help="MCP service URL (overrides profile)"
    ),
    profile: Optional[str] = typer.Option(
        None, "--profile", help="MCP service profile from .mcp_services.yaml"
    ),
    output_format: str = typer.Option("table", "--format", help="table, json, or sarif"),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write the report (JSON, or SARIF with --format sarif)"
    ),
    baseline: Optional[Path] = typer.Option(
        None, "--baseline", help="Baseline JSON (from --save-baseline); enables rug-pull checks"
    ),
    save_baseline: Optional[Path] = typer.Option(
        None, "--save-baseline", help="Save the current tool list as a baseline and exit"
    ),
    max_severity: Optional[str] = typer.Option(
        None,
        "--max-severity",
        help="Exit 1 if any finding exceeds this severity (low|medium|high|critical)",
    ),
    gate: bool = typer.Option(
        False,
        "--gate",
        help="Read security.max_severity from .testmcpy-gate.yaml (unified gate)",
    ),
):
    """Scan an MCP server's tool metadata for poisoning and rug-pull patterns."""
    from testmcpy.security.rules import SEVERITIES, severity_exceeds
    from testmcpy.security.scanner import scan_rug_pull, scan_tools
    from testmcpy.src.mcp_client import MCPError

    if output_format not in ("table", "json", "sarif"):
        console.print(f"[red]Unknown format:[/red] {output_format} (use table, json, or sarif)")
        raise typer.Exit(2)

    if gate and max_severity is None:
        from testmcpy.src.ci_gate import load_gate_section

        section_value = load_gate_section("security").get("max_severity")
        if section_value is not None:
            max_severity = str(section_value)

    if max_severity is not None and max_severity not in SEVERITIES:
        console.print(
            f"[red]Invalid --max-severity:[/red] {max_severity} "
            f"(use one of: {', '.join(SEVERITIES)})"
        )
        raise typer.Exit(2)

    effective_mcp_url, auth_config, effective_profile = _resolve_connection(mcp_url, profile)

    if not effective_mcp_url:
        console.print(
            "[red]No MCP server specified.[/red] "
            "Use --mcp-url or --profile (or configure a default profile)."
        )
        raise typer.Exit(2)

    if output_format == "table":
        # Keep stdout pipe-clean in json/sarif modes.
        console.print(
            Panel.fit(
                f"[bold cyan]MCP Security Scan[/bold cyan]\n"
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

    if save_baseline:
        save_baseline.parent.mkdir(parents=True, exist_ok=True)
        save_baseline.write_text(json.dumps({"url": effective_mcp_url, "tools": tools}, indent=2))
        console.print(f"[green]Baseline with {len(tools)} tools saved to {save_baseline}[/green]")
        return

    findings = scan_tools(tools)

    if baseline:
        try:
            baseline_data = json.loads(baseline.read_text())
        except (OSError, json.JSONDecodeError) as e:
            console.print(f"[red]Could not read baseline {baseline}:[/red] {e}")
            raise typer.Exit(2) from None
        findings += scan_rug_pull(baseline_data.get("tools", []), tools)

    summary = dict.fromkeys(reversed(SEVERITIES), 0)
    for finding in findings:
        summary[finding.severity] += 1

    if output_format == "sarif":
        from testmcpy import __version__
        from testmcpy.src.emitters import to_sarif

        report = to_sarif(findings, __version__)
    else:
        report = json.dumps(
            {
                "url": effective_mcp_url,
                "findings": [f.to_dict() for f in findings],
                "summary": summary,
            },
            indent=2,
        )

    if output_format == "table":
        _render_table(findings, summary, len(tools))
    else:
        console.print_json(report)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report)
        if output_format == "table":
            console.print(f"[dim]Report written to {output}[/dim]")

    if max_severity is not None and any(
        severity_exceeds(f.severity, max_severity) for f in findings
    ):
        if output_format == "table":
            console.print(
                f"\n[red]Findings exceed the maximum allowed severity ({max_severity})[/red]"
            )
        raise typer.Exit(1)


def _render_table(findings, summary: dict[str, int], tool_count: int) -> None:
    """Render findings as a rich table plus a summary line."""
    if not findings:
        console.print(f"[green]No findings — {tool_count} tools look clean.[/green]")
        return

    from testmcpy.security.rules import severity_rank

    table = Table(show_header=True, header_style="bold cyan", title="Security Findings")
    table.add_column("Severity")
    table.add_column("Rule")
    table.add_column("Tool")
    table.add_column("Message", overflow="fold")
    for finding in sorted(findings, key=lambda f: -severity_rank(f.severity)):
        style = _SEVERITY_STYLES.get(finding.severity, "white")
        table.add_row(
            f"[{style}]{finding.severity}[/{style}]",
            finding.rule_id,
            finding.tool_name,
            f"{finding.message}\n[dim]{finding.evidence}[/dim]",
        )
    console.print(table)

    parts = [
        f"[{_SEVERITY_STYLES[sev]}]{count} {sev}[/{_SEVERITY_STYLES[sev]}]"
        for sev, count in summary.items()
        if count
    ]
    console.print(f"\n{len(findings)} finding(s) across {tool_count} tools: " + ", ".join(parts))
