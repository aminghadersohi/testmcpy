"""Profile-backed credentials reach usable direct LLM provider consumers."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest
from typer.testing import CliRunner


def _write_openai_profile(tmp_path, monkeypatch) -> str:
    secret = "profile-runtime-secret"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROFILE_OPENAI_KEY", secret)
    (tmp_path / ".llm_providers.yaml").write_text(
        """default: prod
profiles:
  prod:
    name: Production
    description: Profile runtime test
    providers:
      - name: Profile OpenAI
        provider: openai
        model: gpt-profile
        api_key_env: PROFILE_OPENAI_KEY
        default: true
"""
    )

    from testmcpy.config import reload_config

    reload_config()
    return secret


def _write_mcp_profiles(tmp_path, monkeypatch) -> dict[str, tuple[str, dict]]:
    monkeypatch.setenv("DEFAULT_MCP_SECRET", "default-oauth-secret")
    monkeypatch.setenv("EXPLICIT_MCP_SECRET", "explicit-oauth-secret")
    (tmp_path / ".mcp_services.yaml").write_text(
        """default: default-oauth
profiles:
  default-oauth:
    name: Default OAuth
    description: Default OAuth MCP
    mcps:
      - name: Default server
        mcp_url: http://default.example/mcp
        default: true
        auth:
          type: oauth
          client_id: default-client
          client_secret: ${DEFAULT_MCP_SECRET}
          token_url: https://auth.default.example/token
          scopes: [mcp.read]
  explicit-oauth:
    name: Explicit OAuth
    description: Explicit OAuth MCP
    mcps:
      - name: Explicit server
        mcp_url: http://explicit.example/mcp
        default: true
        auth:
          type: oauth
          client_id: explicit-client
          client_secret: ${EXPLICIT_MCP_SECRET}
          token_url: https://auth.explicit.example/token
          scopes: [mcp.read, mcp.write]
"""
    )

    from testmcpy.config import reload_config
    from testmcpy.mcp_profiles import reload_profile_config

    reload_profile_config()
    reload_config()
    return {
        "default-oauth": (
            "http://default.example/mcp",
            {
                "type": "oauth",
                "client_id": "default-client",
                "client_secret": "default-oauth-secret",
                "token_url": "https://auth.default.example/token",
                "scopes": ["mcp.read"],
            },
        ),
        "explicit-oauth": (
            "http://explicit.example/mcp",
            {
                "type": "oauth",
                "client_id": "explicit-client",
                "client_secret": "explicit-oauth-secret",
                "token_url": "https://auth.explicit.example/token",
                "scopes": ["mcp.read", "mcp.write"],
            },
        ),
    }


def _assert_profile_factory_call(factory: Mock, secret: str) -> None:
    args, kwargs = factory.call_args
    assert args[:2] == ("openai", "gpt-profile")
    assert kwargs["api_key"] == secret
    assert kwargs["api_key_env"] == "PROFILE_OPENAI_KEY"


@pytest.mark.parametrize("profile_args", [[], ["--llm-profile", "prod"]])
def test_chat_command_uses_profile_credentials(tmp_path, monkeypatch, profile_args):
    secret = _write_openai_profile(tmp_path, monkeypatch)

    import testmcpy.cli.commands.tui  # noqa: F401
    from testmcpy.cli.app import app

    provider = Mock()
    provider.initialize = AsyncMock()
    provider.close = AsyncMock()

    with patch(
        "testmcpy.src.llm_integration.create_llm_provider",
        return_value=provider,
    ) as factory:
        result = CliRunner().invoke(
            app,
            ["chat", *profile_args, "--no-mcp"],
            input="exit\n",
        )

    assert result.exit_code == 0, result.exception
    assert "LLM profile: prod" in result.output
    assert secret not in result.output
    _assert_profile_factory_call(factory, secret)
    assert factory.call_args.kwargs["mcp_url"] == ""
    assert factory.call_args.kwargs["auth"] == {}
    provider.initialize.assert_awaited_once()
    provider.close.assert_awaited_once()


def test_chat_command_routes_selected_mcp_profile_to_sdk_provider(tmp_path, monkeypatch):
    secret = _write_openai_profile(tmp_path, monkeypatch)
    profiles = _write_mcp_profiles(tmp_path, monkeypatch)

    import testmcpy.cli.commands.tui  # noqa: F401
    from testmcpy.cli.app import app

    provider = Mock(initialize=AsyncMock(), close=AsyncMock())
    mcp_client = Mock(
        initialize=AsyncMock(),
        list_tools=AsyncMock(return_value=[]),
        close=AsyncMock(),
    )
    with (
        patch(
            "testmcpy.src.llm_integration.create_llm_provider",
            return_value=provider,
        ) as factory,
        patch("testmcpy.src.mcp_client.MCPClient", return_value=mcp_client) as mcp_factory,
    ):
        result = CliRunner().invoke(
            app,
            ["chat", "--profile", "explicit-oauth"],
            input="exit\n",
        )

    assert result.exit_code == 0, result.exception
    expected_url, expected_auth = profiles["explicit-oauth"]
    _assert_profile_factory_call(factory, secret)
    assert factory.call_args.kwargs["mcp_url"] == expected_url
    assert factory.call_args.kwargs["auth"] == expected_auth
    mcp_factory.assert_called_once_with(expected_url, auth=expected_auth)
    mcp_client.initialize.assert_awaited_once()
    mcp_client.close.assert_awaited_once()
    provider.close.assert_awaited_once()


@pytest.mark.parametrize("mcp_profile", [None, "explicit-oauth"])
@pytest.mark.asyncio
async def test_chat_session_routes_profile_credentials(tmp_path, monkeypatch, mcp_profile):
    secret = _write_openai_profile(tmp_path, monkeypatch)
    profiles = _write_mcp_profiles(tmp_path, monkeypatch)

    from testmcpy.core.chat_session import ChatSession

    provider = Mock()
    provider.initialize = AsyncMock()
    mcp_client = Mock()
    mcp_client.initialize = AsyncMock()
    mcp_client.list_tools = AsyncMock(return_value=[])
    mcp_client.close = AsyncMock()
    provider.close = AsyncMock()

    with (
        patch("testmcpy.core.chat_session.create_llm_provider", return_value=provider) as factory,
        patch("testmcpy.core.chat_session.MCPClient", return_value=mcp_client) as mcp_factory,
    ):
        session = ChatSession(profile=mcp_profile)
        await session.initialize()
        await session.close()
        await session.close()

    expected_profile = mcp_profile or "default-oauth"
    expected_url, expected_auth = profiles[expected_profile]
    _assert_profile_factory_call(factory, secret)
    assert factory.call_args.kwargs["mcp_url"] == expected_url
    assert factory.call_args.kwargs["auth"] == expected_auth
    mcp_factory.assert_called_once_with(expected_url, auth=expected_auth)
    provider.initialize.assert_awaited_once()
    provider.close.assert_awaited_once()
    mcp_client.close.assert_awaited_once()
    assert session.llm_provider is None
    assert session.mcp_client is None
    assert session._initialized is False


@pytest.mark.asyncio
async def test_chat_session_does_not_attach_profile_auth_to_overridden_url(tmp_path, monkeypatch):
    secret = _write_openai_profile(tmp_path, monkeypatch)
    _write_mcp_profiles(tmp_path, monkeypatch)

    from testmcpy.core.chat_session import ChatSession

    provider = Mock(initialize=AsyncMock(), close=AsyncMock())
    mcp_client = Mock(
        initialize=AsyncMock(),
        list_tools=AsyncMock(return_value=[]),
        close=AsyncMock(),
    )
    override_url = "http://override.example/mcp"

    with (
        patch("testmcpy.core.chat_session.create_llm_provider", return_value=provider) as factory,
        patch("testmcpy.core.chat_session.MCPClient", return_value=mcp_client) as mcp_factory,
    ):
        session = ChatSession(mcp_url=override_url)
        await session.initialize()
        await session.close()

    _assert_profile_factory_call(factory, secret)
    assert factory.call_args.kwargs["mcp_url"] == override_url
    assert factory.call_args.kwargs["auth"] is None
    mcp_factory.assert_called_once_with(override_url, auth=None)


@pytest.mark.asyncio
async def test_chat_session_rolls_back_when_mcp_initialization_is_cancelled(tmp_path, monkeypatch):
    _write_openai_profile(tmp_path, monkeypatch)

    from testmcpy.core.chat_session import ChatSession

    provider = Mock(initialize=AsyncMock(), close=AsyncMock())
    mcp_client = Mock(
        initialize=AsyncMock(side_effect=asyncio.CancelledError()),
        close=AsyncMock(),
    )

    with (
        patch("testmcpy.core.chat_session.create_llm_provider", return_value=provider),
        patch("testmcpy.core.chat_session.MCPClient", return_value=mcp_client),
    ):
        session = ChatSession()
        with pytest.raises(asyncio.CancelledError):
            await session.initialize()

    provider.close.assert_awaited_once()
    mcp_client.close.assert_awaited_once()
    assert session.llm_provider is None
    assert session.mcp_client is None
    assert session._initialized is False


@pytest.mark.asyncio
async def test_docs_optimizer_executes_request_with_explicit_profile_credentials(
    tmp_path, monkeypatch
):
    secret = _write_openai_profile(tmp_path, monkeypatch)

    from testmcpy.core.docs_optimizer import DocsOptimizer
    from testmcpy.src.llm_integration import LLMResult
    from testmcpy.src.mcp_client import MCPTool

    provider = Mock()
    provider.initialize = AsyncMock()
    provider.generate_with_tools = AsyncMock(
        return_value=LLMResult(
            response=(
                "IMPROVED DESCRIPTION:\nA clearer description.\n"
                "SUGGESTIONS:\n- Add an example\n"
                "PARAMETER IMPROVEMENTS:\nquery: Search text"
            ),
            token_usage={"prompt": 10, "completion": 7, "total": 17},
        )
    )
    provider.close = AsyncMock()

    with patch(
        "testmcpy.core.docs_optimizer.create_llm_provider",
        return_value=provider,
    ) as factory:
        optimizer = DocsOptimizer(llm_profile="prod")
        result = await optimizer.optimize_tool_docs(
            MCPTool(name="search", description="Search", input_schema={"type": "object"})
        )
        await optimizer.close()
        await optimizer.close()

    _assert_profile_factory_call(factory, secret)
    provider.initialize.assert_awaited_once()
    provider.generate_with_tools.assert_awaited_once()
    assert provider.generate_with_tools.call_args.kwargs["tools"] == []
    assert "Tool Name: search" in provider.generate_with_tools.call_args.kwargs["prompt"]
    assert result.optimized_description == "A clearer description."
    assert result.tokens_used == 17
    provider.close.assert_awaited_once()
    assert optimizer.llm is None


@pytest.mark.asyncio
async def test_docs_optimizer_closes_provider_when_initialization_fails(tmp_path, monkeypatch):
    _write_openai_profile(tmp_path, monkeypatch)

    from testmcpy.core.docs_optimizer import DocsOptimizer

    provider = Mock(
        initialize=AsyncMock(side_effect=RuntimeError("initialization failed")),
        close=AsyncMock(),
    )
    with patch("testmcpy.core.docs_optimizer.create_llm_provider", return_value=provider):
        optimizer = DocsOptimizer(llm_profile="prod")
        with pytest.raises(RuntimeError, match="initialization failed"):
            await optimizer.initialize()

    provider.close.assert_awaited_once()
    assert optimizer.llm is None


@pytest.mark.asyncio
async def test_mcp_runner_executes_request_without_replaying_native_tool_results(
    tmp_path, monkeypatch
):
    secret = _write_openai_profile(tmp_path, monkeypatch)

    from testmcpy.src.llm_integration import LLMResult
    from testmcpy.src.runner_tools import MCPRunner, ToolDefinition

    provider = Mock(
        initialize=AsyncMock(),
        generate_with_tools=AsyncMock(
            return_value=LLMResult(
                response="completed",
                tool_calls=[{"id": "native-1", "name": "mutate", "arguments": {"x": 1}}],
                tool_results=[
                    {"tool_call_id": "native-1", "content": {"ok": True}, "is_error": False}
                ],
                token_usage={"prompt": 5, "completion": 3, "total": 8},
                raw_response={"request_id": "req-1"},
            )
        ),
        close=AsyncMock(),
    )
    mcp_client = Mock(
        base_url="http://127.0.0.1:8084/mcp",
        auth_config={"type": "bearer", "token": "mcp-token"},
        initialize=AsyncMock(),
        call_tool=AsyncMock(),
        close=AsyncMock(),
    )
    with (
        patch("testmcpy.src.runner_tools.MCPClient", return_value=mcp_client) as mcp_factory,
        patch(
            "testmcpy.src.runner_tools.create_llm_provider",
            return_value=provider,
        ) as factory,
    ):
        runner = MCPRunner(
            mcp_url="http://127.0.0.1:8084/mcp",
            llm_profile="prod",
        )
        await runner.initialize()
        result = await runner.execute(
            "mutate once",
            [ToolDefinition(name="mutate", description="Mutate", parameters={})],
            timeout=12,
            messages=[{"role": "user", "content": "prior"}],
        )
        await runner.close()
        await runner.close()

    _assert_profile_factory_call(factory, secret)
    assert factory.call_args.kwargs["mcp_url"] == "http://127.0.0.1:8084/mcp"
    assert factory.call_args.kwargs["auth"] == mcp_client.auth_config
    mcp_factory.assert_called_once_with("http://127.0.0.1:8084/mcp")
    mcp_client.initialize.assert_awaited_once()
    provider.initialize.assert_awaited_once()
    provider.generate_with_tools.assert_awaited_once_with(
        prompt="mutate once",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "mutate",
                    "description": "Mutate",
                    "parameters": {},
                },
            }
        ],
        timeout=12,
        messages=[{"role": "user", "content": "prior"}],
    )
    mcp_client.call_tool.assert_not_awaited()
    assert result.error is None
    assert result.response == "completed"
    assert result.tool_results[0].content == {"ok": True}
    assert result.tokens_input == 5
    assert result.tokens_output == 3
    assert result.raw_response == {"request_id": "req-1"}
    provider.close.assert_awaited_once()
    mcp_client.close.assert_awaited_once()
    assert runner.llm_provider is None
    assert runner.mcp_client is None
    assert runner._initialized is False


@pytest.mark.asyncio
async def test_mcp_runner_rolls_back_owned_mcp_when_provider_initialization_fails(
    tmp_path, monkeypatch
):
    _write_openai_profile(tmp_path, monkeypatch)

    from testmcpy.src.runner_tools import MCPRunner

    mcp_client = Mock(initialize=AsyncMock(), close=AsyncMock())
    provider = Mock(
        initialize=AsyncMock(side_effect=RuntimeError("provider failed")),
        close=AsyncMock(),
    )
    with (
        patch("testmcpy.src.runner_tools.MCPClient", return_value=mcp_client),
        patch("testmcpy.src.runner_tools.create_llm_provider", return_value=provider),
    ):
        runner = MCPRunner(mcp_url="http://127.0.0.1:8084/mcp", llm_profile="prod")
        with pytest.raises(RuntimeError, match="provider failed"):
            await runner.initialize()

    provider.close.assert_awaited_once()
    mcp_client.close.assert_awaited_once()
    assert runner.llm_provider is None
    assert runner.mcp_client is None
    assert runner._initialized is False


def test_chat_command_closes_provider_when_initialization_fails(tmp_path, monkeypatch):
    _write_openai_profile(tmp_path, monkeypatch)

    import testmcpy.cli.commands.tui  # noqa: F401
    from testmcpy.cli.app import app

    provider = Mock(
        initialize=AsyncMock(side_effect=RuntimeError("provider failed")),
        close=AsyncMock(),
    )
    with patch("testmcpy.src.llm_integration.create_llm_provider", return_value=provider):
        result = CliRunner().invoke(app, ["chat", "--no-mcp"])

    assert result.exit_code == 1
    provider.close.assert_awaited_once()
