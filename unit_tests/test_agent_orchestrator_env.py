"""
Regression tests for the Test Execution Agent's SDK subprocess env.

Under root (Docker), the Claude CLI refuses --dangerously-skip-permissions
(driven by permission_mode="bypassPermissions") unless IS_SANDBOX=1 is set.
The orchestrator must always set it, and inject a UI/profile auth token when
one is provided.
"""

import pytest

pytest.importorskip("claude_agent_sdk")

from testmcpy.agent.models import AgentSession  # noqa: E402
from testmcpy.agent.orchestrator import TestExecutionAgent  # noqa: E402


def _agent(cli_token=None):
    """Build a TestExecutionAgent without running its __init__ side effects."""
    agent = TestExecutionAgent.__new__(TestExecutionAgent)
    agent.mcp_profile = None
    agent.mcp_url = None
    agent.auth_config = None
    agent.models = []
    agent.storage_path = None
    agent.max_turns = 5
    agent.agent_model = None
    agent.cli_token = cli_token
    return agent


def test_env_sets_is_sandbox_without_token():
    options = _agent(cli_token=None)._build_options(AgentSession())
    assert options.env is not None
    assert options.env["IS_SANDBOX"] == "1"
    # CLAUDE_CODE* vars are stripped so a nested CLI can spawn.
    assert not any(k.startswith("CLAUDE_CODE") for k in options.env)


def test_env_injects_subscription_token():
    options = _agent(cli_token="sk-ant-oat-abc")._build_options(AgentSession())
    assert options.env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat-abc"
    assert "ANTHROPIC_API_KEY" not in options.env
    assert options.env["IS_SANDBOX"] == "1"


def test_env_injects_api_key_token():
    options = _agent(cli_token="sk-ant-api-xyz")._build_options(AgentSession())
    assert options.env["ANTHROPIC_API_KEY"] == "sk-ant-api-xyz"
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in options.env
    assert options.env["IS_SANDBOX"] == "1"
