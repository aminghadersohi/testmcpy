"""CLI integration test fixtures."""

import pytest
from typer.testing import CliRunner


@pytest.fixture
def runner():
    """Create a Typer CLI test runner.

    NO_COLOR/TERM disable rich's ANSI styling — rich force-enables color
    when it detects GitHub Actions, and the escape codes split option names
    (e.g. '--mcp-url') so plain substring assertions fail in CI.
    """
    return CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "GITHUB_ACTIONS": ""})


@pytest.fixture
def cli_app():
    """Import and return the testmcpy CLI app."""
    from testmcpy.cli import app

    return app
