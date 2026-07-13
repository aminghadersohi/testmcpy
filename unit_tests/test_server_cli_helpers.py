"""Tests for local web-server startup helpers."""

import os

import pytest
from typer.testing import CliRunner

from testmcpy.cli.commands.server import (
    _configure_serve_allowed_hosts,
    _frontend_needs_build,
    _normalize_allowed_host,
)


def test_allowed_host_cli_help_explains_remote_deployment():
    from testmcpy.cli import app

    result = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"}).invoke(app, ["serve", "--help"])

    assert result.exit_code == 0
    assert "--allowed-host" in result.stdout
    assert "reverse proxy" in result.stdout


def test_allowed_host_option_extends_secure_loopback_defaults(monkeypatch):
    monkeypatch.delenv("TESTMCPY_ALLOWED_HOSTS", raising=False)

    effective, source = _configure_serve_allowed_hosts(
        "0.0.0.0", ["App.Example.COM.", "*.workers.example.com"]
    )

    assert effective == (
        "127.0.0.1",
        "localhost",
        "::1",
        "testserver",
        "app.example.com",
        "*.workers.example.com",
    )
    assert source == "secure loopback defaults + --allowed-host"
    assert os.environ["TESTMCPY_ALLOWED_HOSTS"] == ",".join(effective)


def test_concrete_bind_host_is_allowed_when_policy_is_implicit(monkeypatch):
    monkeypatch.delenv("TESTMCPY_ALLOWED_HOSTS", raising=False)

    effective, source = _configure_serve_allowed_hosts("192.0.2.10", None)

    assert "192.0.2.10" in effective
    assert source == "secure loopback defaults"


def test_explicit_environment_policy_is_preserved(monkeypatch):
    monkeypatch.setenv("TESTMCPY_ALLOWED_HOSTS", "proxy.internal, localhost")

    effective, source = _configure_serve_allowed_hosts("0.0.0.0", None)

    assert effective == ("proxy.internal", "localhost")
    assert source == "TESTMCPY_ALLOWED_HOSTS"


@pytest.mark.parametrize(
    "value",
    ["*", "https://app.example.com", "app.example.com:8000", "*.127.0.0.1", "bad host"],
)
def test_allowed_host_rejects_unsafe_or_ambiguous_values(value):
    with pytest.raises(ValueError):
        _normalize_allowed_host(value)


def test_serve_rejects_wildcard_environment_policy(monkeypatch):
    monkeypatch.setenv("TESTMCPY_ALLOWED_HOSTS", "*")

    with pytest.raises(ValueError, match="DNS-rebinding protection"):
        _configure_serve_allowed_hosts("0.0.0.0", None)


def test_frontend_build_required_when_bundle_missing(tmp_path):
    ui_dir = tmp_path / "ui"
    (ui_dir / "src").mkdir(parents=True)

    assert _frontend_needs_build(ui_dir, ui_dir / "dist") is True


def test_frontend_build_required_when_source_is_newer(tmp_path):
    ui_dir = tmp_path / "ui"
    source = ui_dir / "src" / "App.jsx"
    built = ui_dir / "dist" / "index.html"
    source.parent.mkdir(parents=True)
    built.parent.mkdir()
    source.write_text("source")
    built.write_text("bundle")
    os.utime(built, ns=(1_000_000_000, 1_000_000_000))
    os.utime(source, ns=(2_000_000_000, 2_000_000_000))

    assert _frontend_needs_build(ui_dir, ui_dir / "dist") is True


def test_frontend_build_required_when_index_references_missing_chunk(tmp_path):
    ui_dir = tmp_path / "ui"
    built = ui_dir / "dist" / "index.html"
    built.parent.mkdir(parents=True)
    built.write_text('<script type="module" src="/assets/index-missing.js"></script>')

    assert _frontend_needs_build(ui_dir, ui_dir / "dist") is True


def test_frontend_build_not_required_when_bundle_is_current(tmp_path):
    ui_dir = tmp_path / "ui"
    source = ui_dir / "src" / "App.jsx"
    built = ui_dir / "dist" / "index.html"
    source.parent.mkdir(parents=True)
    built.parent.mkdir()
    source.write_text("source")
    built.write_text("bundle")
    os.utime(source, ns=(1_000_000_000, 1_000_000_000))
    os.utime(built, ns=(2_000_000_000, 2_000_000_000))

    assert _frontend_needs_build(ui_dir, ui_dir / "dist") is False
