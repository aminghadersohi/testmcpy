"""Tests for CLI wizard commands - validation logic and YAML generation."""

import stat
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml


class TestWizardYAMLGeneration:
    """Test YAML generation for the add-test wizard."""

    def test_basic_test_yaml_structure(self):
        """Test that generated YAML has correct structure."""
        tests = [
            {
                "name": "basic_test",
                "prompt": "List all dashboards",
                "evaluators": [{"name": "execution_successful"}],
            }
        ]
        data = {"version": "1.0", "tests": tests}
        yaml_str = yaml.dump(data, default_flow_style=False, sort_keys=False)

        parsed = yaml.safe_load(yaml_str)
        assert parsed["version"] == "1.0"
        assert len(parsed["tests"]) == 1
        assert parsed["tests"][0]["name"] == "basic_test"
        assert parsed["tests"][0]["prompt"] == "List all dashboards"
        assert parsed["tests"][0]["evaluators"][0]["name"] == "execution_successful"

    def test_test_with_evaluator_args(self):
        """Test YAML generation with evaluator arguments."""
        tests = [
            {
                "name": "tool_test",
                "prompt": "Call the tool",
                "evaluators": [
                    {
                        "name": "was_mcp_tool_called",
                        "args": {"tool_name": "list_dashboards"},
                    },
                    {
                        "name": "within_time_limit",
                        "args": {"seconds": 30},
                    },
                ],
            }
        ]
        data = {"version": "1.0", "tests": tests}
        yaml_str = yaml.dump(data, default_flow_style=False, sort_keys=False)

        parsed = yaml.safe_load(yaml_str)
        assert len(parsed["tests"][0]["evaluators"]) == 2
        assert parsed["tests"][0]["evaluators"][0]["args"]["tool_name"] == "list_dashboards"
        assert parsed["tests"][0]["evaluators"][1]["args"]["seconds"] == 30

    def test_multiple_tests(self):
        """Test YAML with multiple test cases."""
        tests = [
            {
                "name": "test_one",
                "prompt": "First test",
                "evaluators": [{"name": "execution_successful"}],
            },
            {
                "name": "test_two",
                "prompt": "Second test",
                "evaluators": [
                    {"name": "final_answer_contains", "args": {"text": "success"}},
                ],
            },
        ]
        data = {"version": "1.0", "tests": tests}
        yaml_str = yaml.dump(data, default_flow_style=False, sort_keys=False)

        parsed = yaml.safe_load(yaml_str)
        assert len(parsed["tests"]) == 2
        assert parsed["tests"][0]["name"] == "test_one"
        assert parsed["tests"][1]["name"] == "test_two"

    def test_special_characters_in_prompt(self):
        """Test that special characters in prompts are handled."""
        tests = [
            {
                "name": "special_chars",
                "prompt": 'Show me "all" dashboards with $special & <chars>',
                "evaluators": [{"name": "execution_successful"}],
            }
        ]
        data = {"version": "1.0", "tests": tests}
        yaml_str = yaml.dump(data, default_flow_style=False, sort_keys=False)

        parsed = yaml.safe_load(yaml_str)
        assert parsed["tests"][0]["prompt"] == 'Show me "all" dashboards with $special & <chars>'


class TestWizardMCPConfigGeneration:
    """Test MCP config YAML generation."""

    def test_sse_mcp_entry(self):
        """Test SSE transport MCP entry generation."""
        mcp_entry = {
            "name": "test-server",
            "mcp_url": "https://api.example.com/mcp/",
            "timeout": 30,
            "rate_limit_rpm": 60,
            "auth": {"type": "bearer", "token": "${MY_TOKEN}"},
        }

        yaml_str = yaml.dump(mcp_entry, default_flow_style=False, sort_keys=False)
        parsed = yaml.safe_load(yaml_str)

        assert parsed["name"] == "test-server"
        assert parsed["mcp_url"] == "https://api.example.com/mcp/"
        assert parsed["auth"]["type"] == "bearer"
        assert parsed["auth"]["token"] == "${MY_TOKEN}"

    def test_stdio_mcp_entry(self):
        """Test stdio transport MCP entry generation."""
        mcp_entry = {
            "name": "local-server",
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            "mcp_url": "stdio://npx",
            "timeout": 30,
            "rate_limit_rpm": 60,
        }

        yaml_str = yaml.dump(mcp_entry, default_flow_style=False, sort_keys=False)
        parsed = yaml.safe_load(yaml_str)

        assert parsed["transport"] == "stdio"
        assert parsed["command"] == "npx"
        assert len(parsed["args"]) == 3
        assert parsed["args"][0] == "-y"

    def test_oauth_mcp_entry(self):
        """Test OAuth auth MCP entry generation."""
        mcp_entry = {
            "name": "oauth-server",
            "mcp_url": "https://secure.example.com/mcp/",
            "timeout": 30,
            "rate_limit_rpm": 60,
            "auth": {
                "type": "oauth",
                "client_id": "my-client",
                "client_secret": "secret123",
                "token_url": "https://auth.example.com/token",
                "scopes": ["read", "write"],
            },
        }

        yaml_str = yaml.dump(mcp_entry, default_flow_style=False, sort_keys=False)
        parsed = yaml.safe_load(yaml_str)

        assert parsed["auth"]["type"] == "oauth"
        assert parsed["auth"]["client_id"] == "my-client"
        assert parsed["auth"]["scopes"] == ["read", "write"]


class TestWizardLLMConfigGeneration:
    """Test LLM provider config YAML generation."""

    def test_anthropic_provider_entry(self):
        """Test Anthropic provider entry generation."""
        provider_entry = {
            "name": "Claude Sonnet 4",
            "provider": "anthropic",
            "model": "claude-sonnet-4-20250514",
            "timeout": 60,
            "default": True,
        }

        yaml_str = yaml.dump(provider_entry, default_flow_style=False, sort_keys=False)
        parsed = yaml.safe_load(yaml_str)

        assert parsed["provider"] == "anthropic"
        assert parsed["model"] == "claude-sonnet-4-20250514"
        assert parsed["default"] is True

    def test_ollama_provider_entry(self):
        """Test Ollama provider entry with base_url."""
        provider_entry = {
            "name": "Local Llama",
            "provider": "ollama",
            "model": "llama3.2:latest",
            "base_url": "http://localhost:11434",
            "timeout": 120,
            "default": False,
        }

        yaml_str = yaml.dump(provider_entry, default_flow_style=False, sort_keys=False)
        parsed = yaml.safe_load(yaml_str)

        assert parsed["provider"] == "ollama"
        assert parsed["base_url"] == "http://localhost:11434"

    def test_provider_with_api_key_env(self):
        """Test provider with env var for API key."""
        provider_entry = {
            "name": "GPT-4o",
            "provider": "openai",
            "model": "gpt-4o",
            "api_key_env": "OPENAI_API_KEY",
            "timeout": 60,
            "default": True,
        }

        yaml_str = yaml.dump(provider_entry, default_flow_style=False, sort_keys=False)
        parsed = yaml.safe_load(yaml_str)

        assert parsed["api_key_env"] == "OPENAI_API_KEY"
        assert "api_key" not in parsed


class TestWizardConfigFileSave:
    """Test that wizard properly saves to config files."""

    def test_save_mcp_to_new_config(self):
        """Test saving MCP to a new config file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".mcp_services.yaml"

            config = {
                "default": "test-profile",
                "profiles": {
                    "test-profile": {
                        "name": "Test Profile",
                        "description": "Test",
                        "mcps": [
                            {
                                "name": "my-server",
                                "mcp_url": "https://example.com/mcp/",
                                "timeout": 30,
                            }
                        ],
                    }
                },
            }

            with open(config_path, "w") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)

            # Verify it was written correctly
            with open(config_path) as f:
                loaded = yaml.safe_load(f)

            assert loaded["default"] == "test-profile"
            assert len(loaded["profiles"]["test-profile"]["mcps"]) == 1
            assert loaded["profiles"]["test-profile"]["mcps"][0]["name"] == "my-server"

    def test_save_llm_to_new_config(self):
        """Test saving LLM provider to a new config file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".llm_providers.yaml"

            config = {
                "default": "prod",
                "profiles": {
                    "prod": {
                        "name": "Production",
                        "description": "Production providers",
                        "providers": [
                            {
                                "name": "Claude Sonnet",
                                "provider": "anthropic",
                                "model": "claude-sonnet-4-20250514",
                                "default": True,
                            }
                        ],
                    }
                },
            }

            with open(config_path, "w") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)

            with open(config_path) as f:
                loaded = yaml.safe_load(f)

            assert loaded["default"] == "prod"
            assert len(loaded["profiles"]["prod"]["providers"]) == 1
            assert loaded["profiles"]["prod"]["providers"][0]["provider"] == "anthropic"

    def test_save_test_file(self):
        """Test saving a test YAML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tests_dir = Path(tmpdir) / "tests"
            tests_dir.mkdir()
            file_path = tests_dir / "my_test.yaml"

            test_data = {
                "version": "1.0",
                "tests": [
                    {
                        "name": "basic",
                        "prompt": "Hello",
                        "evaluators": [{"name": "execution_successful"}],
                    }
                ],
            }

            yaml_str = yaml.dump(test_data, default_flow_style=False, sort_keys=False)
            with open(file_path, "w") as f:
                f.write(yaml_str)

            with open(file_path) as f:
                loaded = yaml.safe_load(f)

            assert loaded["version"] == "1.0"
            assert loaded["tests"][0]["name"] == "basic"


class TestWizardHelpers:
    """Test wizard helper functions."""

    def test_choose_helper(self):
        """Test the _choose helper picks correct index."""
        from testmcpy.cli.commands.wizard import _choose

        # Mock Prompt.ask to return "2"
        with patch("testmcpy.cli.commands.wizard.Prompt.ask", return_value="2"):
            result = _choose("Pick:", ["a", "b", "c"])
            assert result == "b"

    def test_choose_helper_default(self):
        """Test Enter selects the marked default even when it is not first."""
        from testmcpy.cli.commands.wizard import _choose

        with patch("testmcpy.cli.commands.wizard.Prompt.ask", return_value="2") as prompt:
            result = _choose("Pick:", ["a", "b", "c"], default="b")

        assert result == "b"
        prompt.assert_called_once_with("Enter number", default="2")


class TestAddMCPConnectionTest:
    """Test the add-mcp wizard's test-connection step (Step 5)."""

    def test_sse_connection_uses_mcp_client(self, tmp_path, monkeypatch):
        """The sse path constructs MCPClient(url, auth=dict) and initializes it."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from typer.testing import CliRunner

        import testmcpy.cli.commands.wizard  # noqa: F401  register add-mcp command
        from testmcpy.cli.app import app

        monkeypatch.chdir(tmp_path)
        instance = AsyncMock()
        instance.list_tools.return_value = [SimpleNamespace(name="list_charts")]

        inputs = (
            "\n".join(
                [
                    "my-server",  # server name
                    "1",  # transport: sse
                    "https://mcp.example.com/mcp/",  # MCP URL
                    "30",  # timeout
                    "60",  # rate limit
                    "2",  # auth: bearer
                    "secret-token",  # bearer token
                    "y",  # test connection now?
                    "local-dev",  # profile id to create
                ]
            )
            + "\n"
        )
        with patch("testmcpy.src.mcp_client.MCPClient", return_value=instance) as mock_cls:
            result = CliRunner().invoke(app, ["add-mcp"], input=inputs)

        assert "Connected! Found 1 tools." in result.output
        mock_cls.assert_called_once_with(
            "https://mcp.example.com/mcp/", auth={"type": "bearer", "token": "secret-token"}
        )
        instance.initialize.assert_awaited()
        instance.close.assert_awaited()


class TestAddLLMCommand:
    """Focused coverage for the add-llm and llm-profiles commands."""

    def test_add_llm_tests_locally_redacts_secret_and_saves_securely(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        import testmcpy.cli.commands.wizard as wizard
        from testmcpy.cli.app import app

        monkeypatch.chdir(tmp_path)
        direct_secret = "sk-test-never-print-this"
        shared_test = AsyncMock(return_value={"success": True, "duration": 0.01})

        with (
            patch("testmcpy.src.model_registry.get_models_by_provider", return_value=[]),
            patch.object(wizard, "_choose", return_value="openai"),
            patch.object(
                wizard,
                "_prompt",
                side_effect=[
                    "gpt-test-model",
                    "Local Test Provider",
                    direct_secret,
                    "prod",
                ],
            ),
            patch.object(wizard.IntPrompt, "ask", return_value=45),
            patch.object(wizard.Confirm, "ask", side_effect=[True, True]),
            patch(
                "testmcpy.llm_testing.test_llm_provider_connection",
                shared_test,
            ),
        ):
            result = CliRunner().invoke(app, ["add-llm"])

        assert result.exit_code == 0, result.exception
        shared_test.assert_awaited_once_with(
            provider="openai",
            model="gpt-test-model",
            api_key=direct_secret,
            api_key_env=None,
            base_url=None,
            timeout=45,
        )
        assert direct_secret not in result.output
        assert "*** configured ***" in result.output
        assert "Test passed!" in result.output

        config_path = tmp_path / ".llm_providers.yaml"
        saved = yaml.safe_load(config_path.read_text())
        provider = saved["profiles"]["prod"]["providers"][0]
        assert provider["api_key"] == direct_secret
        assert provider["default"] is True
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o600

    def test_add_llm_can_create_profile_when_profiles_already_exist(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        import testmcpy.cli.commands.wizard as wizard
        from testmcpy.cli.app import app
        from testmcpy.llm_profiles import LLMProfile, LLMProfileConfig

        monkeypatch.chdir(tmp_path)
        existing = LLMProfileConfig()
        existing.add_profile(
            LLMProfile(
                profile_id="prod",
                name="Production",
                description="Existing profile",
            )
        )
        existing.default_profile_id = "prod"
        existing.save()

        def choose(label, choices, default=None):
            if label == "Provider:":
                return "claude-sdk"
            assert label == "Add to profile:"
            assert choices == ["prod", wizard._CREATE_LLM_PROFILE_CHOICE]
            assert default == "prod"
            return wizard._CREATE_LLM_PROFILE_CHOICE

        with (
            patch("testmcpy.src.model_registry.get_models_by_provider", return_value=[]),
            patch.object(wizard, "_choose", side_effect=choose),
            patch.object(
                wizard,
                "_prompt",
                side_effect=[
                    "claude-sdk-test",
                    "Claude SDK Provider",
                    "local_dev",
                ],
            ),
            patch.object(wizard.IntPrompt, "ask", return_value=60),
            patch.object(wizard.Confirm, "ask", side_effect=[False, False]),
        ):
            result = CliRunner().invoke(app, ["add-llm"])

        assert result.exit_code == 0, result.exception
        loaded = LLMProfileConfig()
        assert loaded.list_profiles() == ["prod", "local_dev"]
        assert loaded.default_profile_id == "prod"
        assert loaded.profiles["prod"].providers == []
        assert loaded.profiles["local_dev"].providers[0].provider == "claude-sdk"

    @pytest.mark.parametrize("configured_default", [None, "missing"])
    def test_add_llm_repairs_missing_or_dangling_default_profile(
        self,
        tmp_path,
        monkeypatch,
        configured_default,
    ):
        from typer.testing import CliRunner

        import testmcpy.cli.commands.wizard as wizard
        from testmcpy.cli.app import app
        from testmcpy.llm_profiles import LLMProfile, LLMProfileConfig

        monkeypatch.chdir(tmp_path)
        existing = LLMProfileConfig()
        existing.add_profile(
            LLMProfile(profile_id="prod", name="Production", description="Existing")
        )
        existing.default_profile_id = configured_default
        existing.save()

        def choose(label, choices, default=None):
            if label == "Provider:":
                return "claude-sdk"
            assert label == "Add to profile:"
            assert choices == ["prod", wizard._CREATE_LLM_PROFILE_CHOICE]
            return "prod"

        with (
            patch("testmcpy.src.model_registry.get_models_by_provider", return_value=[]),
            patch.object(wizard, "_choose", side_effect=choose),
            patch.object(
                wizard,
                "_prompt",
                side_effect=["claude-sdk-test", "Claude SDK Provider"],
            ),
            patch.object(wizard.IntPrompt, "ask", return_value=60),
            patch.object(wizard.Confirm, "ask", side_effect=[True, False]),
        ):
            result = CliRunner().invoke(app, ["add-llm"])

        assert result.exit_code == 0, result.exception
        loaded = LLMProfileConfig()
        assert loaded.default_profile_id == "prod"
        assert loaded.profiles["prod"].providers[0].provider == "claude-sdk"

    def test_add_codex_requires_api_key_configuration(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        import testmcpy.cli.commands.wizard as wizard
        from testmcpy.cli.app import app

        monkeypatch.chdir(tmp_path)
        with (
            patch("testmcpy.src.model_registry.get_models_by_provider", return_value=[]),
            patch.object(wizard, "_choose", return_value="codex-sdk"),
            patch.object(
                wizard,
                "_prompt",
                side_effect=[
                    "codex-test",
                    "Codex Provider",
                    "",
                    "OPENAI_API_KEY",
                    "prod",
                ],
            ),
            patch.object(wizard.IntPrompt, "ask", return_value=60),
            patch.object(wizard.Confirm, "ask", side_effect=[True, False]),
        ):
            result = CliRunner().invoke(app, ["add-llm"])

        assert result.exit_code == 0, result.exception
        assert "OAuth-only Codex login cannot authenticate" in result.output
        saved = yaml.safe_load((tmp_path / ".llm_providers.yaml").read_text())
        provider = saved["profiles"]["prod"]["providers"][0]
        assert provider["provider"] == "codex-sdk"
        assert provider["api_key_env"] == "OPENAI_API_KEY"

    def test_add_assistant_collects_and_redacts_every_credential(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        import testmcpy.cli.commands.wizard as wizard
        from testmcpy.cli.app import app

        monkeypatch.chdir(tmp_path)
        api_token = "assistant-token-never-print"
        api_secret = "assistant-secret-never-print"
        shared_test = AsyncMock(
            return_value={
                "success": False,
                "tested": False,
                "error": "Assistant profiles require a workspace conversation to verify",
            }
        )
        with (
            patch("testmcpy.src.model_registry.get_models_by_provider", return_value=[]),
            patch.object(wizard, "_choose", return_value="assistant"),
            patch.object(
                wizard,
                "_prompt",
                side_effect=[
                    "assistant-model",
                    "Workspace Assistant",
                    "workspace-hash",
                    "example.test",
                    "https://example.test/auth",
                    api_token,
                    api_secret,
                    "/api/conversations",
                    "/api/completions",
                    "prod",
                ],
            ),
            patch.object(wizard.IntPrompt, "ask", return_value=60),
            patch.object(wizard.Confirm, "ask", side_effect=[True, True]),
            patch("testmcpy.llm_testing.test_llm_provider_connection", shared_test),
        ):
            result = CliRunner().invoke(app, ["add-llm"])

        assert result.exit_code == 0, result.exception
        shared_test.assert_awaited_once_with(
            provider="assistant",
            model="assistant-model",
            api_key=None,
            api_key_env=None,
            base_url=None,
            timeout=60,
            workspace_hash="workspace-hash",
            domain="example.test",
            api_url="https://example.test/auth",
            api_token=api_token,
            api_secret=api_secret,
            conversations_path="/api/conversations",
            completions_path="/api/completions",
        )
        assert "Test skipped" in result.output
        assert api_token not in result.output
        assert api_secret not in result.output
        assert result.output.count("*** configured ***") >= 2

        config_path = tmp_path / ".llm_providers.yaml"
        saved = yaml.safe_load(config_path.read_text())
        provider = saved["profiles"]["prod"]["providers"][0]
        assert provider == {
            "name": "Workspace Assistant",
            "provider": "assistant",
            "model": "assistant-model",
            "timeout": 60,
            "default": True,
            "workspace_hash": "workspace-hash",
            "domain": "example.test",
            "api_token": api_token,
            "api_secret": api_secret,
            "api_url": "https://example.test/auth",
            "conversations_path": "/api/conversations",
            "completions_path": "/api/completions",
        }
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o600

    def test_add_ollama_skips_credentials_and_single_display_prompt(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        import testmcpy.cli.commands.wizard as wizard
        from testmcpy.cli.app import app

        monkeypatch.chdir(tmp_path)
        prompts = [
            "llama3.1:8b",
            "Local Llama",
            "http://127.0.0.1:11434",
            "prod",
        ]
        with (
            patch("testmcpy.src.model_registry.get_models_by_provider", return_value=[]),
            patch.object(wizard, "_choose", return_value="ollama"),
            patch.object(wizard, "_prompt", side_effect=prompts) as prompt,
            patch.object(wizard.IntPrompt, "ask", return_value=60),
            patch.object(wizard.Confirm, "ask", side_effect=[True, False]),
        ):
            result = CliRunner().invoke(app, ["add-llm"])

        assert result.exit_code == 0, result.exception
        assert [call.args[0] for call in prompt.call_args_list] == [
            "Model ID",
            "Display name",
            "Base URL",
            "Profile ID to create",
        ]
        provider = yaml.safe_load((tmp_path / ".llm_providers.yaml").read_text())["profiles"][
            "prod"
        ]["providers"][0]
        assert provider["base_url"] == "http://127.0.0.1:11434"
        assert "api_key" not in provider
        assert "api_key_env" not in provider

    def test_codex_oauth_only_is_not_reported_as_authenticated(self, tmp_path, monkeypatch):
        import testmcpy.cli.commands.wizard as wizard
        from testmcpy.llm_profiles import LLMProviderConfig

        monkeypatch.setenv("HOME", str(tmp_path))
        provider = LLMProviderConfig(
            name="Keyless Codex",
            provider="codex-sdk",
            model="codex-o4-mini",
        )
        assert wizard._credential_status(provider) == "Codex API key (not configured)"

        auth_dir = tmp_path / ".codex"
        auth_dir.mkdir()
        oauth_secret = "oauth-access-token-never-print"
        (auth_dir / "auth.json").write_text('{"tokens": {"access_token": "' + oauth_secret + '"}}')
        assert wizard._credential_status(provider) == "Codex API key (not configured)"

        api_key = "codex-platform-key-never-print"
        (auth_dir / "auth.json").write_text('{"OPENAI_API_KEY": "' + api_key + '"}')
        status = wizard._credential_status(provider)
        assert status == "host API key (configured)"
        assert oauth_secret not in status
        assert api_key not in status

    def test_llm_profiles_masks_credentials_and_is_read_only(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        import testmcpy.cli.commands.wizard as wizard
        from testmcpy.cli.app import app
        from testmcpy.llm_profiles import LLMProfile, LLMProfileConfig, LLMProviderConfig

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("TEST_LLM_LIST_KEY", "env-secret-never-print")
        direct_secret = "direct-secret-never-print"
        assistant_token = "assistant-token-never-print"
        assistant_secret = "assistant-secret-never-print"

        config = LLMProfileConfig()
        config.add_profile(
            LLMProfile(
                profile_id="prod",
                name="Production",
                description="Credential listing",
                providers=[
                    LLMProviderConfig(
                        name="Direct",
                        provider="openai",
                        model="gpt-test",
                        api_key=direct_secret,
                        default=True,
                    ),
                    LLMProviderConfig(
                        name="Environment",
                        provider="anthropic",
                        model="claude-test",
                        api_key_env="TEST_LLM_LIST_KEY",
                    ),
                    LLMProviderConfig(
                        name="Assistant",
                        provider="assistant",
                        model="default",
                        api_token=assistant_token,
                        api_secret=assistant_secret,
                    ),
                    LLMProviderConfig(
                        name="SDK",
                        provider="claude-sdk",
                        model="claude-sdk-test",
                    ),
                ],
            )
        )
        config.add_profile(LLMProfile(profile_id="empty", name="Empty", description="No providers"))
        config.default_profile_id = "prod"
        config.save()
        providers = config.profiles["prod"].providers
        assert wizard._credential_status(providers[0]) == "direct key (configured)"
        assert wizard._credential_status(providers[1]) == "env TEST_LLM_LIST_KEY (set)"
        assert wizard._credential_status(providers[2]) == "assistant token + secret (configured)"
        assert wizard._credential_status(providers[3]) == "host login"
        config_path = tmp_path / ".llm_providers.yaml"
        before = config_path.read_bytes()
        before_mtime = config_path.stat().st_mtime_ns

        runner = CliRunner()
        result = runner.invoke(app, ["llm-profiles"], terminal_width=220)

        assert result.exit_code == 0, result.exception
        normalized_output = " ".join(result.output.split())
        assert "LLM Profiles" in normalized_output
        assert "direct key" in normalized_output
        assert "assistant" in normalized_output
        assert "host login" in normalized_output
        assert "empty" in normalized_output
        for secret in (
            direct_secret,
            assistant_token,
            assistant_secret,
            "env-secret-never-print",
        ):
            assert secret not in result.output
        assert config_path.read_bytes() == before
        assert config_path.stat().st_mtime_ns == before_mtime

        filtered = runner.invoke(
            app,
            ["llm-profiles", "--profile", "empty"],
            terminal_width=220,
        )
        assert filtered.exit_code == 0
        assert "empty" in filtered.output
        assert "openai" not in filtered.output

        missing = runner.invoke(app, ["llm-profiles", "--profile", "missing"])
        assert missing.exit_code == 1
        assert "was not found" in missing.output

    def test_llm_profiles_reports_malformed_config(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from testmcpy.cli.app import app

        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / ".llm_providers.yaml"
        malformed = "profiles:\n  prod:\n    providers:\n      - null\n"
        config_path.write_text(malformed)

        result = CliRunner().invoke(app, ["llm-profiles"])

        assert result.exit_code == 1
        assert "Invalid .llm_providers.yaml" in result.output
        assert config_path.read_text() == malformed
