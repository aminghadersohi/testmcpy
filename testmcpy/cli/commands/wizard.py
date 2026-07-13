"""Interactive wizard commands for adding MCP servers, LLM providers, and tests."""

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

import typer
import yaml
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from testmcpy.cli.app import app, console

_CREATE_LLM_PROFILE_CHOICE = "Create a new profile"
_DEFAULT_LLM_KEY_ENVS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "gemini-sdk": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
    "grok": "XAI_API_KEY",
}
_HOST_AUTH_LLM_PROVIDERS = {
    "claude-code",
    "claude-cli",
    "claude-sdk",
    "gemini-cli",
}
_CODEX_PROVIDERS = {"codex", "codex-cli", "codex-sdk"}


def _prompt(label: str, default: str = "", password: bool = False) -> str:
    """Prompt user for input with optional default."""
    if default:
        return Prompt.ask(f"[bold]{label}[/bold]", default=default, password=password)
    return Prompt.ask(f"[bold]{label}[/bold]", password=password)


def _choose(label: str, choices: list[str], default: str | None = None) -> str:
    """Prompt user to choose from a list."""
    console.print(f"\n[bold]{label}[/bold]")
    for i, choice in enumerate(choices, 1):
        marker = "[green]*[/green] " if choice == default else "  "
        console.print(f"  {marker}{i}. {choice}")

    default_index = choices.index(default) + 1 if default in choices else 1
    while True:
        raw = Prompt.ask("Enter number", default=str(default_index))
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        except ValueError:
            pass
        console.print("[red]Invalid choice, try again.[/red]")


def _redacted_provider_preview(provider_entry: dict[str, Any]) -> dict[str, Any]:
    """Return preview data that indicates direct credentials without exposing them."""
    preview = provider_entry.copy()
    for field in ("api_key", "api_token", "api_secret"):
        if preview.get(field):
            preview[field] = "*** configured ***"
    return preview


def _has_cached_codex_api_key() -> bool:
    """Return whether Codex's auth file contains a Platform API key, not OAuth only."""
    try:
        data = json.loads((Path.home() / ".codex" / "auth.json").read_text())
    except (OSError, json.JSONDecodeError):
        return False
    api_key = data.get("OPENAI_API_KEY") if isinstance(data, dict) else None
    return isinstance(api_key, str) and bool(api_key)


def _credential_status(provider: Any) -> str:
    """Describe configured credentials without resolving or displaying secrets."""
    raw = vars(provider)
    if raw.get("api_key"):
        return "direct key (configured)"

    provider_type = str(raw.get("provider") or "").lower()
    if provider_type in {"assistant", "chatbot"}:
        token_set = bool(raw.get("api_token"))
        secret_set = bool(raw.get("api_secret"))
        if token_set and secret_set:
            return "assistant token + secret (configured)"
        if token_set or secret_set:
            return "assistant credentials (partial)"
        return "assistant credentials (not configured)"

    env_name = raw.get("api_key_env")
    if env_name:
        state = "set" if os.environ.get(str(env_name)) else "unset"
        return f"env {env_name} ({state})"

    if provider_type in _HOST_AUTH_LLM_PROVIDERS:
        return "host login"

    if provider_type in _CODEX_PROVIDERS:
        if _has_cached_codex_api_key():
            return "host API key (configured)"
        return "Codex API key (not configured)"

    default_env = _DEFAULT_LLM_KEY_ENVS.get(provider_type)
    if default_env:
        state = "set" if os.environ.get(default_env) else "unset"
        return f"env {default_env} ({state})"
    if provider_type == "ollama":
        return "not required"
    return "not configured"


@app.command(name="add-mcp")
def add_mcp():
    """
    Interactive wizard to add an MCP server to your configuration.

    Walks you through: name, transport, connection, auth, test, and save.
    """
    console.print(
        Panel(
            "[bold cyan]Add MCP Server[/bold cyan]\n"
            "[dim]Follow the prompts to configure a new MCP server.[/dim]",
            border_style="cyan",
        )
    )

    # Step 1: Name
    console.print("\n[bold yellow]Step 1: Server Info[/bold yellow]")
    name = _prompt("Server name", "my-mcp-server")

    # Step 2: Transport
    console.print("\n[bold yellow]Step 2: Transport[/bold yellow]")
    transport = _choose("Transport type:", ["sse", "stdio"], default="sse")

    # Step 3: Connection
    console.print("\n[bold yellow]Step 3: Connection[/bold yellow]")
    mcp_url = ""
    command = ""
    args_str = ""

    if transport == "stdio":
        command = _prompt("Command (e.g., npx, python, node)")
        args_str = _prompt("Arguments (space-separated)", "")
    else:
        mcp_url = _prompt("MCP URL", "https://api.example.com/mcp/")

    timeout = IntPrompt.ask("[bold]Timeout (seconds)[/bold]", default=30)
    rate_limit = IntPrompt.ask("[bold]Rate limit (req/min)[/bold]", default=60)

    # Step 4: Auth
    console.print("\n[bold yellow]Step 4: Authentication[/bold yellow]")
    auth_type = _choose("Auth type:", ["none", "bearer", "jwt", "oauth"], default="none")

    auth_config: dict = {"type": auth_type}
    if auth_type == "bearer":
        token = _prompt("Bearer token (or ${ENV_VAR})", password=True)
        auth_config["token"] = token
    elif auth_type == "jwt":
        auth_config["api_url"] = _prompt("API URL")
        auth_config["api_token"] = _prompt("API Token", password=True)
        auth_config["api_secret"] = _prompt("API Secret", password=True)
    elif auth_type == "oauth":
        auto_discover = Confirm.ask("Use OAuth auto-discovery (RFC 8414)?", default=False)
        if auto_discover:
            auth_config["oauth_auto_discover"] = True
        else:
            auth_config["client_id"] = _prompt("Client ID")
            auth_config["client_secret"] = _prompt("Client Secret", password=True)
            auth_config["token_url"] = _prompt("Token URL")
            scopes = _prompt("Scopes (comma-separated)", "")
            if scopes:
                auth_config["scopes"] = [s.strip() for s in scopes.split(",") if s.strip()]

    # Step 5: Test Connection
    console.print("\n[bold yellow]Step 5: Test Connection[/bold yellow]")
    if Confirm.ask("Test connection now?", default=True):
        console.print("[dim]Connecting...[/dim]")
        try:
            from testmcpy.src.mcp_client import MCPClient, MCPError, StdioMCPClient

            if transport == "stdio":
                client: MCPClient | StdioMCPClient = StdioMCPClient(
                    command=command, args=args_str.split() if args_str else None
                )
            else:
                client = MCPClient(mcp_url, auth=auth_config)

            async def _test_connection():
                try:
                    await client.initialize(timeout=float(timeout))
                    return await client.list_tools(timeout=float(timeout))
                finally:
                    await client.close()

            tools = asyncio.run(_test_connection())
            console.print(f"[green]Connected! Found {len(tools)} tools.[/green]")
            if tools:
                tool_names = [t.name if hasattr(t, "name") else str(t) for t in tools[:5]]
                console.print(
                    f"[dim]  Tools: {', '.join(tool_names)}{'...' if len(tools) > 5 else ''}[/dim]"
                )
        except (MCPError, ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as e:
            console.print(f"[red]Connection failed: {e}[/red]")
            if not Confirm.ask("Continue anyway?", default=True):
                raise typer.Abort()

    # Step 6: Save
    console.print("\n[bold yellow]Step 6: Save[/bold yellow]")

    # Build MCP entry
    mcp_entry: dict = {"name": name, "timeout": timeout, "rate_limit_rpm": rate_limit}

    if transport == "stdio":
        mcp_entry["transport"] = "stdio"
        mcp_entry["command"] = command
        if args_str:
            mcp_entry["args"] = args_str.split()
        mcp_entry["mcp_url"] = f"stdio://{command}"
    else:
        mcp_entry["mcp_url"] = mcp_url

    if auth_type != "none":
        mcp_entry["auth"] = auth_config

    # Show preview
    console.print("\n[bold]Configuration preview:[/bold]")
    yaml_str = yaml.dump(mcp_entry, default_flow_style=False, sort_keys=False)
    console.print(Syntax(yaml_str, "yaml", theme="monokai"))

    # Load existing config
    config_path = Path.cwd() / ".mcp_services.yaml"
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {"default": "local-dev", "profiles": {}}

    profiles = config.get("profiles", {})
    profile_ids = list(profiles.keys())

    if profile_ids:
        target_profile = _choose("Add to profile:", profile_ids, default=profile_ids[0])
    else:
        target_profile = _prompt("Profile ID to create", "local-dev")
        profiles[target_profile] = {
            "name": target_profile,
            "description": "Created by wizard",
            "mcps": [],
        }
        config["profiles"] = profiles
        if "default" not in config:
            config["default"] = target_profile

    # Add MCP to profile
    profile = profiles[target_profile]
    if "mcps" not in profile:
        profile["mcps"] = []
    profile["mcps"].append(mcp_entry)

    # Write config
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    console.print(f"\n[green]MCP server '{name}' added to profile '{target_profile}'![/green]")
    console.print(f"[dim]Config saved to {config_path}[/dim]")


@app.command(name="add-llm")
def add_llm():
    """
    Interactive wizard to add an LLM provider to your configuration.

    Walks you through: provider type, model, API key, test, and save.
    """
    console.print(
        Panel(
            "[bold cyan]Add LLM Provider[/bold cyan]\n"
            "[dim]Follow the prompts to configure a new LLM provider.[/dim]",
            border_style="cyan",
        )
    )

    # Step 1: Provider
    console.print("\n[bold yellow]Step 1: Provider Type[/bold yellow]")
    provider = _choose(
        "Provider:",
        [
            "anthropic",
            "openai",
            "google",
            "ollama",
            "claude-sdk",
            "claude-code",
            "codex-sdk",
            "gemini-sdk",
            "assistant",
        ],
        default="anthropic",
    )

    # Step 2: Model
    console.print("\n[bold yellow]Step 2: Model Selection[/bold yellow]")

    from testmcpy.src.model_registry import get_models_by_provider

    models = get_models_by_provider(provider)
    if models:
        table = Table(title=f"Available {provider} models")
        table.add_column("#", style="dim")
        table.add_column("Model ID", style="cyan")
        table.add_column("Name")
        table.add_column("$/1M in", justify="right")
        table.add_column("$/1M out", justify="right")
        for i, m in enumerate(models, 1):
            default_marker = " *" if m.is_default else ""
            table.add_row(
                str(i),
                m.id,
                f"{m.name}{default_marker}",
                f"${m.input_price_per_1m:.2f}",
                f"${m.output_price_per_1m:.2f}",
            )
        console.print(table)

        raw = Prompt.ask("[bold]Model (number or ID)[/bold]", default="1")
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(models):
                model_id = models[idx].id
                model_name = models[idx].name
            else:
                model_id = raw
                model_name = raw
        except ValueError:
            model_id = raw
            model_name = raw
    else:
        model_id = _prompt("Model ID")
        model_name = model_id

    display_name = _prompt("Display name", model_name)

    # Step 3: API Key
    console.print("\n[bold yellow]Step 3: Credentials[/bold yellow]")

    api_key = ""
    api_key_env = ""
    base_url = ""
    assistant_config: dict[str, str] = {}

    if provider in ("claude-sdk", "claude-code"):
        console.print("[green]No API key needed - uses Claude Code authentication.[/green]")
    elif provider == "ollama":
        console.print("[green]No API key needed - Ollama runs locally.[/green]")
    elif provider == "assistant":
        console.print("Enter the Preset workspace and JWT authentication settings.")
        assistant_config = {
            "workspace_hash": _prompt("Workspace hash"),
            "domain": _prompt("Domain"),
            "api_url": _prompt("Auth API URL"),
            "api_token": _prompt("API token", password=True),
            "api_secret": _prompt("API secret", password=True),
            "conversations_path": _prompt("Conversations path", "/api/v1/copilot/conversations"),
            "completions_path": _prompt("Completions path", "/api/v1/copilot/completions"),
        }
        missing = [field for field, value in assistant_config.items() if not value.strip()]
        if missing:
            console.print("[red]Assistant configuration requires: " + ", ".join(missing) + "[/red]")
            raise typer.Abort()
        parsed_api_url = urlsplit(assistant_config["api_url"])
        if parsed_api_url.scheme not in {"http", "https"} or not parsed_api_url.netloc:
            console.print("[red]Auth API URL must be an absolute HTTP(S) URL[/red]")
            raise typer.Abort()
        from testmcpy.llm_profiles import validate_assistant_endpoint_path

        try:
            for field in ("conversations_path", "completions_path"):
                validate_assistant_endpoint_path(assistant_config[field], field)
        except ValueError as error:
            console.print(f"[red]{error}[/red]")
            raise typer.Abort()
    else:
        if provider == "codex-sdk":
            console.print(
                "[yellow]Codex requires an OpenAI API key; an OAuth-only Codex login "
                "cannot authenticate the Agents SDK.[/yellow]"
            )
        elif provider == "gemini-sdk":
            console.print(
                "[green]Requires a Google API key — get one at https://aistudio.google.com[/green]"
            )
        else:
            console.print("Enter API key directly or specify an environment variable name.")
        api_key = _prompt("API key (leave empty to use env var)", password=True)
        if not api_key:
            default_env = {
                "anthropic": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
                "codex-sdk": "OPENAI_API_KEY",
                "google": "GOOGLE_API_KEY",
                "gemini-sdk": "GOOGLE_API_KEY",
            }.get(provider, "")
            api_key_env = _prompt("Environment variable name", default_env)

    if provider == "ollama":
        base_url = _prompt("Base URL", "http://localhost:11434")

    timeout = IntPrompt.ask("[bold]Timeout (seconds)[/bold]", default=60)
    is_default = Confirm.ask("Set as default provider?", default=True)

    # Step 4: Test
    console.print("\n[bold yellow]Step 4: Test[/bold yellow]")
    if Confirm.ask("Test credentials now?", default=True):
        console.print("[dim]Sending test prompt...[/dim]")
        try:
            from testmcpy.llm_testing import test_llm_provider_connection

            test_kwargs: dict[str, Any] = {
                "provider": provider,
                "model": model_id,
                "api_key": api_key or None,
                "api_key_env": api_key_env or None,
                "base_url": base_url or None,
                "timeout": timeout,
            }
            if provider == "assistant":
                test_kwargs.update(assistant_config)
            result = asyncio.run(test_llm_provider_connection(**test_kwargs))
            if result.get("success"):
                console.print(f"[green]Test passed! ({result.get('duration', 0):.2f}s)[/green]")
            else:
                error = str(result.get("error", "Unknown error"))
                for secret in (
                    api_key,
                    assistant_config.get("api_token"),
                    assistant_config.get("api_secret"),
                ):
                    if secret:
                        error = error.replace(secret, "***")
                if result.get("tested") is False:
                    console.print(f"[yellow]Test skipped: {error}[/yellow]")
                else:
                    console.print(f"[red]Test failed: {error}[/red]")
        except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as e:
            error = str(e)
            for secret in (
                api_key,
                assistant_config.get("api_token"),
                assistant_config.get("api_secret"),
            ):
                if secret:
                    error = error.replace(secret, "***")
            console.print(f"[yellow]Could not test: {error}[/yellow]")

    # Step 5: Save
    console.print("\n[bold yellow]Step 5: Save[/bold yellow]")

    provider_entry: dict[str, Any] = {
        "name": display_name,
        "provider": provider,
        "model": model_id,
        "timeout": timeout,
        "default": is_default,
    }
    if api_key:
        provider_entry["api_key"] = api_key
    if api_key_env:
        provider_entry["api_key_env"] = api_key_env
    if base_url:
        provider_entry["base_url"] = base_url
    provider_entry.update(assistant_config)

    # The entered key is saved but never rendered back to the terminal.
    console.print("\n[bold]Configuration preview:[/bold]")
    yaml_str = yaml.dump(
        _redacted_provider_preview(provider_entry),
        default_flow_style=False,
        sort_keys=False,
    )
    console.print(Syntax(yaml_str, "yaml", theme="monokai"))

    from testmcpy.llm_profiles import (
        LLM_PROFILE_ID_MAX_LENGTH,
        LLM_PROFILE_ID_PATTERN,
        LLMProfile,
        LLMProfileConfig,
        LLMProviderConfig,
    )

    profile_config = LLMProfileConfig()
    if profile_config.load_error:
        console.print(
            f"[red]Cannot update invalid .llm_providers.yaml:[/red] {profile_config.load_error}"
        )
        raise typer.Exit(code=1)
    profile_ids = profile_config.list_profiles()

    if profile_ids:
        resolved_default = profile_config.get_profile()
        default_profile = resolved_default.profile_id if resolved_default else profile_ids[0]
        target_profile = _choose(
            "Add to profile:",
            [*profile_ids, _CREATE_LLM_PROFILE_CHOICE],
            default=default_profile,
        )
    else:
        target_profile = _CREATE_LLM_PROFILE_CHOICE

    if target_profile == _CREATE_LLM_PROFILE_CHOICE:
        target_profile = _prompt("Profile ID to create", "prod")
        if len(target_profile) > LLM_PROFILE_ID_MAX_LENGTH or not re.fullmatch(
            LLM_PROFILE_ID_PATTERN,
            target_profile,
        ):
            console.print(
                "[red]Invalid profile ID - start with a letter or number and use at most "
                "64 letters, numbers, dots, underscores, tildes, or hyphens[/red]"
            )
            raise typer.Abort()
        if target_profile in profile_config.profiles:
            console.print(f"[red]Profile '{target_profile}' already exists.[/red]")
            raise typer.Abort()
        profile_config.add_profile(
            LLMProfile(
                profile_id=target_profile,
                name=target_profile.replace("-", " ").title(),
                description="Created by wizard",
            )
        )

    if profile_config.get_profile() is None:
        profile_config.default_profile_id = target_profile

    profile = profile_config.profiles[target_profile]
    if is_default:
        for configured_provider in profile.providers:
            configured_provider.default = False
    profile.providers.append(LLMProviderConfig(**provider_entry))
    profile_config.save()  # type: ignore[no-untyped-call]

    console.print(
        f"\n[green]LLM provider '{display_name}' added to profile '{target_profile}'![/green]"
    )
    console.print(Text(f"Config saved to {profile_config.source_path}", style="dim"))


@app.command(name="llm-profiles")
def llm_profiles(
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        "-p",
        help="Show one LLM profile instead of all profiles",
    ),
):
    """List configured LLM profiles and masked credential status."""
    from testmcpy.llm_profiles import LLMProfileConfig

    profile_config = LLMProfileConfig()
    if profile_config.load_error:
        console.print(f"[red]Invalid .llm_providers.yaml:[/red] {profile_config.load_error}")
        raise typer.Exit(code=1)
    if profile:
        selected = profile_config.get_profile(profile)
        if selected is None:
            console.print(f"[red]LLM profile '{profile}' was not found.[/red]")
            raise typer.Exit(code=1)
        profiles = [(profile, selected)]
    else:
        profiles = [
            (profile_id, profile_config.profiles[profile_id])
            for profile_id in profile_config.list_profiles()
        ]

    if not profiles:
        console.print("[yellow]No LLM profiles configured.[/yellow]")
        console.print(Text(f"Config: {profile_config.source_path}", style="dim"))
        return

    table = Table(title="LLM Profiles", show_lines=True)
    table.add_column("Profile", style="cyan", no_wrap=True)
    table.add_column("Name")
    table.add_column("Provider", overflow="fold")
    table.add_column("Model", overflow="fold")
    table.add_column("Credentials", overflow="fold")
    table.add_column("Default", justify="center")

    resolved_default = profile_config.get_profile()
    default_profile_id = resolved_default.profile_id if resolved_default else None
    for profile_id, configured_profile in profiles:
        profile_default = profile_id == default_profile_id
        if not configured_profile.providers:
            table.add_row(
                Text(profile_id),
                Text(configured_profile.name),
                Text("-"),
                Text("-"),
                Text("not configured"),
                Text("profile" if profile_default else ""),
            )
            continue

        for index, configured_provider in enumerate(configured_profile.providers):
            defaults = []
            if profile_default and index == 0:
                defaults.append("profile")
            if configured_provider.default:
                defaults.append("provider")
            table.add_row(
                Text(profile_id if index == 0 else ""),
                Text(configured_profile.name if index == 0 else ""),
                Text(configured_provider.provider),
                Text(configured_provider.model),
                Text(_credential_status(configured_provider)),
                Text(", ".join(defaults)),
            )

    console.print(table)
    console.print(Text(f"Config: {profile_config.source_path}", style="dim"))


@app.command(name="add-test")
def add_test():
    """
    Interactive wizard to create a test case YAML file.

    Walks you through: file name, prompts, evaluators, and YAML preview.
    """
    console.print(
        Panel(
            "[bold cyan]Create Test Case[/bold cyan]\n"
            "[dim]Follow the prompts to create a new test YAML file.[/dim]",
            border_style="cyan",
        )
    )

    # Step 1: File name
    console.print("\n[bold yellow]Step 1: Test File[/bold yellow]")
    filename = _prompt("Test file name", "my_tests.yaml")
    if not filename.endswith(".yaml"):
        filename += ".yaml"
    # Sanitize filename: allow only alphanumeric, underscores, hyphens, dots
    if not re.match(r"^[a-zA-Z0-9._-]+$", filename):
        console.print(
            "[red]Invalid filename - only alphanumeric, underscores, hyphens, and dots allowed[/red]"
        )
        raise typer.Abort()

    # Step 2: Write tests
    console.print("\n[bold yellow]Step 2: Define Tests[/bold yellow]")

    evaluator_names = [
        "execution_successful",
        "was_mcp_tool_called",
        "final_answer_contains",
        "tool_called_with_params",
        "tool_call_count",
        "within_time_limit",
        "answer_contains_link",
        "sql_query_valid",
        "token_usage_reasonable",
    ]

    tests = []
    while True:
        console.print(f"\n[bold]Test #{len(tests) + 1}[/bold]")
        test_name = _prompt("Test name (empty to stop)")
        if not test_name:
            if not tests:
                console.print("[red]At least one test is required.[/red]")
                continue
            break

        prompt_text = _prompt("Prompt for the LLM")

        # Evaluators
        evaluators: list[dict] = []
        console.print("[dim]Add evaluators (empty name to stop):[/dim]")
        while True:
            ev_name = _choose(
                "Evaluator:",
                evaluator_names + ["(done)"],
                default="execution_successful",
            )
            if ev_name == "(done)":
                break

            ev_entry: dict = {"name": ev_name}

            # Prompt for args based on evaluator type
            if ev_name == "was_mcp_tool_called":
                tool = _prompt("Tool name")
                ev_entry["args"] = {"tool_name": tool}
            elif ev_name == "final_answer_contains":
                text = _prompt("Expected text")
                ev_entry["args"] = {"text": text}
            elif ev_name == "tool_called_with_params":
                tool = _prompt("Tool name")
                params_str = _prompt('Parameters (JSON, e.g., {"key": "value"})')
                ev_entry["args"] = {"tool_name": tool, "params": params_str}
            elif ev_name == "tool_call_count":
                tool = _prompt("Tool name")
                count = IntPrompt.ask("Expected count", default=1)
                ev_entry["args"] = {"tool_name": tool, "count": count}
            elif ev_name == "within_time_limit":
                seconds = IntPrompt.ask("Time limit (seconds)", default=30)
                ev_entry["args"] = {"seconds": seconds}
            elif ev_name == "token_usage_reasonable":
                max_tokens = IntPrompt.ask("Max tokens", default=10000)
                ev_entry["args"] = {"max_tokens": max_tokens}

            evaluators.append(ev_entry)

        if not evaluators:
            evaluators = [{"name": "execution_successful"}]

        tests.append({"name": test_name, "prompt": prompt_text, "evaluators": evaluators})

        if not Confirm.ask("Add another test?", default=False):
            break

    # Step 3: Preview & Save
    console.print("\n[bold yellow]Step 3: Preview & Save[/bold yellow]")

    yaml_data: dict = {"version": "1.0", "tests": tests}
    yaml_str = yaml.dump(yaml_data, default_flow_style=False, sort_keys=False)

    console.print("\n[bold]Generated YAML:[/bold]")
    console.print(Syntax(yaml_str, "yaml", theme="monokai"))

    # Determine test file path
    tests_dir = Path.cwd() / "tests"
    if not tests_dir.exists():
        tests_dir.mkdir(parents=True, exist_ok=True)

    file_path = (tests_dir / filename).resolve()
    if not file_path.is_relative_to(tests_dir.resolve()):
        console.print("[red]Invalid filename - must be within tests directory[/red]")
        raise typer.Abort()

    if file_path.exists():
        if not Confirm.ask(
            f"[yellow]{file_path} already exists. Overwrite?[/yellow]", default=False
        ):
            console.print("[dim]Aborted.[/dim]")
            raise typer.Abort()

    with open(file_path, "w") as f:
        f.write(yaml_str)

    console.print(f"\n[green]Test file created: {file_path}[/green]")
    console.print(f"[dim]Run with: testmcpy run --test {file_path}[/dim]")
