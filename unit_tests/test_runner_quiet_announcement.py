"""
Unit tests for TestRunner.quiet_test_announcement.

The streaming WebSocket already emits its own per-test announcement block
("🧪 Running test 1/N: name", "📝 Prompt: …", "⏱️ Timeout: …s") before
calling runner.run_test. Without this flag, the runner would ALSO emit
"Running test: name" + "Prompt: …" + "Provider: …, Model: …" + (for
non-chatbot providers) "Available tools: N" + "MCP URL: …" — producing a
duplicate group header in the UI's StreamingLogViewer, which parses every
"Running test:" line into its own collapsible group.
"""

import pytest

from testmcpy.src.test_runner import TestCase, TestRunner
from testmcpy.src.llm_integration import LLMResult


class _FakeProvider:
    """Minimal stand-in for an LLM provider. Returns a trivial result so
    runner.run_test doesn't hit the network."""

    async def initialize(self):
        pass

    async def close(self):
        pass

    async def generate_with_tools(self, prompt, tools=None, timeout=30.0, **kwargs):
        return LLMResult(response="ok")


class _FakeMcpClient:
    """No-op MCP client — the test doesn't exercise tool discovery."""

    base_url = "https://example.test/mcp"

    async def initialize(self):
        pass

    async def list_tools(self):
        return []

    async def close(self):
        pass


def _make_runner(*, quiet: bool, provider: str = "claude-sdk") -> tuple[TestRunner, list[str]]:
    captured: list[str] = []

    def callback(msg: str) -> None:
        captured.append(msg)

    runner = TestRunner(
        model="test-model",
        provider=provider,
        mcp_url="https://example.test/mcp",
        verbose=True,
        log_callback=callback,
        quiet_test_announcement=quiet,
    )
    runner.llm_provider = _FakeProvider()  # type: ignore[assignment]
    runner.mcp_client = _FakeMcpClient()  # type: ignore[assignment]
    return runner, captured


def _make_test_case() -> TestCase:
    return TestCase(
        name="test_demo",
        prompt="Find any dataset on this workspace.",
        evaluators=[],
        timeout=10.0,
    )


def test_default_is_loud_for_cli_backward_compat():
    """CLI callers depend on the announcement lines (they don't emit their
    own preamble). The default must remain unchanged."""
    runner, _ = _make_runner(quiet=False)
    assert runner.quiet_test_announcement is False


def test_quiet_flag_stores_on_runner():
    runner, _ = _make_runner(quiet=True)
    assert runner.quiet_test_announcement is True


@pytest.mark.asyncio
async def test_loud_mode_emits_running_test_and_prompt_lines():
    """The CLI (and any other caller without its own preamble) needs the
    duplicate-prone lines, so loud mode must keep emitting them."""
    runner, logs = _make_runner(quiet=False, provider="claude-sdk")
    await runner.run_test(_make_test_case())

    assert any(line == "Running test: test_demo" for line in logs), logs
    assert any(line.startswith("Prompt: ") for line in logs), logs
    assert any(line.startswith("Provider: ") for line in logs), logs
    # claude-sdk path also emits MCP URL + tool count
    assert any(line.startswith("MCP URL:") for line in logs), logs
    assert any(line.startswith("Available tools:") for line in logs), logs


@pytest.mark.asyncio
async def test_quiet_mode_suppresses_all_pre_test_announcement_lines():
    """The websocket emits its own preamble, so the runner must not
    duplicate any of these lines."""
    runner, logs = _make_runner(quiet=True, provider="claude-sdk")
    await runner.run_test(_make_test_case())

    assert not any(line == "Running test: test_demo" for line in logs), logs
    assert not any(line.startswith("Prompt: ") for line in logs), logs
    assert not any(line.startswith("Provider: ") for line in logs), logs
    assert not any(line.startswith("MCP URL:") for line in logs), logs
    assert not any(line.startswith("Available tools:") for line in logs), logs


@pytest.mark.asyncio
async def test_quiet_mode_suppresses_chatbot_announcement_lines_too():
    """The chatbot/assistant variants of those lines must also be silenced
    when the caller owns the preamble."""
    runner, logs = _make_runner(quiet=True, provider="chatbot")
    await runner.run_test(_make_test_case())

    assert not any(line.startswith("Chatbot API:") for line in logs), logs
    assert not any("(Tools provided server-side" in line for line in logs), logs
    assert not any(line.startswith("Provider: ") for line in logs), logs
