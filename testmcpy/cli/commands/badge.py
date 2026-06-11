"""`testmcpy badge` — shields.io endpoint JSON for quality badges.

Emits the schemaVersion-1 document that https://img.shields.io/endpoint
renders, so repos can show live pass-rate / usability / conformance
badges:

    ![evals](https://img.shields.io/endpoint?url=<hosted badge.json>)

Publish the JSON anywhere public (gist, pages branch, artifact).
"""

import json
from pathlib import Path
from typing import Any, Optional

import typer

from testmcpy.cli.app import app, console


def _color_for(value: float) -> str:
    """shields.io color ramp for a 0-100 quality value."""
    if value >= 90:
        return "brightgreen"
    if value >= 80:
        return "green"
    if value >= 70:
        return "yellowgreen"
    if value >= 60:
        return "yellow"
    if value >= 50:
        return "orange"
    return "red"


def _shield(label: str, message: str, color: str) -> dict[str, Any]:
    return {"schemaVersion": 1, "label": label, "message": message, "color": color}


def _emit(badge_doc: dict[str, Any], output: Optional[Path]) -> None:
    text = json.dumps(badge_doc, indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text)
        console.print(f"[green]Badge written to {output}[/green]")
    else:
        print(text)


@app.command()
def badge(
    badge_type: str = typer.Argument(..., help="Badge type: pass-rate, score, or conformance"),
    from_file: Optional[Path] = typer.Option(
        None,
        "--from",
        help=(
            "Result JSON produced by `testmcpy score --output` or "
            "`testmcpy conformance --output` (required for score/conformance)"
        ),
    ),
    suite: Optional[str] = typer.Option(
        None, "--suite", help="pass-rate only: filter to one test suite/file"
    ),
    since: Optional[str] = typer.Option(
        None, "--since", help="pass-rate only: window like '30d' or an ISO date"
    ),
    db_path: Optional[str] = typer.Option(
        None, "--db-path", help="pass-rate only: results DB path override"
    ),
    label: Optional[str] = typer.Option(None, "--label", help="Override the badge label"),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write badge JSON here (default: stdout)"
    ),
):
    """Emit shields.io endpoint JSON for a quality badge."""
    if badge_type == "pass-rate":
        from testmcpy import analytics
        from testmcpy.cli.commands.analytics import _get_session, _parse_since

        with _get_session(db_path) as session:
            configs = analytics.leaderboard(session, suite_id=suite, date_from=_parse_since(since))
        if not configs:
            _emit(_shield(label or "mcp evals", "no runs", "lightgrey"), output)
            return
        total_results = sum(c["n_results"] for c in configs)
        weighted = sum(c["pass_rate"] * c["n_results"] for c in configs)
        rate = (weighted / total_results * 100) if total_results else 0.0
        _emit(
            _shield(label or "mcp evals", f"{rate:.0f}% pass", _color_for(rate)),
            output,
        )

    elif badge_type == "score":
        if not from_file or not from_file.exists():
            console.print(
                "[red]--from FILE is required[/red] — generate one with "
                "[cyan]testmcpy score --output score.json[/cyan]"
            )
            raise typer.Exit(2)
        data = json.loads(from_file.read_text())
        value = float(data.get("score", 0.0))
        grade = data.get("grade", "?")
        _emit(
            _shield(label or "mcp usability", f"{value:.0f}/100 ({grade})", _color_for(value)),
            output,
        )

    elif badge_type == "conformance":
        if not from_file or not from_file.exists():
            console.print(
                "[red]--from FILE is required[/red] — generate one with "
                "[cyan]testmcpy conformance <url> --output checks.json[/cyan]"
            )
            raise typer.Exit(2)
        data = json.loads(from_file.read_text())
        checks = data.get("checks", [])
        graded = [c for c in checks if c.get("status") in ("SUCCESS", "FAILURE", "WARNING")]
        failed = sum(1 for c in graded if c.get("status") == "FAILURE")
        passed = sum(1 for c in graded if c.get("status") == "SUCCESS")
        if not graded:
            _emit(_shield(label or "mcp conformance", "no checks", "lightgrey"), output)
        elif failed:
            _emit(
                _shield(label or "mcp conformance", f"{failed} failing", "red"),
                output,
            )
        else:
            _emit(
                _shield(label or "mcp conformance", f"{passed} checks passing", "brightgreen"),
                output,
            )

    else:
        console.print(
            f"[red]Unknown badge type: {badge_type}[/red] (pass-rate, score, conformance)"
        )
        raise typer.Exit(2)
