"""Regression tests for using LLM profiles with the Claude execution agent."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner


def _write_profile(
    provider: str,
    *,
    api_key: str | None = None,
    api_key_env: str | None = None,
) -> None:
    credential = f"        api_key: {api_key}\n" if api_key is not None else ""
    env_binding = f"        api_key_env: {api_key_env}\n" if api_key_env is not None else ""
    Path(".llm_providers.yaml").write_text(
        "default: prod\n"
        "profiles:\n"
        "  prod:\n"
        "    name: Production\n"
        "    description: Test\n"
        "    providers:\n"
        "      - name: Agent provider\n"
        f"        provider: {provider}\n"
        "        model: agent-model\n"
        f"{credential}"
        f"{env_binding}"
        "        default: true\n"
    )


def test_server_rejects_missing_explicit_profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from testmcpy.server.routers.agent import _resolve_cli_token

    with pytest.raises(ValueError, match="was not found"):
        _resolve_cli_token("missing")


def test_server_reports_malformed_profile_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".llm_providers.yaml").write_text("profiles:\n  prod:\n    providers:\n      - null\n")
    from testmcpy.server.routers.agent import _resolve_cli_token

    with pytest.raises(RuntimeError, match="Invalid LLM profile configuration"):
        _resolve_cli_token("prod")


def test_server_rejects_non_claude_profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_profile("openai", api_key="openai-secret")
    from testmcpy.server.routers.agent import _resolve_cli_token

    with pytest.raises(ValueError, match="no Claude SDK provider"):
        _resolve_cli_token("prod")


def test_server_resolves_claude_profile_token(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_profile("claude-sdk", api_key="sk-ant-oat-test")
    from testmcpy.server.routers.agent import _resolve_cli_token

    assert _resolve_cli_token("prod") == "sk-ant-oat-test"


def test_server_rejects_configured_unset_claude_token(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MISSING_CLAUDE_AGENT_TOKEN", raising=False)
    _write_profile("claude-sdk", api_key_env="MISSING_CLAUDE_AGENT_TOKEN")
    from testmcpy.llm_profiles import LLMProfileConfigError
    from testmcpy.server.routers.agent import _resolve_cli_token

    with pytest.raises(LLMProfileConfigError, match="configured API key.*empty value"):
        _resolve_cli_token("prod")


def test_server_keyless_claude_profile_uses_host_login(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_profile("claude-sdk")
    from testmcpy.server.routers.agent import _resolve_cli_token

    assert _resolve_cli_token("prod") is None


def test_server_registers_resolved_profile_token(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    secret = "literal-agent-profile-credential"
    _write_profile("claude-sdk", api_key=secret)
    from testmcpy.scrubber import REDACTED, reset_cache, scrub_text
    from testmcpy.server.routers.agent import _resolve_cli_token

    reset_cache()
    try:
        assert _resolve_cli_token("prod") == secret
        assert scrub_text(f"upstream echoed {secret}") == f"upstream echoed {REDACTED}"
    finally:
        reset_cache()


def test_cli_rejects_incompatible_profile_before_starting_agent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_profile("openai", api_key="openai-secret")
    from testmcpy.cli import app

    result = CliRunner().invoke(app, ["agent", "run tests", "--llm-profile", "prod"])

    assert result.exit_code == 1
    assert "has no Claude SDK provider" in result.output
    assert "openai-secret" not in result.output


def test_cli_reports_malformed_profile_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".llm_providers.yaml").write_text("profiles:\n  prod:\n    providers:\n      - null\n")
    from testmcpy.cli import app

    result = CliRunner().invoke(app, ["agent", "run tests", "--llm-profile", "prod"])

    assert result.exit_code == 1
    assert "Invalid LLM profile configuration" in result.output
    assert "was not found" not in result.output


def test_cli_rejects_configured_unset_claude_token_before_starting_agent(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MISSING_CLAUDE_AGENT_TOKEN", raising=False)
    _write_profile("claude-sdk", api_key_env="MISSING_CLAUDE_AGENT_TOKEN")
    from testmcpy.cli import app

    result = CliRunner().invoke(app, ["agent", "run tests", "--llm-profile", "prod"])

    assert result.exit_code == 1
    assert "configured API key that resolved to an empty value" in " ".join(result.output.split())
    assert "Test Execution Agent" not in result.output


def test_cli_keyless_claude_profile_uses_host_login(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_profile("claude-sdk")
    from testmcpy.agent import orchestrator
    from testmcpy.cli import app
    from testmcpy.cli.commands import agent as agent_command

    captured = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run(self, _prompt):
            return object()

    monkeypatch.setattr(orchestrator, "TestExecutionAgent", FakeAgent)
    monkeypatch.setattr(agent_command, "_display_report", lambda *_args, **_kwargs: None)

    result = CliRunner().invoke(app, ["agent", "run tests", "--llm-profile", "prod"])

    assert result.exit_code == 0
    assert captured["cli_token"] is None


def test_cli_token_is_scrubbed_from_persisted_agent_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    secret = "literal-cli-agent-credential"
    output = tmp_path / "agent-report.json"
    from testmcpy.agent import orchestrator
    from testmcpy.cli import app
    from testmcpy.cli.commands import agent as agent_command
    from testmcpy.scrubber import REDACTED, reset_cache

    captured = {}

    class FakeReport:
        def to_dict(self):
            return {"analysis": f"upstream echoed {secret}"}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run(self, _prompt):
            return FakeReport()

    monkeypatch.setattr(orchestrator, "TestExecutionAgent", FakeAgent)
    monkeypatch.setattr(agent_command, "_display_report", lambda *_args, **_kwargs: None)

    reset_cache()
    try:
        result = CliRunner().invoke(
            app,
            [
                "agent",
                "run tests",
                "--cli-token",
                secret,
                "--output",
                str(output),
            ],
        )

        assert result.exit_code == 0
        assert captured["cli_token"] == secret
        saved = json.loads(output.read_text())
        assert secret not in output.read_text()
        assert saved["analysis"] == f"upstream echoed {REDACTED}"
    finally:
        reset_cache()
