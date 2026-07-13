"""
Unit tests for testmcpy.llm_profiles module.

Tests cover:
- LLMProviderConfig creation and serialization
- LLMProfile default provider selection
- LLMProfileConfig loading from YAML files
- API key resolution (direct and env vars)
- Default profile selection
- Profile management (add, remove, set default)
- Edge cases and error handling
"""

import os
import stat
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest
import yaml

from testmcpy.llm_profiles import (
    LLMProfile,
    LLMProfileConfig,
    LLMProfileConfigError,
    LLMProfileNotFoundError,
    LLMProviderConfig,
    get_default_llm_profile_id,
    get_llm_profile_config,
    list_available_llm_profiles,
    load_llm_profile,
    reload_llm_profile_config,
    resolve_llm_provider_config,
    resolve_llm_provider_selection,
)


class TestLLMProviderConfig:
    """Tests for LLMProviderConfig dataclass."""

    def test_minimal_provider_config(self):
        """Test creating provider config with minimal required fields."""
        config = LLMProviderConfig(
            name="Test Provider",
            provider="anthropic",
            model="claude-sonnet-4-20250514",
        )

        assert config.name == "Test Provider"
        assert config.provider == "anthropic"
        assert config.model == "claude-sonnet-4-20250514"
        assert config.api_key is None
        assert config.api_key_env is None
        assert config.base_url is None
        assert config.timeout == 60
        assert config.default is False

    def test_full_provider_config(self):
        """Test creating provider config with all fields."""
        config = LLMProviderConfig(
            name="OpenAI GPT-4",
            provider="openai",
            model="gpt-4o",
            api_key="sk-test-key",
            api_key_env="OPENAI_API_KEY",
            base_url="https://api.openai.com/v1",
            timeout=120,
            default=True,
        )

        assert config.name == "OpenAI GPT-4"
        assert config.provider == "openai"
        assert config.model == "gpt-4o"
        assert config.api_key == "sk-test-key"
        assert config.api_key_env == "OPENAI_API_KEY"
        assert config.base_url == "https://api.openai.com/v1"
        assert config.timeout == 120
        assert config.default is True

    def test_api_key_env_resolves_lazily_without_materializing(self, monkeypatch):
        monkeypatch.setenv("CUSTOM_OPENAI_KEY", "runtime-key")
        config = LLMProviderConfig(
            name="OpenAI",
            provider="openai",
            model="gpt-4o",
            api_key_env="CUSTOM_OPENAI_KEY",
        )

        assert config.api_key == "runtime-key"
        assert config.to_dict()["api_key_env"] == "CUSTOM_OPENAI_KEY"
        assert "api_key" not in config.to_dict()

    def test_to_dict_minimal(self):
        """Test to_dict() with minimal config excludes None values."""
        config = LLMProviderConfig(
            name="Test",
            provider="anthropic",
            model="claude-sonnet-4-20250514",
        )

        result = config.to_dict()

        assert result == {
            "name": "Test",
            "provider": "anthropic",
            "model": "claude-sonnet-4-20250514",
            "timeout": 60,
            "default": False,
        }
        # Ensure None values are not included
        assert "api_key" not in result
        assert "api_key_env" not in result
        assert "base_url" not in result

    def test_to_dict_full(self):
        """Test to_dict() with all fields populated."""
        config = LLMProviderConfig(
            name="Test",
            provider="openai",
            model="gpt-4o",
            api_key="test-key",
            api_key_env="OPENAI_API_KEY",
            base_url="https://example.com",
            timeout=90,
            default=True,
        )

        result = config.to_dict()

        assert result == {
            "name": "Test",
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "test-key",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://example.com",
            "timeout": 90,
            "default": True,
        }

    def test_different_provider_types(self):
        """Test different provider types are supported."""
        providers = ["anthropic", "openai", "ollama", "claude-sdk", "claude-cli"]

        for provider_type in providers:
            config = LLMProviderConfig(
                name=f"{provider_type} Provider",
                provider=provider_type,
                model="test-model",
            )
            assert config.provider == provider_type


class TestLLMProfile:
    """Tests for LLMProfile dataclass."""

    def test_empty_profile(self):
        """Test creating an empty profile."""
        profile = LLMProfile(
            profile_id="test",
            name="Test Profile",
            description="Test description",
        )

        assert profile.profile_id == "test"
        assert profile.name == "Test Profile"
        assert profile.description == "Test description"
        assert profile.providers == []

    def test_profile_with_providers(self):
        """Test creating profile with multiple providers."""
        providers = [
            LLMProviderConfig(
                name="Provider 1",
                provider="anthropic",
                model="claude-sonnet-4-20250514",
            ),
            LLMProviderConfig(
                name="Provider 2",
                provider="openai",
                model="gpt-4o",
            ),
        ]

        profile = LLMProfile(
            profile_id="multi",
            name="Multi Provider",
            description="Multiple providers",
            providers=providers,
        )

        assert len(profile.providers) == 2
        assert profile.providers[0].name == "Provider 1"
        assert profile.providers[1].name == "Provider 2"

    def test_get_default_provider_marked(self):
        """Test get_default_provider() returns explicitly marked default."""
        providers = [
            LLMProviderConfig(
                name="Provider 1",
                provider="anthropic",
                model="model1",
                default=False,
            ),
            LLMProviderConfig(
                name="Provider 2",
                provider="openai",
                model="model2",
                default=True,
            ),
            LLMProviderConfig(
                name="Provider 3",
                provider="anthropic",
                model="model3",
                default=False,
            ),
        ]

        profile = LLMProfile(
            profile_id="test",
            name="Test",
            description="Test",
            providers=providers,
        )

        default = profile.get_default_provider()
        assert default is not None
        assert default.name == "Provider 2"
        assert default.default is True

    def test_get_default_provider_first_when_none_marked(self):
        """Test get_default_provider() returns first when none marked default."""
        providers = [
            LLMProviderConfig(
                name="Provider 1",
                provider="anthropic",
                model="model1",
            ),
            LLMProviderConfig(
                name="Provider 2",
                provider="openai",
                model="model2",
            ),
        ]

        profile = LLMProfile(
            profile_id="test",
            name="Test",
            description="Test",
            providers=providers,
        )

        default = profile.get_default_provider()
        assert default is not None
        assert default.name == "Provider 1"

    def test_get_default_provider_empty_list(self):
        """Test get_default_provider() returns None for empty provider list."""
        profile = LLMProfile(
            profile_id="empty",
            name="Empty",
            description="No providers",
        )

        default = profile.get_default_provider()
        assert default is None

    def test_get_default_provider_multiple_defaults(self):
        """Test get_default_provider() returns first when multiple marked default."""
        providers = [
            LLMProviderConfig(
                name="Provider 1",
                provider="anthropic",
                model="model1",
                default=True,
            ),
            LLMProviderConfig(
                name="Provider 2",
                provider="openai",
                model="model2",
                default=True,
            ),
        ]

        profile = LLMProfile(
            profile_id="test",
            name="Test",
            description="Test",
            providers=providers,
        )

        default = profile.get_default_provider()
        assert default is not None
        assert default.name == "Provider 1"

    def test_to_dict(self):
        """Test profile serialization to dict."""
        providers = [
            LLMProviderConfig(
                name="Test Provider",
                provider="anthropic",
                model="claude-sonnet-4-20250514",
                default=True,
            )
        ]

        profile = LLMProfile(
            profile_id="test",
            name="Test Profile",
            description="Test description",
            providers=providers,
        )

        result = profile.to_dict()

        assert result == {
            "name": "Test Profile",
            "description": "Test description",
            "providers": [
                {
                    "name": "Test Provider",
                    "provider": "anthropic",
                    "model": "claude-sonnet-4-20250514",
                    "timeout": 60,
                    "default": True,
                }
            ],
        }


class TestLLMProfileConfig:
    """Tests for LLMProfileConfig and YAML loading."""

    @patch("pathlib.Path.exists")
    def test_no_config_file(self, mock_exists):
        """Test initialization when no config file exists."""
        mock_exists.return_value = False

        config = LLMProfileConfig()

        assert config.profiles == {}
        assert config.default_profile_id is None
        assert config.global_settings == {}

    @patch("pathlib.Path.exists")
    @patch("builtins.open", new_callable=mock_open)
    def test_load_empty_yaml(self, mock_file, mock_exists):
        """Test loading an empty YAML file."""
        mock_exists.return_value = True
        mock_file.return_value.read.return_value = ""

        config = LLMProfileConfig()

        assert config.profiles == {}
        assert config.default_profile_id is None

    @patch("pathlib.Path.cwd")
    @patch("pathlib.Path.exists")
    def test_load_minimal_yaml(self, mock_exists, mock_cwd):
        """Test loading minimal valid YAML configuration."""
        mock_cwd.return_value = Path("/test")
        mock_exists.return_value = True

        yaml_content = """
default: prod
profiles:
  prod:
    name: Production
    description: Production profile
    providers:
      - name: Claude
        provider: anthropic
        model: claude-sonnet-4-20250514
"""
        mock_data = yaml.safe_load(yaml_content)

        with patch("builtins.open", mock_open(read_data=yaml_content)):
            with patch("yaml.safe_load", return_value=mock_data):
                config = LLMProfileConfig()

        assert config.default_profile_id == "prod"
        assert "prod" in config.profiles
        assert config.profiles["prod"].profile_id == "prod"
        assert config.profiles["prod"].name == "Production"
        assert len(config.profiles["prod"].providers) == 1
        assert config.profiles["prod"].providers[0].name == "Claude"

    @patch("pathlib.Path.cwd")
    @patch("pathlib.Path.exists")
    def test_load_full_yaml(self, mock_exists, mock_cwd):
        """Test loading full YAML with multiple profiles and providers."""
        mock_cwd.return_value = Path("/test")
        mock_exists.return_value = True

        yaml_content = """
default: prod
global:
  timeout: 120
  rate_limit:
    requests_per_minute: 60
profiles:
  prod:
    name: Production
    description: Production environment
    providers:
      - name: Claude Sonnet
        provider: anthropic
        model: claude-sonnet-4-20250514
        api_key_env: ANTHROPIC_API_KEY
        timeout: 60
        default: true
      - name: GPT-4
        provider: openai
        model: gpt-4o
        api_key: sk-test-key
        base_url: https://api.openai.com/v1
        timeout: 90
        default: false
  dev:
    name: Development
    description: Development environment
    providers:
      - name: Local Ollama
        provider: ollama
        model: llama3
        base_url: http://localhost:11434
"""
        mock_data = yaml.safe_load(yaml_content)

        with patch("builtins.open", mock_open(read_data=yaml_content)):
            with patch("yaml.safe_load", return_value=mock_data):
                config = LLMProfileConfig()

        # Check default profile
        assert config.default_profile_id == "prod"

        # Check global settings
        assert config.global_settings["timeout"] == 120
        assert config.global_settings["rate_limit"]["requests_per_minute"] == 60

        # Check prod profile
        assert "prod" in config.profiles
        prod = config.profiles["prod"]
        assert prod.name == "Production"
        assert len(prod.providers) == 2
        assert prod.providers[0].name == "Claude Sonnet"
        assert prod.providers[0].api_key_env == "ANTHROPIC_API_KEY"
        assert prod.providers[0].default is True
        assert prod.providers[1].name == "GPT-4"
        assert prod.providers[1].api_key == "sk-test-key"

        # Check dev profile
        assert "dev" in config.profiles
        dev = config.profiles["dev"]
        assert dev.name == "Development"
        assert len(dev.providers) == 1
        assert dev.providers[0].provider == "ollama"
        assert dev.providers[0].base_url == "http://localhost:11434"

    @patch("pathlib.Path.cwd")
    @patch("pathlib.Path.exists")
    def test_load_handles_missing_optional_fields(self, mock_exists, mock_cwd):
        """Test loading YAML with missing optional fields uses defaults."""
        mock_cwd.return_value = Path("/test")
        mock_exists.return_value = True

        yaml_content = """
profiles:
  minimal:
    providers:
      - provider: anthropic
        model: claude-sonnet-4-20250514
"""
        mock_data = yaml.safe_load(yaml_content)

        with patch("builtins.open", mock_open(read_data=yaml_content)):
            with patch("yaml.safe_load", return_value=mock_data):
                config = LLMProfileConfig()

        assert "minimal" in config.profiles
        minimal = config.profiles["minimal"]
        assert minimal.name == "minimal"  # Uses profile_id as fallback
        assert minimal.description == ""
        assert minimal.providers[0].name == ""
        assert minimal.providers[0].timeout == 60
        assert minimal.providers[0].default is False

    @patch("pathlib.Path.cwd")
    @patch("pathlib.Path.exists")
    @patch("builtins.open", new_callable=mock_open)
    def test_load_handles_yaml_error(self, mock_file, mock_exists, mock_cwd, capsys):
        """Test loading handles YAML parsing errors gracefully."""
        mock_cwd.return_value = Path("/test")
        mock_exists.return_value = True

        with patch("yaml.safe_load") as mock_yaml:
            mock_yaml.side_effect = yaml.YAMLError("Invalid YAML")
            config = LLMProfileConfig()

        # Should create empty config and print warning
        assert config.profiles == {}
        captured = capsys.readouterr()
        assert "Warning: Failed to load LLM profiles" in captured.out

    def test_secret_placeholders_resolve_lazily_and_round_trip_raw(self, tmp_path, monkeypatch):
        """Credential reads resolve env vars without persisting their values."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-runtime-secret")
        config_path = tmp_path / ".llm_providers.yaml"
        config_path.write_text(
            """
default: prod
custom_top_level: keep-top
profiles:
  prod:
    name: ${PROFILE_NAME:-Production}
    description: Test
    custom_profile_field: keep-profile
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-4o
        api_key: ${OPENAI_API_KEY}
        base_url: ${OPENAI_BASE_URL:-https://api.openai.test/v1}
        temperature: 0.2
        default: true
"""
        )

        config = LLMProfileConfig()
        provider = config.profiles["prod"].providers[0]

        assert provider.api_key == "sk-runtime-secret"
        assert provider.base_url == "https://api.openai.test/v1"
        assert config.profiles["prod"].name == "Production"
        assert provider.to_dict()["api_key"] == "${OPENAI_API_KEY}"

        config.save()
        saved_text = config_path.read_text()
        saved = yaml.safe_load(saved_text)
        assert "sk-runtime-secret" not in saved_text
        assert saved["profiles"]["prod"]["providers"][0]["api_key"] == "${OPENAI_API_KEY}"
        assert (
            saved["profiles"]["prod"]["providers"][0]["base_url"]
            == "${OPENAI_BASE_URL:-https://api.openai.test/v1}"
        )
        assert saved["profiles"]["prod"]["name"] == "${PROFILE_NAME:-Production}"
        assert saved["custom_top_level"] == "keep-top"
        assert saved["profiles"]["prod"]["custom_profile_field"] == "keep-profile"
        assert saved["profiles"]["prod"]["providers"][0]["temperature"] == 0.2

    def test_malformed_later_profile_rejects_entire_document(self, tmp_path, monkeypatch, capsys):
        """A bad later entry cannot leave earlier profiles partially loaded."""
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / ".llm_providers.yaml"
        malformed = """
default: good
global:
  timeout: 90
profiles:
  good:
    name: Good
    description: valid
    providers: []
  broken:
    name: Broken
    providers:
      - null
"""
        config_path.write_text(malformed)

        config = LLMProfileConfig()

        assert config.profiles == {}
        assert config.default_profile_id is None
        assert config.global_settings == {}
        assert config.load_error
        assert "Failed to load LLM profiles" in capsys.readouterr().out
        with pytest.raises(ValueError, match="Refusing to overwrite"):
            config.save()
        assert config_path.read_text() == malformed

    def test_has_profiles(self):
        """Test has_profiles() method."""
        with patch("pathlib.Path.exists", return_value=False):
            config = LLMProfileConfig()
            assert config.has_profiles() is False

            # Add a profile
            profile = LLMProfile(
                profile_id="test",
                name="Test",
                description="Test",
            )
            config.add_profile(profile)
            assert config.has_profiles() is True

    def test_list_profiles(self):
        """Test list_profiles() method."""
        with patch("pathlib.Path.exists", return_value=False):
            config = LLMProfileConfig()

            assert config.list_profiles() == []

            profile1 = LLMProfile(profile_id="prod", name="Production", description="Prod")
            profile2 = LLMProfile(profile_id="dev", name="Development", description="Dev")
            config.add_profile(profile1)
            config.add_profile(profile2)

            profiles = config.list_profiles()
            assert len(profiles) == 2
            assert "prod" in profiles
            assert "dev" in profiles

    def test_get_profile_by_id(self):
        """Test get_profile() with specific profile ID."""
        with patch("pathlib.Path.exists", return_value=False):
            config = LLMProfileConfig()
            profile = LLMProfile(profile_id="test", name="Test", description="Test")
            config.add_profile(profile)

            result = config.get_profile("test")
            assert result is not None
            assert result.profile_id == "test"

    def test_get_profile_default(self):
        """Test get_profile() without ID returns default profile."""
        with patch("pathlib.Path.exists", return_value=False):
            config = LLMProfileConfig()
            profile1 = LLMProfile(profile_id="prod", name="Production", description="Prod")
            profile2 = LLMProfile(profile_id="dev", name="Development", description="Dev")
            config.add_profile(profile1)
            config.add_profile(profile2)
            config.set_default_profile("dev")

            result = config.get_profile()
            assert result is not None
            assert result.profile_id == "dev"

    def test_get_profile_none_when_not_found(self):
        """Test get_profile() returns None when profile not found."""
        with patch("pathlib.Path.exists", return_value=False):
            config = LLMProfileConfig()

            result = config.get_profile("nonexistent")
            assert result is None

    def test_get_profile_none_when_no_default(self):
        """Test get_profile() returns None when no default set."""
        with patch("pathlib.Path.exists", return_value=False):
            config = LLMProfileConfig()
            profile = LLMProfile(profile_id="test", name="Test", description="Test")
            config.add_profile(profile)

            result = config.get_profile()  # No ID, no default
            assert result is None

    def test_add_profile(self):
        """Test add_profile() adds new profile."""
        with patch("pathlib.Path.exists", return_value=False):
            config = LLMProfileConfig()
            profile = LLMProfile(profile_id="new", name="New", description="New profile")

            config.add_profile(profile)

            assert "new" in config.profiles
            assert config.profiles["new"] == profile

    def test_add_profile_updates_existing(self):
        """Test add_profile() updates existing profile with same ID."""
        with patch("pathlib.Path.exists", return_value=False):
            config = LLMProfileConfig()
            profile1 = LLMProfile(profile_id="test", name="Original", description="Original")
            profile2 = LLMProfile(profile_id="test", name="Updated", description="Updated")

            config.add_profile(profile1)
            assert config.profiles["test"].name == "Original"

            config.add_profile(profile2)
            assert config.profiles["test"].name == "Updated"

    def test_remove_profile(self):
        """Test remove_profile() removes profile."""
        with patch("pathlib.Path.exists", return_value=False):
            config = LLMProfileConfig()
            profile = LLMProfile(profile_id="test", name="Test", description="Test")
            config.add_profile(profile)

            assert "test" in config.profiles
            config.remove_profile("test")
            assert "test" not in config.profiles

    def test_remove_profile_clears_default(self):
        """Test remove_profile() clears default if removing default profile."""
        with patch("pathlib.Path.exists", return_value=False):
            config = LLMProfileConfig()
            profile = LLMProfile(profile_id="test", name="Test", description="Test")
            config.add_profile(profile)
            config.set_default_profile("test")

            assert config.default_profile_id == "test"
            config.remove_profile("test")
            assert config.default_profile_id is None

    def test_remove_profile_nonexistent(self):
        """Test remove_profile() handles nonexistent profile gracefully."""
        with patch("pathlib.Path.exists", return_value=False):
            config = LLMProfileConfig()
            # Should not raise error
            config.remove_profile("nonexistent")

    def test_set_default_profile(self):
        """Test set_default_profile() sets default."""
        with patch("pathlib.Path.exists", return_value=False):
            config = LLMProfileConfig()
            profile = LLMProfile(profile_id="test", name="Test", description="Test")
            config.add_profile(profile)

            config.set_default_profile("test")
            assert config.default_profile_id == "test"

    def test_set_default_profile_raises_on_nonexistent(self):
        """Test set_default_profile() raises error for nonexistent profile."""
        with patch("pathlib.Path.exists", return_value=False):
            config = LLMProfileConfig()

            with pytest.raises(ValueError, match="Profile 'nonexistent' not found"):
                config.set_default_profile("nonexistent")

    def test_save_creates_yaml_with_private_permissions(self, tmp_path, monkeypatch):
        """save() atomically creates a mode-0600 YAML file."""
        monkeypatch.chdir(tmp_path)
        config = LLMProfileConfig()
        provider = LLMProviderConfig(
            name="Test",
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            default=True,
        )
        profile = LLMProfile(
            profile_id="test",
            name="Test Profile",
            description="Test",
            providers=[provider],
        )
        config.add_profile(profile)
        config.set_default_profile("test")
        config.global_settings = {"timeout": 120}

        config.save()

        config_path = tmp_path / ".llm_providers.yaml"
        data = yaml.safe_load(config_path.read_text())
        assert data["default"] == "test"
        assert "test" in data["profiles"]
        assert data["profiles"]["test"]["name"] == "Test Profile"
        assert data["global"] == {"timeout": 120}
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o600

    def test_save_without_fchmod_uses_portable_chmod_fallback(self, tmp_path, monkeypatch):
        """Windows Python builds do not expose os.fchmod."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("testmcpy.llm_profiles.os.fchmod", None)
        config = LLMProfileConfig()
        config.add_profile(LLMProfile(profile_id="test", name="Test", description=""))

        config.save()

        config_path = tmp_path / ".llm_providers.yaml"
        assert yaml.safe_load(config_path.read_text())["profiles"]["test"]["name"] == "Test"
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o600

    def test_save_creates_private_backup(self, tmp_path, monkeypatch):
        """Replacing a config keeps a private backup of the previous bytes."""
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / ".llm_providers.yaml"
        original = "default: old\nprofiles: {}\n"
        config_path.write_text(original)
        config = LLMProfileConfig()
        config.default_profile_id = "new"

        config.save()

        backup_path = tmp_path / ".llm_providers.yaml.backup"
        assert backup_path.read_text() == original
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(backup_path.stat().st_mode) == 0o600

    def test_save_uses_fallback_when_parent_cannot_atomically_replace(
        self,
        tmp_path,
        monkeypatch,
    ):
        """A writable file in a non-writable directory still needs fallback."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        fallback_dir = workspace / ".testmcpy"
        fallback_dir.mkdir()
        primary = workspace / ".llm_providers.yaml"
        primary.write_text("default: old\nprofiles: {}\n")
        primary.chmod(0o600)
        monkeypatch.chdir(workspace)
        config = LLMProfileConfig()
        config.default_profile_id = "new"

        real_access = os.access

        def atomic_access(path, mode):
            if Path(path) == workspace and mode & os.W_OK:
                return False
            return real_access(path, mode)

        monkeypatch.setattr("testmcpy.llm_profiles.os.access", atomic_access)
        config.save()

        fallback = fallback_dir / ".llm_providers.yaml"
        assert yaml.safe_load(fallback.read_text())["default"] == "new"
        assert yaml.safe_load(primary.read_text())["default"] == "old"

    def test_save_writes_through_symlink_without_replacing_it(self, tmp_path, monkeypatch):
        """Atomic saving preserves a configured symlink and updates its target."""
        workspace = tmp_path / "workspace"
        target_dir = tmp_path / "config"
        workspace.mkdir()
        target_dir.mkdir()
        target = target_dir / "providers.yaml"
        target.write_text("default: old\nprofiles: {}\n")
        link = workspace / ".llm_providers.yaml"
        link.symlink_to(target)
        monkeypatch.chdir(workspace)
        config = LLMProfileConfig()
        config.default_profile_id = "new"

        config.save()

        assert link.is_symlink()
        assert link.resolve() == target
        assert yaml.safe_load(target.read_text())["default"] == "new"

    def test_save_backup_failure_leaves_original_untouched(self, tmp_path, monkeypatch):
        """A failed backup aborts before the live config can be replaced."""
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / ".llm_providers.yaml"
        original = "default: old\nprofiles: {}\n"
        config_path.write_text(original)
        config = LLMProfileConfig()

        with patch("testmcpy.llm_profiles._atomic_copy", side_effect=OSError("backup failed")):
            with pytest.raises(Exception, match="Failed to save LLM profiles"):
                config.save()

        assert config_path.read_text() == original

    def test_save_handles_write_failure_without_truncation(self, tmp_path, monkeypatch):
        """A serializer failure cannot truncate the live configuration."""
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / ".llm_providers.yaml"
        original = "default: old\nprofiles: {}\n"
        config_path.write_text(original)
        config = LLMProfileConfig()

        with patch("yaml.dump") as mock_dump:
            mock_dump.side_effect = OSError("disk full")
            with pytest.raises(Exception, match="Failed to save LLM profiles"):
                config.save()

        assert config_path.read_text() == original
        assert not list(tmp_path.glob("*.tmp"))

    def test_save_restores_backup_if_replace_removes_target(self, tmp_path, monkeypatch):
        """An unusual destructive replace failure restores the original bytes."""
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / ".llm_providers.yaml"
        original = "default: old\nprofiles: {}\n"
        config_path.write_text(original)
        config = LLMProfileConfig()
        real_replace = os.replace
        failed_once = False

        def destructive_replace(source, destination):
            nonlocal failed_once
            if Path(destination) == config_path and not failed_once:
                failed_once = True
                config_path.unlink()
                raise OSError("replace failed after removing target")
            return real_replace(source, destination)

        with patch("testmcpy.llm_profiles.os.replace", side_effect=destructive_replace):
            with pytest.raises(Exception, match="Failed to save LLM profiles"):
                config.save()

        assert config_path.read_text() == original
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    @patch("testmcpy.llm_profiles._llm_profile_config", None)
    @patch("pathlib.Path.exists", return_value=False)
    def test_get_llm_profile_config_singleton(self, mock_exists):
        """Test get_llm_profile_config() creates singleton instance."""
        # Reset global
        import testmcpy.llm_profiles

        testmcpy.llm_profiles._llm_profile_config = None

        config1 = get_llm_profile_config()
        config2 = get_llm_profile_config()

        assert config1 is config2

    @patch("pathlib.Path.exists", return_value=False)
    def test_reload_llm_profile_config(self, mock_exists):
        """Test reload_llm_profile_config() creates new instance."""
        import testmcpy.llm_profiles

        testmcpy.llm_profiles._llm_profile_config = None

        config1 = get_llm_profile_config()
        config2 = reload_llm_profile_config()

        assert config1 is not config2

    def test_singleton_reloads_when_config_path_changes(self, tmp_path, monkeypatch):
        """Changing workspace cannot reuse a singleton loaded from another CWD."""
        import testmcpy.llm_profiles

        workspace_a = tmp_path / "a"
        workspace_b = tmp_path / "b"
        workspace_a.mkdir()
        workspace_b.mkdir()
        (workspace_a / ".llm_providers.yaml").write_text(
            "default: a\nprofiles:\n  a: {name: A, description: '', providers: []}\n"
        )
        (workspace_b / ".llm_providers.yaml").write_text(
            "default: b\nprofiles:\n  b: {name: B, description: '', providers: []}\n"
        )
        monkeypatch.setattr(testmcpy.llm_profiles, "_llm_profile_config", None)

        monkeypatch.chdir(workspace_a)
        config_a = get_llm_profile_config()
        monkeypatch.chdir(workspace_b)
        config_b = get_llm_profile_config()

        assert config_a is not config_b
        assert config_a.get_profile().profile_id == "a"
        assert config_b.get_profile().profile_id == "b"

    @pytest.mark.parametrize(
        ("configured_provider", "requested_provider"),
        [("assistant", "chatbot"), ("bedrock", "aws-bedrock")],
    )
    def test_runtime_provider_aliases_share_profile_config(
        self,
        tmp_path,
        monkeypatch,
        configured_provider,
        requested_provider,
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".llm_providers.yaml").write_text(
            f"""
default: prod
profiles:
  prod:
    name: Production
    providers:
      - name: Provider
        provider: {configured_provider}
        model: test-model
        api_token: profile-token-for-alias
"""
        )
        reload_llm_profile_config()

        resolved = resolve_llm_provider_config(requested_provider, "test-model")

        assert resolved["api_token"] == "profile-token-for-alias"

    def test_runtime_profile_secrets_are_registered_with_scrubber(self, tmp_path, monkeypatch):
        from testmcpy.scrubber import scrub_text

        monkeypatch.chdir(tmp_path)
        secret = "profile-direct-secret-123-unique"
        (tmp_path / ".llm_providers.yaml").write_text(
            f"""
default: prod
profiles:
  prod:
    name: Production
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-test
        api_key: {secret}
"""
        )
        reload_llm_profile_config()

        assert resolve_llm_provider_config("openai", "gpt-test")["api_key"] == secret
        assert secret not in scrub_text(f"upstream echoed {secret}")

    def test_blank_profile_id_uses_default_runtime_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".llm_providers.yaml").write_text(
            """
default: prod
profiles:
  prod:
    name: Production
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-test
        api_key: default-profile-secret
"""
        )
        reload_llm_profile_config()

        resolved = resolve_llm_provider_config("openai", "gpt-test", "")

        assert resolved["api_key"] == "default-profile-secret"

    def test_named_profile_selects_provider_model_and_runtime_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".llm_providers.yaml").write_text(
            """
default: default
profiles:
  default:
    name: Default
    providers:
      - {name: Claude, provider: anthropic, model: claude-test}
  selected:
    name: Selected
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-test
        api_key: selected-profile-key
"""
        )
        reload_llm_profile_config()

        provider, model, runtime = resolve_llm_provider_selection(profile_id="selected")

        assert (provider, model) == ("openai", "gpt-test")
        assert runtime["api_key"] == "selected-profile-key"

    @pytest.mark.parametrize(
        ("provider", "model", "ambient_key", "profile_key"),
        [
            ("openai", "gpt-test", "OPENAI_API_KEY", "PROFILE_OPENAI_KEY"),
            ("anthropic", "claude-test", "ANTHROPIC_API_KEY", "PROFILE_ANTHROPIC_KEY"),
            ("codex-sdk", "codex-test", "OPENAI_API_KEY", "PROFILE_CODEX_KEY"),
            (
                "claude-sdk",
                "claude-sdk-test",
                "CLAUDE_CODE_OAUTH_TOKEN",
                "PROFILE_CLAUDE_KEY",
            ),
        ],
    )
    def test_explicit_profile_unresolved_api_key_env_rejects_ambient_fallback(
        self,
        tmp_path,
        monkeypatch,
        provider,
        model,
        ambient_key,
        profile_key,
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(ambient_key, "ambient-key-must-not-be-used")
        monkeypatch.delenv(profile_key, raising=False)
        (tmp_path / ".llm_providers.yaml").write_text(
            f"""
profiles:
  isolated:
    name: Isolated
    providers:
      - name: Provider
        provider: {provider}
        model: {model}
        api_key_env: {profile_key}
"""
        )
        reload_llm_profile_config()

        with pytest.raises(LLMProfileConfigError, match="resolved to an empty value"):
            resolve_llm_provider_config(provider, model, "isolated")

    def test_default_profile_unresolved_key_rejects_ambient_fallback(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("OPENAI_API_KEY", "ambient-key-must-not-be-used")
        monkeypatch.delenv("PROFILE_OPENAI_KEY", raising=False)
        (tmp_path / ".llm_providers.yaml").write_text(
            """
default: isolated
profiles:
  isolated:
    name: Isolated
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-test
        api_key_env: PROFILE_OPENAI_KEY
"""
        )
        reload_llm_profile_config()

        with pytest.raises(LLMProfileConfigError, match="resolved to an empty value"):
            resolve_llm_provider_config("openai", "gpt-test")

    def test_dangling_default_profile_is_a_configuration_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".llm_providers.yaml").write_text(
            "default: missing\nprofiles:\n  prod: {name: Production, providers: []}\n"
        )
        reload_llm_profile_config()

        with pytest.raises(LLMProfileConfigError, match="Default LLM profile 'missing'"):
            resolve_llm_provider_selection(
                fallback_provider="openai",
                fallback_model="gpt-test",
            )
        with pytest.raises(LLMProfileConfigError, match="Default LLM profile 'missing'"):
            resolve_llm_provider_config("openai", "gpt-test")

    def test_explicit_profile_provider_mismatch_is_a_configuration_error(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".llm_providers.yaml").write_text(
            """
profiles:
  isolated:
    name: Isolated
    providers:
      - name: Anthropic
        provider: anthropic
        model: claude-test
"""
        )
        reload_llm_profile_config()

        with pytest.raises(LLMProfileConfigError, match="no provider matching 'openai'"):
            resolve_llm_provider_selection("openai", "gpt-test", "isolated")
        with pytest.raises(LLMProfileConfigError, match="no provider matching 'openai'"):
            resolve_llm_provider_config("openai", "gpt-test", "isolated")

    def test_explicit_profile_unresolved_api_key_expression_rejects_ambient_fallback(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("OPENAI_API_KEY", "ambient-key-must-not-be-used")
        monkeypatch.delenv("PROFILE_OPENAI_KEY", raising=False)
        (tmp_path / ".llm_providers.yaml").write_text(
            """
profiles:
  isolated:
    name: Isolated
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-test
        api_key: ${PROFILE_OPENAI_KEY}
"""
        )
        reload_llm_profile_config()

        with pytest.raises(LLMProfileConfigError, match="resolved to an empty value"):
            resolve_llm_provider_config("openai", "gpt-test", "isolated")

    def test_explicit_profile_without_api_key_binding_can_use_provider_defaults(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".llm_providers.yaml").write_text(
            """
profiles:
  host-default:
    name: Host default
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-test
"""
        )
        reload_llm_profile_config()

        assert resolve_llm_provider_config("openai", "gpt-test", "host-default") == {"timeout": 60}

    def test_explicit_missing_profile_never_falls_back_to_global_provider(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        reload_llm_profile_config()

        with pytest.raises(ValueError, match="LLM profile 'missing' was not found"):
            resolve_llm_provider_selection(
                profile_id="missing",
                fallback_provider="openai",
                fallback_model="gpt-fallback",
            )

    def test_direct_runtime_config_rejects_explicit_missing_profile(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        reload_llm_profile_config()

        with pytest.raises(LLMProfileNotFoundError, match="LLM profile 'missing' was not found"):
            resolve_llm_provider_config("openai", "gpt-fallback", "missing")

    def test_blank_profile_id_uses_global_fallback(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        reload_llm_profile_config()

        provider, model, runtime = resolve_llm_provider_selection(
            profile_id="",
            fallback_provider="openai",
            fallback_model="gpt-fallback",
        )

        assert (provider, model, runtime) == ("openai", "gpt-fallback", {})

    def test_runtime_selection_rejects_malformed_profile_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".llm_providers.yaml").write_text("profiles: [not-a-mapping]\n")
        reload_llm_profile_config()

        with pytest.raises(RuntimeError, match="Invalid LLM profile configuration"):
            resolve_llm_provider_selection(
                profile_id="missing",
                fallback_provider="openai",
                fallback_model="gpt-fallback",
            )

    @patch("pathlib.Path.exists", return_value=False)
    def test_load_llm_profile_with_id(self, mock_exists):
        """Test load_llm_profile() loads specific profile."""
        import testmcpy.llm_profiles

        testmcpy.llm_profiles._llm_profile_config = None

        config = get_llm_profile_config()
        profile = LLMProfile(profile_id="test", name="Test", description="Test")
        config.add_profile(profile)

        result = load_llm_profile("test")
        assert result is not None
        assert result.profile_id == "test"

    @patch("pathlib.Path.exists", return_value=False)
    def test_load_llm_profile_default(self, mock_exists):
        """Test load_llm_profile() loads default profile when no ID given."""
        import testmcpy.llm_profiles

        testmcpy.llm_profiles._llm_profile_config = None

        config = get_llm_profile_config()
        profile = LLMProfile(profile_id="prod", name="Production", description="Prod")
        config.add_profile(profile)
        config.set_default_profile("prod")

        result = load_llm_profile()
        assert result is not None
        assert result.profile_id == "prod"

    @patch("pathlib.Path.exists", return_value=False)
    def test_list_available_llm_profiles(self, mock_exists):
        """Test list_available_llm_profiles() returns all profile IDs."""
        import testmcpy.llm_profiles

        testmcpy.llm_profiles._llm_profile_config = None

        config = get_llm_profile_config()
        profile1 = LLMProfile(profile_id="prod", name="Production", description="Prod")
        profile2 = LLMProfile(profile_id="dev", name="Development", description="Dev")
        config.add_profile(profile1)
        config.add_profile(profile2)

        result = list_available_llm_profiles()
        assert len(result) == 2
        assert "prod" in result
        assert "dev" in result

    @patch("pathlib.Path.exists", return_value=False)
    def test_get_default_llm_profile_id(self, mock_exists):
        """Test get_default_llm_profile_id() returns default ID."""
        import testmcpy.llm_profiles

        testmcpy.llm_profiles._llm_profile_config = None

        config = get_llm_profile_config()
        profile = LLMProfile(profile_id="prod", name="Production", description="Prod")
        config.add_profile(profile)
        config.set_default_profile("prod")

        result = get_default_llm_profile_id()
        assert result == "prod"

    @patch("pathlib.Path.exists", return_value=False)
    def test_get_default_llm_profile_id_none(self, mock_exists):
        """Test get_default_llm_profile_id() returns None when no default."""
        import testmcpy.llm_profiles

        testmcpy.llm_profiles._llm_profile_config = None

        get_llm_profile_config()

        result = get_default_llm_profile_id()
        assert result is None


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    @patch("pathlib.Path.cwd")
    @patch("pathlib.Path.exists")
    def test_profile_without_providers(self, mock_exists, mock_cwd):
        """Test profile with empty providers list."""
        mock_cwd.return_value = Path("/test")
        mock_exists.return_value = True

        yaml_content = """
profiles:
  empty:
    name: Empty Profile
    description: No providers
    providers: []
"""
        mock_data = yaml.safe_load(yaml_content)

        with patch("builtins.open", mock_open(read_data=yaml_content)):
            with patch("yaml.safe_load", return_value=mock_data):
                config = LLMProfileConfig()

        assert "empty" in config.profiles
        assert len(config.profiles["empty"].providers) == 0
        assert config.profiles["empty"].get_default_provider() is None

    @patch("pathlib.Path.cwd")
    @patch("pathlib.Path.exists")
    def test_provider_with_both_api_key_methods(self, mock_exists, mock_cwd):
        """Test provider with both api_key and api_key_env specified."""
        mock_cwd.return_value = Path("/test")
        mock_exists.return_value = True

        yaml_content = """
profiles:
  test:
    name: Test
    description: Test
    providers:
      - name: Dual Key
        provider: anthropic
        model: claude-sonnet-4-20250514
        api_key: direct-key
        api_key_env: ENV_KEY
"""
        mock_data = yaml.safe_load(yaml_content)

        with patch("builtins.open", mock_open(read_data=yaml_content)):
            with patch("yaml.safe_load", return_value=mock_data):
                config = LLMProfileConfig()

        provider = config.profiles["test"].providers[0]
        assert provider.api_key == "direct-key"
        assert provider.api_key_env == "ENV_KEY"

    def test_provider_config_with_zero_timeout(self):
        """Test provider config with zero timeout."""
        config = LLMProviderConfig(
            name="Test",
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            timeout=0,
        )

        assert config.timeout == 0

    def test_provider_config_with_negative_timeout(self):
        """Test provider config with negative timeout (should be allowed)."""
        config = LLMProviderConfig(
            name="Test",
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            timeout=-1,
        )

        assert config.timeout == -1

    @patch("pathlib.Path.cwd")
    @patch("pathlib.Path.exists")
    def test_yaml_with_no_profiles_key(self, mock_exists, mock_cwd):
        """Test YAML without 'profiles' key."""
        mock_cwd.return_value = Path("/test")
        mock_exists.return_value = True

        yaml_content = """
default: prod
global:
  timeout: 60
"""
        mock_data = yaml.safe_load(yaml_content)

        with patch("builtins.open", mock_open(read_data=yaml_content)):
            with patch("yaml.safe_load", return_value=mock_data):
                config = LLMProfileConfig()

        assert config.default_profile_id == "prod"
        assert config.global_settings == {"timeout": 60}
        assert config.profiles == {}

    def test_profile_id_with_special_characters(self):
        """Test profile with special characters in ID."""
        profile = LLMProfile(
            profile_id="my-profile_v2.0",
            name="Special Profile",
            description="Has special chars",
        )

        assert profile.profile_id == "my-profile_v2.0"

    def test_provider_name_with_unicode(self):
        """Test provider with unicode characters in name."""
        config = LLMProviderConfig(
            name="Provider 测试",
            provider="anthropic",
            model="claude-sonnet-4-20250514",
        )

        assert config.name == "Provider 测试"

    @patch("pathlib.Path.cwd")
    @patch("pathlib.Path.exists")
    def test_yaml_with_null_required_values_is_rejected(self, mock_exists, mock_cwd, capsys):
        """Explicit nulls in required string fields reject the whole document."""
        mock_cwd.return_value = Path("/test")
        mock_exists.return_value = True

        yaml_content = """
default: null
profiles:
  test:
    name: Test
    description: null
    providers:
      - name: Provider
        provider: anthropic
        model: claude-sonnet-4-20250514
        api_key: null
        base_url: null
"""
        mock_data = yaml.safe_load(yaml_content)

        with patch("builtins.open", mock_open(read_data=yaml_content)):
            with patch("yaml.safe_load", return_value=mock_data):
                config = LLMProfileConfig()

        assert config.default_profile_id is None
        assert config.profiles == {}
        assert "description must be a string" in capsys.readouterr().out
