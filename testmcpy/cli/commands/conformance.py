"""`testmcpy conformance` — wrap the official MCP conformance suite.

Runs `npx @modelcontextprotocol/conformance` (pinned version) against a
server URL, parses the checks.json results it writes, and renders them
through testmcpy's table/JSON output with a CI-friendly exit code.

We deliberately wrap rather than reimplement: the official suite is the
source of truth for spec compliance; testmcpy adds the layer above it
(LLM-driven evals, usability scoring, security scanning) and one place
to gate on all of them.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

import typer
from rich.table import Table

from testmcpy.cli.app import app, console

# Pinned by default so output-format drift in the npx package can't
# silently break parsing; override with --suite-version.
DEFAULT_CONFORMANCE_VERSION = "0.1.16"

_STATUS_STYLES = {
    "SUCCESS": "[green]PASS[/green]",
    "FAILURE": "[red]FAIL[/red]",
    "WARNING": "[yellow]WARN[/yellow]",
}


def _collect_checks(results_dir: Path) -> list[dict[str, Any]]:
    """Gather checks from every results/server-*/checks.json the suite wrote."""
    checks: list[dict[str, Any]] = []
    for checks_file in sorted(results_dir.glob("*/checks.json")):
        scenario = checks_file.parent.name
        try:
            data = json.loads(checks_file.read_text())
        except (OSError, json.JSONDecodeError) as e:
            console.print(f"[yellow]Warning: could not parse {checks_file}: {e}[/yellow]")
            continue
        items = data if isinstance(data, list) else data.get("checks", [])
        for check in items:
            if isinstance(check, dict):
                check.setdefault("scenario", scenario)
                checks.append(check)
    return checks


@app.command()
def conformance(
    mcp_url: str = typer.Argument(..., help="MCP server URL to test"),
    scenario: Optional[str] = typer.Option(
        None, "--scenario", help="Run a single scenario (e.g. server-initialize)"
    ),
    suite: Optional[str] = typer.Option(
        None, "--suite", help="Suite to run: active (default), all, draft, pending"
    ),
    suite_version: str = typer.Option(
        DEFAULT_CONFORMANCE_VERSION,
        "--suite-version",
        help="@modelcontextprotocol/conformance version to run via npx",
    ),
    output_format: str = typer.Option("table", "--format", help="table or json"),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write raw checks JSON to this path"
    ),
    timeout: int = typer.Option(300, "--timeout", help="Suite timeout in seconds"),
    fail_on_warning: bool = typer.Option(
        False, "--fail-on-warning", help="Exit non-zero on WARNING checks too"
    ),
):
    """Run the official MCP spec conformance suite against a server."""
    npx = shutil.which("npx")
    if not npx:
        console.print(
            "[red]npx not found.[/red] The conformance suite is a Node.js tool — "
            "install Node.js 22+ (https://nodejs.org) and re-run."
        )
        raise typer.Exit(2)

    cmd = [
        npx,
        "-y",
        f"@modelcontextprotocol/conformance@{suite_version}",
        "server",
        "--url",
        mcp_url,
    ]
    if scenario:
        cmd += ["--scenario", scenario]
    if suite:
        cmd += ["--suite", suite]

    console.print(
        f"[bold]MCP Conformance[/bold] — suite v{suite_version} against {mcp_url}\n"
        f"[dim]{' '.join(cmd)}[/dim]\n"
    )

    # The suite writes results/<scenario>-<timestamp>/checks.json relative
    # to cwd — run in a tempdir so we never litter the user's project.
    with tempfile.TemporaryDirectory(prefix="testmcpy-conformance-") as workdir:
        try:
            proc = subprocess.run(
                cmd,
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            console.print(f"[red]Conformance suite timed out after {timeout}s[/red]")
            raise typer.Exit(2) from None

        checks = _collect_checks(Path(workdir) / "results")

        if not checks:
            console.print("[red]Conformance suite produced no checks.[/red]")
            if proc.stdout.strip():
                console.print(f"[dim]stdout:[/dim]\n{proc.stdout[-2000:]}")
            if proc.stderr.strip():
                console.print(f"[dim]stderr:[/dim]\n{proc.stderr[-2000:]}")
            if "globSync" in proc.stderr or "SyntaxError" in proc.stderr:
                console.print(
                    "[yellow]Hint: the conformance suite requires Node.js 22+ — "
                    "check `node --version`.[/yellow]"
                )
            raise typer.Exit(2)

    graded = [c for c in checks if c.get("status") in _STATUS_STYLES]
    failures = [c for c in graded if c.get("status") == "FAILURE"]
    warnings = [c for c in graded if c.get("status") == "WARNING"]
    passed = [c for c in graded if c.get("status") == "SUCCESS"]

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"url": mcp_url, "checks": checks}, indent=2))
        console.print(f"[dim]Raw checks written to {output}[/dim]")

    if output_format == "json":
        console.print_json(
            json.dumps(
                {
                    "url": mcp_url,
                    "suite_version": suite_version,
                    "total": len(graded),
                    "passed": len(passed),
                    "failed": len(failures),
                    "warnings": len(warnings),
                    "checks": graded,
                }
            )
        )
    else:
        table = Table(show_header=True, header_style="bold cyan", title="Conformance Checks")
        table.add_column("Status", justify="center")
        table.add_column("Scenario", style="dim")
        table.add_column("Check")
        table.add_column("Detail", overflow="fold")
        for check in graded:
            table.add_row(
                _STATUS_STYLES[check["status"]],
                check.get("scenario", "—"),
                check.get("name", check.get("id", "?")),
                check.get("errorMessage") or "",
            )
        console.print(table)
        console.print(
            f"\n[bold]Summary:[/bold] {len(passed)}/{len(graded)} passed, "
            f"{len(failures)} failed, {len(warnings)} warnings"
        )

    if failures or (fail_on_warning and warnings):
        raise typer.Exit(1)
