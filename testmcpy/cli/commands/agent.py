"""Agent execution commands for the Test Execution Agent."""

import asyncio
import json
from pathlib import Path
from typing import Optional

import typer
from rich.panel import Panel
from rich.table import Table

from testmcpy.cli.app import app, console


@app.command(name="agent")
def agent_run(
    prompt: Optional[str] = typer.Argument(
        None,
        help="Natural language instruction for the agent",
    ),
    test_path: Optional[Path] = typer.Option(
        None,
        "--test-path",
        "-t",
        help="Path to test file or directory",
    ),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        "-p",
        help="MCP service profile from .mcp_services.yaml",
    ),
    mcp_url: Optional[str] = typer.Option(
        None,
        "--mcp-url",
        help="MCP service URL (overrides profile)",
    ),
    models: Optional[str] = typer.Option(
        None,
        "--models",
        "-m",
        help="Comma-separated list of models to test (e.g., claude-sonnet-4-5,gpt-4o)",
    ),
    max_turns: int = typer.Option(
        50,
        "--max-turns",
        help="Maximum agent turns",
    ),
    agent_model: Optional[str] = typer.Option(
        None,
        "--agent-model",
        help="Model for the agent itself (default: SDK default)",
    ),
    llm_profile: Optional[str] = typer.Option(
        None,
        "--llm-profile",
        help="LLM profile to source the Claude auth token from",
    ),
    cli_token: Optional[str] = typer.Option(
        None,
        "--cli-token",
        help="Claude auth token (subscription sk-ant-oat... or API key); "
        "overrides --llm-profile. Defaults to the host 'claude' login.",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Save agent report to file (JSON)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed agent output",
    ),
):
    """
    Run the Test Execution Agent.

    The agent uses Claude Agent SDK to intelligently orchestrate test execution,
    analysis, and reporting. It wraps testmcpy infrastructure with reasoning
    and natural language interaction.

    Examples:
        testmcpy agent "Run all tests in tests/example.yaml"
        testmcpy agent --test-path tests/ --profile prod
        testmcpy agent "Compare claude-sonnet-4-5 vs gpt-4o on tests/" --models claude-sonnet-4-5,gpt-4o
        testmcpy agent "What tools are available?" --profile my-profile
    """
    from testmcpy.agent.orchestrator import TestExecutionAgent

    # Build the prompt if not directly provided
    effective_prompt = prompt
    if not effective_prompt:
        if test_path:
            effective_prompt = f"Run all tests in {test_path}"
            if models:
                effective_prompt += f" using models: {models}"
        else:
            console.print(
                "[red]Error:[/red] Provide a prompt or --test-path. "
                "Example: testmcpy agent 'Run all tests in tests/example.yaml'"
            )
            raise typer.Exit(1)
    elif test_path:
        # Append test path context to the prompt
        effective_prompt += f"\n\nTest files are at: {test_path}"

    # Resolve MCP profile
    effective_profile = profile
    if not effective_profile and not mcp_url:
        from testmcpy.server.helpers.mcp_config import load_mcp_yaml

        mcp_config = load_mcp_yaml()
        effective_profile = mcp_config.get("default")

    # Parse models list
    model_list = [m.strip() for m in models.split(",")] if models else []

    # Resolve the Claude auth token: direct --cli-token wins, else from the
    # named LLM profile's default provider (api_key / api_key_env).
    effective_cli_token = cli_token
    if not effective_cli_token and llm_profile:
        from testmcpy.llm_profiles import (
            LLMProfileConfigError,
            get_llm_profile_config,
            load_llm_profile,
            resolve_llm_provider_selection,
        )
        from testmcpy.src.llm_integration import CLAUDE_SDK_PROVIDERS

        profile_config = get_llm_profile_config()
        if profile_config.load_error:
            console.print(
                f"[red]Error:[/red] Invalid LLM profile configuration: {profile_config.load_error}"
            )
            raise typer.Exit(1)
        prof = load_llm_profile(llm_profile)
        if not prof:
            console.print(f"[red]Error:[/red] LLM profile '{llm_profile}' was not found")
            raise typer.Exit(1)
        if not any(provider.provider in CLAUDE_SDK_PROVIDERS for provider in prof.providers):
            console.print(
                f"[red]Error:[/red] LLM profile '{llm_profile}' has no Claude SDK provider"
            )
            raise typer.Exit(1)
        try:
            _, _, provider_config = resolve_llm_provider_selection(
                provider="claude-sdk",
                model=agent_model,
                profile_id=llm_profile,
            )
        except LLMProfileConfigError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc
        token = provider_config.get("api_key")
        effective_cli_token = token if isinstance(token, str) else None

    from testmcpy.scrubber import register_secret, scrub_obj, scrub_text

    register_secret(effective_cli_token)

    console.print(
        Panel.fit(
            "[bold cyan]Test Execution Agent[/bold cyan]\n"
            f"[dim]{effective_prompt[:80]}{'...' if len(effective_prompt) > 80 else ''}[/dim]",
            border_style="cyan",
        )
    )

    if verbose:
        console.print(f"[dim]Profile: {effective_profile or 'none'}[/dim]")
        console.print(f"[dim]MCP URL: {mcp_url or 'from profile'}[/dim]")
        console.print(f"[dim]Models: {model_list or 'default'}[/dim]")
        console.print(f"[dim]Max turns: {max_turns}[/dim]")
        console.print()

    async def _run_agent():
        try:
            agent = TestExecutionAgent(
                mcp_profile=effective_profile,
                mcp_url=mcp_url,
                models=model_list,
                max_turns=max_turns,
                agent_model=agent_model,
                cli_token=effective_cli_token,
            )
        except ImportError as exc:
            console.print(f"[red]Error:[/red] {scrub_text(str(exc))}")
            raise typer.Exit(1) from exc

        with console.status("[cyan]Agent is working...[/cyan]"):
            report = await agent.run(effective_prompt)

        # Display results
        console.print()
        _display_report(report, verbose)

        # Save report if requested
        if output:
            output.write_text(json.dumps(scrub_obj(report.to_dict()), indent=2, default=str))
            console.print(f"\n[green]Report saved to {output}[/green]")

    asyncio.run(_run_agent())


def _display_report(report, verbose: bool = False):
    """Display the agent run report with Rich formatting."""
    from testmcpy.scrubber import scrub_text

    # Test Results Summary
    if report.tests_run > 0:
        status_color = "green" if report.tests_failed == 0 else "red"
        console.print(
            Panel.fit(
                f"[bold {status_color}]Test Results[/bold {status_color}]\n"
                f"Passed: {report.tests_passed}/{report.tests_run} | "
                f"Failed: {report.tests_failed} | "
                f"Pass Rate: {report.pass_rate:.0%}",
                border_style=status_color,
            )
        )

    # Cost breakdown
    cost_table = Table(show_header=True, header_style="bold", box=None)
    cost_table.add_column("Category", style="dim")
    cost_table.add_column("Cost", justify="right")
    cost_table.add_column("Tokens", justify="right")

    cost_table.add_row(
        "Orchestrator (Agent)",
        f"${report.orchestrator_cost_usd:.4f}",
        f"{report.orchestrator_tokens_input + report.orchestrator_tokens_output:,}",
    )
    cost_table.add_row(
        "Test Execution (Subject LLMs)",
        f"${report.test_execution_cost_usd:.4f}",
        f"{report.test_execution_tokens:,}",
    )
    cost_table.add_row(
        "[bold]Total[/bold]",
        f"[bold]${report.total_cost_usd:.4f}[/bold]",
        "",
    )

    console.print("\n[bold]Cost Breakdown[/bold]")
    console.print(cost_table)

    # Tool usage
    if report.tool_call_counts:
        console.print(f"\n[bold]Tool Usage[/bold] ({report.total_tool_calls} total calls)")
        for tool_name, count in sorted(
            report.tool_call_counts.items(), key=lambda x: x[1], reverse=True
        ):
            console.print(f"  {tool_name}: {count}")

    # Duration
    console.print(f"\n[bold]Duration:[/bold] {report.duration_ms / 1000:.1f}s")
    console.print(f"[bold]Agent Turns:[/bold] {report.num_turns}")

    # Errors
    if report.errors:
        console.print(f"\n[bold red]Errors ({len(report.errors)}):[/bold red]")
        for error in report.errors[:5]:
            console.print(f"  [red]{scrub_text(error)}[/red]")
        if len(report.errors) > 5:
            console.print(f"  [dim]... and {len(report.errors) - 5} more[/dim]")

    # Agent's analysis
    if report.analysis and verbose:
        console.print("\n[bold]Agent Analysis:[/bold]")
        console.print(Panel(scrub_text(report.analysis[:2000]), border_style="dim"))

    # Verbose: tool call history
    if verbose and report.tool_call_history:
        console.print("\n[bold]Tool Call History:[/bold]")
        for inv in report.tool_call_history:
            status = "[red]ERR[/red]" if inv.is_error else "[green]OK[/green]"
            console.print(f"  {status} {inv.tool_name} ({inv.duration_ms:.0f}ms)")
