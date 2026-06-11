"""`testmcpy bench` — run a suite across models × profiles × repeats.

The performance matrix (`testmcpy matrix`, /performance UI) needs the
same suite executed repeatedly under multiple configs; single runs are
statistical noise. bench builds the cross product and executes each
combination as a `testmcpy run` subprocess (clean provider state per
run), grouping everything under one session_id.
"""

import subprocess
import sys
import uuid
from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from testmcpy.cli.app import app, console


@app.command()
def bench(
    test_path: Path = typer.Argument(..., help="Path to test file or directory"),
    models: str = typer.Option(
        ..., "--models", help="Comma-separated models, e.g. claude-sonnet-4-5,gpt-4o"
    ),
    providers: Optional[str] = typer.Option(
        None,
        "--providers",
        help=(
            "Comma-separated providers aligned with --models "
            "(single value applies to all; default: provider per `testmcpy run` default)"
        ),
    ),
    profiles: Optional[str] = typer.Option(
        None, "--profiles", help="Comma-separated MCP profiles (default: just the default profile)"
    ),
    repeat: int = typer.Option(3, "--repeat", help="Runs per model × profile combination"),
    extra_args: Optional[str] = typer.Option(
        None,
        "--run-args",
        help='Extra args passed through to each `testmcpy run`, e.g. "--timeout 60"',
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the planned runs and exit"),
):
    """Run a suite across models × profiles × repeats for matrix analytics."""
    if not test_path.exists():
        console.print(f"[red]Error: test path does not exist: {test_path}[/red]")
        raise typer.Exit(1)
    if repeat < 1:
        console.print("[red]Error: --repeat must be >= 1[/red]")
        raise typer.Exit(1)

    model_list = [m.strip() for m in models.split(",") if m.strip()]
    profile_list: list[Optional[str]] = [
        p.strip() for p in (profiles or "").split(",") if p.strip()
    ] or [None]

    provider_list: list[Optional[str]]
    if providers:
        provider_list = [p.strip() or None for p in providers.split(",")]
        if len(provider_list) == 1:
            provider_list = provider_list * len(model_list)
        if len(provider_list) != len(model_list):
            console.print(
                f"[red]Error: {len(provider_list)} providers for "
                f"{len(model_list)} models — pass one per model or a single value[/red]"
            )
            raise typer.Exit(1)
    else:
        provider_list = [None] * len(model_list)

    session_id = str(uuid.uuid4())
    combos = [
        (model, provider, profile, iteration)
        for model, provider in zip(model_list, provider_list, strict=True)
        for profile in profile_list
        for iteration in range(1, repeat + 1)
    ]

    console.print(
        f"[bold]Bench:[/bold] {len(model_list)} model(s) × "
        f"{len(profile_list)} profile(s) × {repeat} repeat(s) "
        f"= {len(combos)} runs\n[dim]Session: {session_id}[/dim]"
    )

    if dry_run:
        for model, provider, profile, iteration in combos:
            label = f"{provider or 'default'}/{model}"
            if profile:
                label += f" @ {profile}"
            console.print(f"  • {label} (run {iteration}/{repeat})")
        return

    results = []
    for i, (model, provider, profile, iteration) in enumerate(combos, 1):
        label = f"{provider or 'default'}/{model}" + (f" @ {profile}" if profile else "")
        console.print(f"\n[cyan]── Run {i}/{len(combos)}: {label} (repeat {iteration}) ──[/cyan]")

        cmd = [
            sys.executable,
            "-m",
            "testmcpy",
            "run",
            str(test_path),
            "--model",
            model,
            "--session-id",
            session_id,
        ]
        if provider:
            cmd += ["--provider", provider]
        if profile:
            cmd += ["--profile", profile]
        if extra_args:
            cmd += extra_args.split()

        proc = subprocess.run(cmd)
        results.append((label, iteration, proc.returncode))

    table = Table(show_header=True, header_style="bold cyan", title="Bench Summary")
    table.add_column("Config")
    table.add_column("Repeat", justify="right")
    table.add_column("Exit", justify="right")
    failures = 0
    for label, iteration, code in results:
        if code != 0:
            failures += 1
        status = "[green]0[/green]" if code == 0 else f"[red]{code}[/red]"
        table.add_row(label, str(iteration), status)
    console.print(table)

    console.print(
        f"\n[bold]Session:[/bold] {session_id}\n"
        "Analyze with: [cyan]testmcpy matrix[/cyan] or "
        "[cyan]testmcpy leaderboard[/cyan], or open the /performance page"
    )
    if failures:
        console.print(
            f"[yellow]⚠ {failures}/{len(results)} run invocation(s) exited non-zero[/yellow]"
        )
        raise typer.Exit(1)
