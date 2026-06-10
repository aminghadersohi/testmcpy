"""
Integration tests for the LLM provider factory and tool call parsing.

Tests cover:
- Provider factory (create_llm_provider) — instantiation without API calls
- LLMResult dataclass creation and field access
- Evaluator factory (create_evaluator) — instantiation and evaluation
- Tool name matching (_match_tool_name)
- New evaluators: response_not_includes, no_leaked_data, url_is_valid,
  success_rate_above, latency_percentile, response_matches_pattern
"""

from unittest.mock import AsyncMock, patch

import pytest

from testmcpy.evals.base_evaluators import _match_tool_name, create_evaluator
from testmcpy.src.llm_integration import (
    AnthropicProvider,
    AssistantProvider,
    ClaudeSDKProvider,
    CodexSDKProvider,
    LLMResult,
    OpenAIProvider,
    OpenRouterProvider,
    _SSEStreamState,
    create_llm_provider,
)

# ---------------------------------------------------------------------------
# Provider Factory Tests
# ---------------------------------------------------------------------------


class TestProviderFactory:
    def test_create_anthropic_provider(self):
        provider = create_llm_provider("anthropic", "claude-haiku-4-5", api_key="test")
        assert isinstance(provider, AnthropicProvider)

    def test_create_openai_provider(self):
        provider = create_llm_provider("openai", "gpt-4o", api_key="test")
        assert isinstance(provider, OpenAIProvider)

    def test_create_assistant_provider(self):
        provider = create_llm_provider(
            "assistant",
            "default",
            workspace_hash="test",
            domain="test.com",
            conversations_path="/api/v1/copilot/conversations",
            completions_path="/api/v1/copilot/completions",
        )
        assert isinstance(provider, AssistantProvider)

    def test_create_openrouter_provider(self):
        provider = create_llm_provider("openrouter", "anthropic/claude-haiku-4-5", api_key="test")
        assert isinstance(provider, OpenRouterProvider)

    def test_create_unknown_provider_raises(self):
        with pytest.raises(ValueError):
            create_llm_provider("nonexistent", "model")

    def test_provider_aliases(self):
        # claude-cli, claude-code should map to ClaudeSDKProvider
        p1 = create_llm_provider("claude-cli", "claude-sonnet-4-20250514")
        p2 = create_llm_provider("claude-code", "claude-sonnet-4-20250514")
        assert type(p1).__name__ == "ClaudeSDKProvider"
        assert type(p2).__name__ == "ClaudeSDKProvider"


# ---------------------------------------------------------------------------
# ClaudeSDKProvider OAuth Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_claude_sdk_module(monkeypatch):
    """Stub claude_agent_sdk so .initialize() doesn't require the real package."""
    import sys
    import types

    # Provide just enough surface for ClaudeSDKProvider.initialize().
    fake_pkg = types.ModuleType("claude_agent_sdk")
    fake_pkg.CLINotFoundError = type("CLINotFoundError", (Exception,), {})
    fake_types = types.ModuleType("claude_agent_sdk.types")
    fake_types.McpHttpServerConfig = dict  # used as a type alias only
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_pkg)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk.types", fake_types)
    return fake_pkg


class TestClaudeSDKProviderOAuth:
    """Cover the OAuth branches in ClaudeSDKProvider.initialize().

    These exist because the SDK's MCP transport will silently fall back to
    its own claude.ai/oauth flow if no Authorization header is set, which
    masks misconfiguration. The provider must either supply a Bearer token
    or fail loudly.
    """

    @pytest.mark.asyncio
    async def test_oauth_auto_discover_uses_cached_token(self, fake_claude_sdk_module):
        """When oauth_auto_discover is set, the cached fastmcp token is used as Bearer."""
        provider = ClaudeSDKProvider(
            model="claude-sonnet-4-5",
            mcp_url="https://mcp.example.com/mcp",
            auth={"type": "oauth", "oauth_auto_discover": True},
        )
        with patch.object(
            ClaudeSDKProvider,
            "_read_cached_oauth_token",
            new=AsyncMock(return_value="cached-access-token-abc"),
        ) as read_cached:
            await provider.initialize()
            read_cached.assert_awaited_once()
        headers = provider._mcp_server_config.get("headers", {})
        assert headers.get("Authorization") == "Bearer cached-access-token-abc"

    @pytest.mark.asyncio
    async def test_oauth_auto_discover_missing_token_fails_fast(self, fake_claude_sdk_module):
        """No cached token must raise so the SDK can't bounce to claude.ai/oauth."""
        provider = ClaudeSDKProvider(
            model="claude-sonnet-4-5",
            mcp_url="https://mcp.example.com/mcp",
            auth={"type": "oauth", "oauth_auto_discover": True},
        )
        with patch.object(
            ClaudeSDKProvider, "_read_cached_oauth_token", new=AsyncMock(return_value=None)
        ):
            with pytest.raises(ValueError, match="No usable cached OAuth token"):
                await provider.initialize()

    @pytest.mark.asyncio
    async def test_oauth_client_credentials_path_unchanged(self, fake_claude_sdk_module):
        """Profiles without oauth_auto_discover still use the client_credentials grant."""
        provider = ClaudeSDKProvider(
            model="claude-sonnet-4-5",
            mcp_url="https://mcp.example.com/mcp",
            auth={
                "type": "oauth",
                "client_id": "id",
                "client_secret": "secret",
                "token_url": "https://auth.example.com/token",
            },
        )
        with (
            patch.object(
                ClaudeSDKProvider,
                "_fetch_oauth_token",
                new=AsyncMock(return_value="cc-token-xyz"),
            ) as fetch_cc,
            patch.object(
                ClaudeSDKProvider, "_read_cached_oauth_token", new=AsyncMock()
            ) as read_cached,
        ):
            await provider.initialize()
            fetch_cc.assert_awaited_once()
            read_cached.assert_not_awaited()
        headers = provider._mcp_server_config.get("headers", {})
        assert headers.get("Authorization") == "Bearer cc-token-xyz"


# ---------------------------------------------------------------------------
# ClaudeSDK verbose log format tests
# ---------------------------------------------------------------------------


class TestClaudeSDKVerboseLogs:
    """Assert that the new log-suppression and thinking-preview logic works."""

    @pytest.mark.asyncio
    async def test_assistant_message_header_suppressed(self, monkeypatch):
        """Message #N: AssistantMessage must NOT appear in logs (content lines replace it)."""
        import sys
        import types

        # Build minimal fake claude_agent_sdk with the types the code imports.
        fake_pkg = types.ModuleType("claude_agent_sdk")
        fake_types_mod = types.ModuleType("claude_agent_sdk.types")

        # Name classes without underscores so type().__name__ matches what the
        # production code logs (e.g. "AssistantMessage", not "_AssistantMessage").
        TextBlock = type(
            "TextBlock", (), {"__init__": lambda s, text: setattr(s, "text", text) or None}
        )
        ThinkingBlock = type(
            "ThinkingBlock", (), {"__init__": lambda s, t: setattr(s, "thinking", t) or None}
        )
        AssistantMessage = type(
            "AssistantMessage", (), {"__init__": lambda s, c: setattr(s, "content", c) or None}
        )
        UserMessage = type("UserMessage", (), {})
        SystemMessage = type(
            "SystemMessage",
            (),
            {
                "__init__": lambda s: (
                    (setattr(s, "subtype", "info"), setattr(s, "data", {})) and None
                )
            },
        )

        rl_info = type("RLInfo", (), {"status": "allowed", "utilization": None})()
        RateLimitEvent = type(
            "RateLimitEvent",
            (),
            {"__init__": lambda s: setattr(s, "rate_limit_info", rl_info) or None},
        )
        ResultMessage = type(
            "ResultMessage",
            (),
            {
                "__init__": lambda s: (
                    (
                        setattr(s, "usage", {}),
                        setattr(s, "total_cost_usd", 0.001),
                        setattr(s, "duration_ms", 100),
                        setattr(s, "num_turns", 1),
                    )
                    and None
                )
            },
        )
        ToolResultBlock = type("ToolResultBlock", (), {})

        # Populate fake package
        for name, cls in [
            ("AssistantMessage", AssistantMessage),
            ("UserMessage", UserMessage),
            ("SystemMessage", SystemMessage),
            ("RateLimitEvent", RateLimitEvent),
            ("ResultMessage", ResultMessage),
            ("TextBlock", TextBlock),
            ("ThinkingBlock", ThinkingBlock),
            ("ToolUseBlock", type("ToolUseBlock", (), {})),
            ("ClaudeAgentOptions", dict),
            ("ClaudeSDKError", Exception),
            ("CLIConnectionError", Exception),
            ("CLINotFoundError", Exception),
            ("ProcessError", Exception),
        ]:
            setattr(fake_pkg, name, cls)

        fake_types_mod.ToolResultBlock = ToolResultBlock

        # 120-char thinking string so truncation fires and ellipsis appears
        long_thinking = 'I need to call "get_dashboard_info" to answer this. ' * 3

        async def fake_query(prompt, options):
            yield AssistantMessage(
                [
                    TextBlock("I'll look into that."),
                    ThinkingBlock(long_thinking),
                ]
            )
            yield RateLimitEvent()
            yield ResultMessage()

        fake_pkg.query = fake_query

        monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_pkg)
        monkeypatch.setitem(sys.modules, "claude_agent_sdk.types", fake_types_mod)

        provider = ClaudeSDKProvider(model="claude-sonnet-4-5")
        provider._initialized = True
        provider._mcp_server_config = {}
        provider.verbose = True

        result = await provider.generate_with_tools("Hello", tools=[])

        log_text = "\n".join(result.logs)

        # Generic class-name headers must be suppressed for content-bearing types
        assert "Message #1: AssistantMessage" not in log_text
        assert "Message #1: UserMessage" not in log_text

        # RateLimitEvent MUST keep its header (no dedicated content line)
        assert "Message #2: RateLimitEvent" in log_text

        # ResultMessage MUST keep its header
        assert "Message #3: ResultMessage" in log_text

        # Text content line must be present
        assert "[ClaudeSDK] Text:" in log_text

        # Thinking preview must appear with repr() and ellipsis
        assert "[ClaudeSDK] Thinking:" in log_text
        assert "chars)" in log_text
        # The preview should use repr() — so quotes are present
        thinking_lines = [line for line in result.logs if "Thinking:" in line]
        assert len(thinking_lines) == 1
        assert "..." in thinking_lines[0]  # ellipsis because text > 100 chars


# ---------------------------------------------------------------------------
# CodexSDKProvider Tests
# ---------------------------------------------------------------------------


class TestCodexSDKProvider:
    """Cover CodexSDKProvider construction, auth resolution, and factory aliases."""

    def test_factory_alias_codex_sdk(self) -> None:
        p = create_llm_provider("codex-sdk", "codex-o3", openai_api_key="sk-test")
        assert isinstance(p, CodexSDKProvider)

    def test_factory_alias_codex_cli(self) -> None:
        p = create_llm_provider("codex-cli", "codex-o3", openai_api_key="sk-test")
        assert isinstance(p, CodexSDKProvider)

    def test_factory_alias_codex(self) -> None:
        p = create_llm_provider("codex", "codex-o3", openai_api_key="sk-test")
        assert isinstance(p, CodexSDKProvider)

    def test_model_id_remapped(self) -> None:
        p = CodexSDKProvider(model="codex-o3", openai_api_key="sk-test")
        assert p.model == "o3"

    def test_model_id_remapped_o4mini(self) -> None:
        p = CodexSDKProvider(model="codex-o4-mini", openai_api_key="sk-test")
        assert p.model == "o4-mini"

    def test_model_id_passthrough_for_unknown(self) -> None:
        # If user passes a raw OpenAI model ID, it is passed through unchanged.
        p = CodexSDKProvider(model="gpt-4o-mini", openai_api_key="sk-test")
        assert p.model == "gpt-4o-mini"

    def test_api_key_from_constructor(self) -> None:
        p = CodexSDKProvider(model="codex-o3", openai_api_key="sk-explicit")
        assert p.openai_api_key == "sk-explicit"

    def test_no_api_key_defaults_empty(self) -> None:
        # Key comes from the LLM profile (resolved in .llm_providers.yaml),
        # not from the environment — constructor with no key yields empty string.
        p = CodexSDKProvider(model="codex-o3")
        assert p.openai_api_key == ""

    def test_read_cached_codex_token_present(self, tmp_path, monkeypatch) -> None:
        auth_file = tmp_path / ".codex" / "auth.json"
        auth_file.parent.mkdir(parents=True)
        # Real Codex CLI schema: OPENAI_API_KEY at top level, OAuth tokens nested
        auth_file.write_text(
            '{"OPENAI_API_KEY": "sk-stored-key", "tokens": {"access_token": "oauth-only"}}'
        )
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        p = CodexSDKProvider(model="codex-o3")
        assert p._read_cached_codex_token() == "sk-stored-key"

    def test_read_cached_codex_token_oauth_only_returns_none(self, tmp_path, monkeypatch) -> None:
        # OAuth-only login: OPENAI_API_KEY is null — ChatGPT token can't hit Platform API
        auth_file = tmp_path / ".codex" / "auth.json"
        auth_file.parent.mkdir(parents=True)
        auth_file.write_text('{"OPENAI_API_KEY": null, "tokens": {"access_token": "chatgpt-tok"}}')
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        p = CodexSDKProvider(model="codex-o3")
        assert p._read_cached_codex_token() is None

    def test_read_cached_codex_token_missing_file(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        p = CodexSDKProvider(model="codex-o3")
        assert p._read_cached_codex_token() is None

    def test_read_cached_codex_token_invalid_json(self, tmp_path, monkeypatch) -> None:
        auth_file = tmp_path / ".codex" / "auth.json"
        auth_file.parent.mkdir(parents=True)
        auth_file.write_text("not-json{{")
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        p = CodexSDKProvider(model="codex-o3")
        assert p._read_cached_codex_token() is None

    @pytest.mark.asyncio
    async def test_initialize_missing_package_raises(self, monkeypatch) -> None:
        import sys

        monkeypatch.setitem(sys.modules, "agents", None)
        p = CodexSDKProvider(model="codex-o3", openai_api_key="sk-test")
        with pytest.raises(ValueError, match="openai-agents"):
            await p.initialize()

    @pytest.mark.asyncio
    async def test_initialize_no_key_raises(self, monkeypatch, tmp_path) -> None:
        """No constructor key and no ~/.codex/auth.json must raise ValueError."""
        import sys
        import types

        fake_agents = types.ModuleType("agents")
        fake_agents.Agent = object
        fake_agents.Runner = object
        monkeypatch.setitem(sys.modules, "agents", fake_agents)
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        p = CodexSDKProvider(model="codex-o3")  # no openai_api_key
        with pytest.raises(ValueError, match="api_key"):
            await p.initialize()

    def test_tool_call_extraction_from_raw_item(self) -> None:
        """tool_calls must be populated from ToolCallItem.raw_item, not .arguments."""
        pytest.importorskip("agents", reason="openai-agents not installed")
        from agents.items import ToolCallItem

        # Build a minimal ToolCallItem with a dict raw_item (the MCP call shape).
        raw = {"name": "list_dashboards", "arguments": '{"page": 1}', "call_id": "c1"}
        item = ToolCallItem(raw_item=raw, agent=None)  # type: ignore[call-arg]

        assert item.tool_name == "list_dashboards"
        # Confirm .arguments does NOT exist (the bug this test guards against).
        assert not hasattr(item, "arguments")
        # Confirm raw_item carries the arguments string.
        assert raw.get("arguments") == '{"page": 1}'

    @pytest.mark.asyncio
    async def test_initialize_bearer_auth_sets_mcp_header(self, monkeypatch) -> None:
        """Bearer auth type must set Authorization header on MCP requests."""
        import sys
        import types

        fake_agents = types.ModuleType("agents")
        fake_agents.Agent = object
        fake_agents.Runner = object
        monkeypatch.setitem(sys.modules, "agents", fake_agents)

        p = CodexSDKProvider(
            model="codex-o3",
            mcp_url="https://mcp.example.com/mcp",
            auth={"type": "bearer", "token": "bearer-tok-789"},
            openai_api_key="sk-test",
        )
        await p.initialize()
        assert p._mcp_headers == {"Authorization": "Bearer bearer-tok-789"}


# ---------------------------------------------------------------------------
# AssistantProvider SSE tool_call parsing tests
# ---------------------------------------------------------------------------


class TestAssistantSSEToolCallParsing:
    """_handle_sse_event must extract tool name/args across backend field variants."""

    def _make_provider(self):
        p = AssistantProvider.__new__(AssistantProvider)
        p.model = "default"
        p.workspace_hash = "testhash"
        p.domain = "example.com"
        p.base_url = "https://testhash.example.com"
        p.completions_path = "/api/v1/copilot/completions"
        return p

    def _run(self, data: dict) -> tuple[str, dict, str]:
        provider = self._make_provider()
        state = _SSEStreamState()
        logs: list[str] = []
        provider._handle_sse_event("tool_call", data, state, logs.append)
        assert len(state.tool_calls) == 1
        tc = state.tool_calls[0]
        return tc["name"], tc["arguments"], tc["id"]

    def test_canonical_fields(self):
        name, args, tid = self._run(
            {"tool_call_id": "id1", "tool_name": "get_info", "input": {"k": "v"}}
        )
        assert name == "get_info"
        assert args == {"k": "v"}
        assert tid == "id1"

    def test_name_field_fallback(self):
        name, args, _ = self._run({"name": "list_dashboards", "arguments": {"page": 1}})
        assert name == "list_dashboards"
        assert args == {"page": 1}

    def test_function_name_field(self):
        name, args, _ = self._run(
            {"function_name": "create_chart", "parameters": {"title": "Sales"}}
        )
        assert name == "create_chart"
        assert args == {"title": "Sales"}

    def test_nested_function_dict(self):
        name, args, _ = self._run(
            {"function": {"name": "health_check", "arguments": {"verbose": True}}}
        )
        assert name == "health_check"
        assert args == {"verbose": True}

    def test_dotted_function_keys(self):
        name, args, _ = self._run(
            {"function.name": "get_schema", "function.arguments": {"model_type": "chart"}}
        )
        assert name == "get_schema"
        assert args == {"model_type": "chart"}

    def test_json_string_arguments_parsed(self):
        """arguments delivered as a JSON string must be parsed into a dict."""
        import json

        name, args, _ = self._run(
            {"name": "run_query", "arguments": json.dumps({"sql": "SELECT 1"})}
        )
        assert name == "run_query"
        assert args == {"sql": "SELECT 1"}

    def test_json_string_function_arguments_parsed(self):
        """function.arguments as JSON string must also be parsed."""
        import json

        name, args, _ = self._run({"function": {"name": "foo", "arguments": json.dumps({"x": 1})}})
        assert name == "foo"
        assert args == {"x": 1}

    def test_non_dict_function_value_ignored(self):
        """If function is not a dict, fall back to other fields."""
        name, args, _ = self._run({"function": "not_a_dict", "name": "fallback_tool"})
        assert name == "fallback_tool"

    def test_id_field_fallback(self):
        name, _, tid = self._run({"id": "alt-id", "tool_name": "my_tool"})
        assert tid == "alt-id"

    def test_verbose_log_contains_name(self):
        provider = self._make_provider()
        state = _SSEStreamState()
        logs: list[str] = []
        provider._handle_sse_event(
            "tool_call", {"tool_name": "list_charts", "input": {}}, state, logs.append
        )
        assert any("list_charts" in line for line in logs)


# ---------------------------------------------------------------------------
# LLMResult Parsing Tests
# ---------------------------------------------------------------------------


class TestLLMResult:
    def test_llm_result_creation(self):
        result = LLMResult(
            response="Hello",
            tool_calls=[{"name": "health_check", "arguments": {}}],
            tool_results=[],
            token_usage={"total": 100},
            cost=0.01,
            duration=1.5,
        )
        assert result.response == "Hello"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "health_check"
        assert result.cost == 0.01
        assert result.duration == 1.5

    def test_llm_result_empty(self):
        result = LLMResult(
            response="",
            tool_calls=[],
            tool_results=[],
            token_usage={},
            cost=0.0,
            duration=0.0,
        )
        assert result.response == ""
        assert result.tool_calls == []
        assert result.tool_results == []


# ---------------------------------------------------------------------------
# Evaluator Factory Tests
# ---------------------------------------------------------------------------


class TestEvaluatorFactory:
    def test_create_all_evaluators(self):
        """Verify all registered evaluators can be instantiated."""
        simple_evaluators = ["execution_successful", "no_leaked_data", "url_is_valid"]
        for name in simple_evaluators:
            eval_instance = create_evaluator(name)
            assert eval_instance.name is not None

    def test_create_evaluator_with_args(self):
        e = create_evaluator("response_includes", content=["hello"])
        assert "response_includes" in e.name

    def test_create_unknown_evaluator_raises(self):
        with pytest.raises(ValueError):
            create_evaluator("nonexistent_evaluator")


# ---------------------------------------------------------------------------
# Tool Name Matching Tests
# ---------------------------------------------------------------------------


class TestToolNameMatching:
    def test_match_tool_name_exact(self):
        assert _match_tool_name("health_check", "health_check")

    def test_match_tool_name_prefix(self):
        assert _match_tool_name("mcp__myserver__health_check", "health_check")

    def test_match_tool_name_no_match(self):
        assert not _match_tool_name("list_charts", "health_check")


# ---------------------------------------------------------------------------
# New Evaluator Tests
# ---------------------------------------------------------------------------


class TestResponseNotIncludes:
    def test_pass(self):
        e = create_evaluator("response_not_includes", content=["error", "failed"])
        result = e.evaluate({"response": "All dashboards loaded successfully"})
        assert result.passed

    def test_fail(self):
        e = create_evaluator("response_not_includes", content=["error"])
        result = e.evaluate({"response": "An error occurred"})
        assert not result.passed


class TestNoLeakedData:
    def test_pass(self):
        e = create_evaluator("no_leaked_data")
        result = e.evaluate({"response": "Here are your dashboards"})
        assert result.passed

    def test_fail_connection_string(self):
        e = create_evaluator("no_leaked_data")
        result = e.evaluate({"response": "Error connecting to postgresql://user:pass@host/db"})
        assert not result.passed


class TestUrlIsValid:
    def test_pass(self):
        e = create_evaluator("url_is_valid")
        result = e.evaluate({"response": "View at https://example.com/dashboard/1"})
        assert result.passed

    def test_no_urls(self):
        e = create_evaluator("url_is_valid")
        result = e.evaluate({"response": "No URL here"})
        assert not result.passed


class TestSuccessRateAbove:
    def test_pass(self):
        e = create_evaluator("success_rate_above", min_rate=0.8)
        results = [{"success": True}] * 9 + [{"success": False}]
        result = e.evaluate({"load_test_results": results})
        assert result.passed  # 90% > 80%

    def test_fail(self):
        e = create_evaluator("success_rate_above", min_rate=0.9)
        results = [{"success": True}] * 7 + [{"success": False}] * 3
        result = e.evaluate({"load_test_results": results})
        assert not result.passed  # 70% < 90%


class TestLatencyPercentile:
    def test_pass(self):
        e = create_evaluator("latency_percentile", percentile=95, max_seconds=10.0)
        results = [{"duration": i * 0.5} for i in range(20)]  # 0 to 9.5s
        result = e.evaluate({"load_test_results": results})
        assert result.passed


class TestResponseMatchesPattern:
    def test_pass(self):
        e = create_evaluator("response_matches_pattern", pattern=r"dashboard_id:\s*\d+")
        result = e.evaluate({"response": "Created dashboard_id: 42"})
        assert result.passed
