"""End-to-end CLI checks for secure LLM profile setup."""

import stat
from pathlib import Path

import yaml


def test_setup_stores_environment_reference_not_detected_secret(
    runner,
    cli_app,
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-from-environment")

    result = runner.invoke(cli_app, ["setup"], input="\n\n\n\n")

    assert result.exit_code == 0, result.output
    config_path = Path(".llm_providers.yaml")
    config = yaml.safe_load(config_path.read_text())
    provider = config["profiles"]["prod"]["providers"][0]
    assert provider["api_key_env"] == "ANTHROPIC_API_KEY"
    assert "api_key" not in provider
    assert "sk-secret-from-environment" not in result.output
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


def test_setup_rejects_invalid_provider_choice(runner, cli_app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli_app, ["setup"], input="9\n")

    assert result.exit_code == 1
    assert "Invalid provider choice" in result.output
    assert not Path(".llm_providers.yaml").exists()


def test_setup_does_not_silently_replace_fallback_config(runner, cli_app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fallback = tmp_path / ".testmcpy" / ".llm_providers.yaml"
    fallback.parent.mkdir()
    original = "profiles:\n  existing:\n    name: Existing\n    providers: []\n"
    fallback.write_text(original)

    result = runner.invoke(cli_app, ["setup"], input="\n")

    assert result.exit_code == 0, result.output
    assert "Setup cancelled" in result.output
    compact_output = "".join(line.strip() for line in result.output.splitlines())
    assert ".testmcpy/.llm_providers.yaml" in compact_output
    assert fallback.read_text() == original
