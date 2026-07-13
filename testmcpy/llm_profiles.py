"""
LLM Provider Profile Management.

Manages multiple LLM provider configurations with profile-based organization.
Similar to MCP profiles, allows users to define different LLM setups for different environments.
"""

import copy
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

LLM_PROFILE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._~-]*$"
LLM_PROFILE_ID_MAX_LENGTH = 64
_ENV_REFERENCE_VALUE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?\}$")


def validate_assistant_endpoint_path(value: str, field_name: str) -> None:
    """Require a same-origin absolute path for Assistant API endpoints."""
    if _ENV_REFERENCE_VALUE.fullmatch(value):
        return
    parsed = urlsplit(value)
    if (
        not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or any(ord(char) < 0x20 for char in value)
        or parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"Assistant {field_name} must be a same-origin path starting with one '/'")


def _resolve_llm_providers_path() -> Path:
    """Read path: prefer ``.testmcpy/.llm_providers.yaml`` when present
    (writable persistent fallback for Docker ``:ro`` bind mounts),
    else the standard CWD location. SC-108367 #3.
    """
    fallback = Path.cwd() / ".testmcpy" / ".llm_providers.yaml"
    if fallback.exists():
        return fallback
    return Path.cwd() / ".llm_providers.yaml"


def _resolve_writable_path(primary_path: Path) -> tuple[Path, bool]:
    """Pick where to write a config file.

    Returns ``(save_path, using_fallback)``. ``save_path`` is the primary
    path when writable, else ``.testmcpy/<filename>`` next to the DB.
    Atomic replacement needs a writable/searchable parent directory. We also
    honor a non-writable target as the ``:ro`` single-file bind-mount signal.
    Symlinks are written through to preserve the link instead of replacing it.
    """

    def _writable(p: Path) -> bool:
        target = p.resolve(strict=False) if p.is_symlink() else p
        parent_writable = os.access(target.parent, os.W_OK | os.X_OK)
        if not target.exists():
            return parent_writable
        return parent_writable and os.access(target, os.W_OK)

    if _writable(primary_path):
        save_path = (
            primary_path.resolve(strict=False) if primary_path.is_symlink() else primary_path
        )
        return save_path, False
    persistent_dir = Path.cwd() / ".testmcpy"
    try:
        persistent_dir.mkdir(exist_ok=True)
    except OSError:
        pass
    return persistent_dir / primary_path.name, True


def _substitute_env_vars(value: Any) -> Any:
    """
    Recursively substitute environment variables in config values.

    Supports ${VAR_NAME} and ${VAR_NAME:-default_value} syntax.
    """
    if isinstance(value, str):
        # Match ${VAR_NAME} or ${VAR_NAME:-default}
        pattern = r"\$\{([^}:]+)(?::-([^}]*))?\}"

        def replace_var(match):
            var_name = match.group(1)
            default_value = match.group(2) if match.group(2) is not None else ""
            return os.environ.get(var_name, default_value)

        return re.sub(pattern, replace_var, value)

    elif isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}

    elif isinstance(value, list):
        return [_substitute_env_vars(item) for item in value]

    return value


def _absolute_path(path: Path) -> Path:
    """Return a stable path identity without requiring the file to exist."""
    return path.expanduser().absolute()


def _require_mapping(value: Any, context: str) -> dict[str, Any]:
    """Validate a YAML mapping and return it with a useful error on failure."""
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a mapping")
    return value


def _require_optional_string(value: Any, context: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{context} must be a string or null")
    return value


def _secure_temp_file(fd: int, path: Path) -> None:
    """Restrict a temporary profile file on Unix and Windows Python builds."""
    fchmod = getattr(os, "fchmod", None)
    if callable(fchmod):
        fchmod(fd, 0o600)
    else:
        os.chmod(path, 0o600)


def _atomic_copy(source: Path, destination: Path) -> None:
    """Copy a file through a mode-0600 temporary followed by atomic replace."""
    fd, temp_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temp_path = Path(temp_name)
    try:
        _secure_temp_file(fd, temp_path)
        with open(source, "rb") as source_file, os.fdopen(fd, "wb") as temp_file:
            fd = -1
            while chunk := source_file.read(1024 * 1024):
                temp_file.write(chunk)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, destination)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Durably write YAML without exposing a partial destination file."""
    fd, temp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temp_path = Path(temp_name)
    try:
        _secure_temp_file(fd, temp_path)
        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
            fd = -1
            yaml.dump(data, temp_file, default_flow_style=False, sort_keys=False)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        # Validate the generated document before it can replace the live config.
        with open(temp_path, encoding="utf-8") as temp_file:
            generated = yaml.safe_load(temp_file)
        if not isinstance(generated, dict):
            raise ValueError("Generated LLM profile configuration is not a mapping")

        os.replace(temp_path, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


@dataclass
class LLMProviderConfig:
    """Configuration for a single LLM provider."""

    name: str
    provider: str  # anthropic, openai, ollama, local, claude-sdk, assistant, ...
    model: str
    # Environment expressions remain raw in ``__dict__`` so serialization never
    # materializes secrets. ``__getattribute__`` resolves them only for callers
    # that explicitly consume a configured value.
    api_key: str | None = field(default=None, repr=False)
    api_key_env: str | None = None  # Environment variable name for API key
    base_url: str | None = None  # For OpenAI-compatible APIs or Ollama
    timeout: int = 60
    default: bool = False  # Mark this as default provider in the profile

    # AssistantProvider-specific fields
    workspace_hash: str | None = None
    domain: str | None = None
    api_token: str | None = field(default=None, repr=False)  # Assistant auth token
    api_secret: str | None = field(default=None, repr=False)  # Assistant auth secret
    api_url: str | None = None  # JWT endpoint for assistant auth
    conversations_path: str | None = None
    completions_path: str | None = None
    _extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    _LAZY_ENV_FIELDS = frozenset(
        {
            "name",
            "provider",
            "model",
            "api_key",
            "api_key_env",
            "base_url",
            "workspace_hash",
            "domain",
            "api_token",
            "api_secret",
            "api_url",
            "conversations_path",
            "completions_path",
        }
    )

    def __getattribute__(self, name: str) -> Any:
        value = object.__getattribute__(self, name)
        if name == "api_key" and value is None:
            env_name = object.__getattribute__(self, "api_key_env")
            resolved_env_name = _substitute_env_vars(env_name)
            if isinstance(resolved_env_name, str) and resolved_env_name:
                return os.environ.get(resolved_env_name)
        if name in object.__getattribute__(self, "_LAZY_ENV_FIELDS"):
            return _substitute_env_vars(value)
        return value

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result: dict[str, Any] = copy.deepcopy(object.__getattribute__(self, "_extra"))
        result.update(
            {
                "name": object.__getattribute__(self, "name"),
                "provider": object.__getattribute__(self, "provider"),
                "model": object.__getattribute__(self, "model"),
                "timeout": self.timeout,
                "default": self.default,
            }
        )
        # Only include non-None optional fields
        for fname in (
            "api_key",
            "api_key_env",
            "base_url",
            "workspace_hash",
            "domain",
            "api_token",
            "api_secret",
            "api_url",
            "conversations_path",
            "completions_path",
        ):
            # Bypass lazy credential resolution when writing configuration.
            val = object.__getattribute__(self, fname)
            if val is not None:
                result[fname] = copy.deepcopy(val)
        return result


@dataclass
class LLMProfile:
    """LLM profile containing multiple provider configurations."""

    profile_id: str
    name: str
    description: str
    providers: list[LLMProviderConfig] = field(default_factory=list)
    _extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    _LAZY_ENV_FIELDS = frozenset({"name", "description"})

    def __getattribute__(self, name: str) -> Any:
        value = object.__getattribute__(self, name)
        if name in object.__getattribute__(self, "_LAZY_ENV_FIELDS"):
            return _substitute_env_vars(value)
        return value

    def get_default_provider(self) -> LLMProviderConfig | None:
        """Get the default provider in this profile."""
        for provider in self.providers:
            if provider.default:
                return provider
        # If no default marked, return first one
        return self.providers[0] if self.providers else None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result = copy.deepcopy(self._extra)
        result.update(
            {
                "name": object.__getattribute__(self, "name"),
                "description": object.__getattribute__(self, "description"),
                "providers": [p.to_dict() for p in self.providers],
            }
        )
        return result


@dataclass
class LLMProfileConfig:
    """Container for all LLM profiles."""

    profiles: dict[str, LLMProfile] = field(default_factory=dict)
    default_profile_id: str | None = None
    global_settings: dict[str, Any] = field(default_factory=dict)
    _extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    _source_path: Path = field(init=False, repr=False, compare=False)
    _load_error: str | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Load profiles from .llm_providers.yaml if available."""
        self._source_path = _absolute_path(_resolve_llm_providers_path())
        self._load_profiles()

    def _load_profiles(self) -> None:
        """Load profiles from .llm_providers.yaml file.

        Prefers a writable fallback at ``.testmcpy/.llm_providers.yaml``
        when it exists (SC-108367 #3) so UI edits round-trip even when
        the primary file is on a read-only mount.
        """
        config_path = _resolve_llm_providers_path()
        self._source_path = _absolute_path(config_path)

        if not config_path.exists():
            return

        try:
            with open(config_path) as f:
                data = yaml.safe_load(f)

            if data is None:
                return

            data = _require_mapping(data, "LLM profile configuration")
            loaded_default = _require_optional_string(data.get("default"), "default")
            loaded_global = _require_mapping(data.get("global", {}), "global")
            profiles_data = _require_mapping(data.get("profiles", {}), "profiles")
            loaded_profiles: dict[str, LLMProfile] = {}

            for profile_id, profile_data in profiles_data.items():
                if not isinstance(profile_id, str):
                    raise ValueError("profile IDs must be strings")
                profile_data = _require_mapping(profile_data, f"profile '{profile_id}'")
                providers_data = profile_data.get("providers", [])
                if not isinstance(providers_data, list):
                    raise ValueError(f"profile '{profile_id}'.providers must be a list")

                providers = []
                for provider_index, provider_data in enumerate(providers_data):
                    provider_data = _require_mapping(
                        provider_data,
                        f"profile '{profile_id}'.providers[{provider_index}]",
                    )
                    # Pull auth block if present (assistant provider pattern)
                    auth_data = provider_data.get("auth", {})
                    if auth_data is None:
                        auth_data = {}
                    auth_data = _require_mapping(
                        auth_data,
                        f"profile '{profile_id}'.providers[{provider_index}].auth",
                    )

                    provider_name = provider_data.get("name", "")
                    provider_type = provider_data.get("provider", "anthropic")
                    model = provider_data.get("model", "")
                    for value, context in (
                        (provider_name, "name"),
                        (provider_type, "provider"),
                        (model, "model"),
                    ):
                        if not isinstance(value, str):
                            raise ValueError(
                                f"profile '{profile_id}'.providers[{provider_index}].{context} "
                                "must be a string"
                            )

                    timeout = provider_data.get("timeout", 60)
                    if isinstance(timeout, bool) or not isinstance(timeout, int):
                        raise ValueError(
                            f"profile '{profile_id}'.providers[{provider_index}].timeout "
                            "must be an integer"
                        )
                    is_default = provider_data.get("default", False)
                    if not isinstance(is_default, bool):
                        raise ValueError(
                            f"profile '{profile_id}'.providers[{provider_index}].default "
                            "must be a boolean"
                        )

                    optional_strings = {
                        field_name: _require_optional_string(
                            provider_data.get(field_name),
                            f"profile '{profile_id}'.providers[{provider_index}].{field_name}",
                        )
                        for field_name in (
                            "api_key",
                            "api_key_env",
                            "base_url",
                            "workspace_hash",
                            "domain",
                            "conversations_path",
                            "completions_path",
                        )
                    }
                    optional_strings["api_token"] = _require_optional_string(
                        provider_data.get("api_token") or auth_data.get("api_token"),
                        f"profile '{profile_id}'.providers[{provider_index}].api_token",
                    )
                    optional_strings["api_secret"] = _require_optional_string(
                        provider_data.get("api_secret") or auth_data.get("api_secret"),
                        f"profile '{profile_id}'.providers[{provider_index}].api_secret",
                    )
                    optional_strings["api_url"] = _require_optional_string(
                        provider_data.get("api_url") or auth_data.get("api_url"),
                        f"profile '{profile_id}'.providers[{provider_index}].api_url",
                    )

                    known_provider_fields = {
                        "name",
                        "provider",
                        "model",
                        "api_key",
                        "api_key_env",
                        "base_url",
                        "timeout",
                        "default",
                        "workspace_hash",
                        "domain",
                        "api_token",
                        "api_secret",
                        "api_url",
                        "conversations_path",
                        "completions_path",
                        "auth",
                    }
                    provider_extra = {
                        key: copy.deepcopy(value)
                        for key, value in provider_data.items()
                        if key not in known_provider_fields
                    }
                    unknown_auth = {
                        key: copy.deepcopy(value)
                        for key, value in auth_data.items()
                        if key not in {"api_token", "api_secret", "api_url"}
                    }
                    if unknown_auth:
                        provider_extra["auth"] = unknown_auth
                    provider = LLMProviderConfig(
                        name=provider_name,
                        provider=provider_type,
                        model=model,
                        timeout=timeout,
                        default=is_default,
                        **optional_strings,
                        _extra=provider_extra,
                    )
                    providers.append(provider)

                profile_name = profile_data.get("name", profile_id)
                description = profile_data.get("description", "")
                if not isinstance(profile_name, str):
                    raise ValueError(f"profile '{profile_id}'.name must be a string")
                if not isinstance(description, str):
                    raise ValueError(f"profile '{profile_id}'.description must be a string")
                profile = LLMProfile(
                    profile_id=profile_id,
                    name=profile_name,
                    description=description,
                    providers=providers,
                    _extra={
                        key: copy.deepcopy(value)
                        for key, value in profile_data.items()
                        if key not in {"name", "description", "providers"}
                    },
                )
                loaded_profiles[profile_id] = profile

            # Commit only after every profile validates. A malformed later entry
            # must not leave a partially loaded configuration in memory.
            self.default_profile_id = loaded_default
            self.global_settings = copy.deepcopy(loaded_global)
            self.profiles = loaded_profiles
            self._extra = {
                key: copy.deepcopy(value)
                for key, value in data.items()
                if key not in {"default", "profiles", "global"}
            }

        except Exception as e:
            self._load_error = str(e)
            print(f"Warning: Failed to load LLM profiles from {config_path}: {e}")

    def save(self, *, force: bool = False):
        """Save profiles to .llm_providers.yaml file.

        If the primary config path is on a read-only mount (Docker
        `:ro` bind), falls back to ``.testmcpy/.llm_providers.yaml``
        next to ``storage.db`` so UI edits actually persist
        (SC-108367 #3). Backup-onto-read-only is skipped so the save
        no longer leaves a misleading "Failed to restore backup"
        cascade in the log.
        """
        if self._load_error and not force:
            raise ValueError(
                f"Refusing to overwrite an invalid LLM profile configuration: {self._load_error}"
            )

        # Resolve via the fallback-preferring loader so save and load
        # never disagree on location, even in the unusual transition
        # where a fallback already exists but CWD has just become
        # writable (Docker-then-native in the same dir). SC-108367
        # review finding #5.
        primary_path = _resolve_llm_providers_path()
        save_path, using_fallback = _resolve_writable_path(primary_path)

        data = copy.deepcopy(self._extra)
        data.update(
            {
                "default": self.default_profile_id,
                "profiles": {},
                "global": copy.deepcopy(self.global_settings),
            }
        )

        for profile_id, profile in self.profiles.items():
            data["profiles"][profile_id] = profile.to_dict()

        backup_path = save_path.with_suffix(".yaml.backup")
        had_existing_file = save_path.exists()
        backup_created = False
        try:
            if had_existing_file:
                _atomic_copy(save_path, backup_path)
                backup_created = True

            _atomic_write_yaml(save_path, data)
            self._source_path = _absolute_path(primary_path if not using_fallback else save_path)
            self._load_error = None
            if using_fallback:
                print(
                    f"[testmcpy] {primary_path} is read-only; "
                    f"persisted LLM providers config to writable fallback {save_path}"
                )
        except Exception as e:
            # Atomic replacement normally leaves the original untouched. Restore
            # from the backup if an unusual filesystem failure removed it.
            if had_existing_file and backup_created and not save_path.exists():
                try:
                    _atomic_copy(backup_path, save_path)
                except Exception as restore_error:
                    raise Exception(
                        f"Failed to save LLM profiles: {e}; "
                        f"failed to restore backup: {restore_error}"
                    ) from e
            raise Exception(f"Failed to save LLM profiles: {e}")

    @property
    def source_path(self) -> Path:
        """Absolute config path loaded by this instance."""
        return self._source_path

    @property
    def load_error(self) -> str | None:
        """Validation/parsing failure for the source document, if any."""
        return self._load_error

    def has_profiles(self) -> bool:
        """Check if any profiles are loaded."""
        return len(self.profiles) > 0

    def list_profiles(self) -> list[str]:
        """List all profile IDs."""
        return list(self.profiles.keys())

    def get_profile(self, profile_id: str | None = None) -> LLMProfile | None:
        """Get a profile by ID. If None, returns default profile."""
        if profile_id is None:
            profile_id = _substitute_env_vars(self.default_profile_id)

        if profile_id is None:
            return None

        return self.profiles.get(profile_id)

    def add_profile(self, profile: LLMProfile):
        """Add or update a profile."""
        self.profiles[profile.profile_id] = profile

    def remove_profile(self, profile_id: str):
        """Remove a profile."""
        if profile_id in self.profiles:
            del self.profiles[profile_id]
            if self.default_profile_id == profile_id:
                self.default_profile_id = None

    def set_default_profile(self, profile_id: str):
        """Set the default profile."""
        if profile_id in self.profiles:
            self.default_profile_id = profile_id
        else:
            raise ValueError(f"Profile '{profile_id}' not found")


# Global instance
_llm_profile_config: LLMProfileConfig | None = None


def get_llm_profile_config() -> LLMProfileConfig:
    """Get or create global LLM profile configuration instance."""
    global _llm_profile_config
    current_path = _absolute_path(_resolve_llm_providers_path())
    if _llm_profile_config is None or _llm_profile_config.source_path != current_path:
        _llm_profile_config = LLMProfileConfig()
    return _llm_profile_config


def reload_llm_profile_config():
    """Force reload of LLM profile configuration."""
    global _llm_profile_config
    _llm_profile_config = LLMProfileConfig()
    return _llm_profile_config


def load_llm_profile(profile_id: str | None = None) -> LLMProfile | None:
    """
    Load an LLM profile by ID.

    Args:
        profile_id: Profile ID to load. If None, loads default profile.

    Returns:
        LLMProfile if found, None otherwise.
    """
    config = get_llm_profile_config()
    return config.get_profile(profile_id)


_RUNTIME_PROVIDER_FIELDS = (
    "api_key",
    "api_key_env",
    "base_url",
    "timeout",
    "workspace_hash",
    "domain",
    "api_token",
    "api_secret",
    "api_url",
    "conversations_path",
    "completions_path",
)

_PROVIDER_FAMILIES = {
    "aws-bedrock": "bedrock",
    "chatbot": "assistant",
    "claude-cli": "claude-sdk",
    "claude-code": "claude-sdk",
    "codex": "codex-sdk",
    "codex-cli": "codex-sdk",
    "google": "gemini",
    "grok": "xai",
}


class LLMProfileNotFoundError(ValueError):
    """Raised when a caller explicitly selects an unknown LLM profile."""


class LLMProfileConfigError(RuntimeError):
    """Raised when runtime selection cannot trust a malformed profile file."""


def _runtime_profile_id(
    profile_config: LLMProfileConfig,
    requested_profile_id: str | None,
) -> str | None:
    """Validate and return the profile ID that runtime selection will use."""
    if requested_profile_id is not None:
        if requested_profile_id not in profile_config.profiles:
            raise LLMProfileNotFoundError(f"LLM profile '{requested_profile_id}' was not found")
        return requested_profile_id

    raw_default = profile_config.default_profile_id
    if raw_default is None:
        return None
    resolved_default = _substitute_env_vars(raw_default)
    if not isinstance(resolved_default, str) or resolved_default not in profile_config.profiles:
        raise LLMProfileConfigError(
            f"Default LLM profile '{resolved_default or raw_default}' was not found"
        )
    return resolved_default


def _provider_family(provider: str) -> str:
    normalized = provider.strip().lower()
    return _PROVIDER_FAMILIES.get(normalized, normalized)


def _provider_name(provider: Any) -> str | None:
    if provider is None:
        return None
    value = getattr(provider, "value", provider)
    return str(value)


def _ensure_profile_api_key_binding_resolved(
    selected: LLMProviderConfig,
    profile_id: str | None,
) -> None:
    """Reject unresolved profile bindings before providers can use fallback keys."""
    if profile_id is None:
        return

    raw_api_key = object.__getattribute__(selected, "api_key")
    raw_api_key_env = object.__getattribute__(selected, "api_key_env")
    if raw_api_key is None and raw_api_key_env is None:
        return

    resolved_api_key = selected.api_key
    if isinstance(resolved_api_key, str) and resolved_api_key.strip():
        return

    raise LLMProfileConfigError(
        f"LLM profile '{profile_id}' has a configured API key that resolved to an empty value"
    )


def select_llm_profile_provider(
    profile_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> LLMProviderConfig | None:
    """Select the profile entry addressed by optional provider/model values."""
    profile = load_llm_profile(profile_id)
    if not profile:
        return None

    candidates = profile.providers
    provider_name = _provider_name(provider)
    if provider_name:
        family = _provider_family(provider_name)
        candidates = [entry for entry in candidates if _provider_family(entry.provider) == family]
        if not candidates:
            return None

    if model:
        exact = next((entry for entry in candidates if entry.model == model), None)
        if exact:
            return exact

    return next(
        (entry for entry in candidates if entry.default), candidates[0] if candidates else None
    )


def resolve_llm_provider_selection(
    provider: str | None = None,
    model: str | None = None,
    profile_id: str | None = None,
    *,
    fallback_provider: str | None = None,
    fallback_model: str | None = None,
) -> tuple[str | None, str | None, dict[str, Any]]:
    """Resolve effective provider/model and its profile-backed runtime kwargs."""
    if profile_id == "":
        profile_id = None
    profile_config = get_llm_profile_config()
    if profile_config.load_error:
        raise LLMProfileConfigError(
            f"Invalid LLM profile configuration: {profile_config.load_error}"
        )
    _runtime_profile_id(profile_config, profile_id)
    selected = select_llm_profile_provider(profile_id, provider, model)
    if profile_id is not None and selected is None:
        requested_provider = _provider_name(provider)
        if requested_provider:
            raise LLMProfileConfigError(
                f"LLM profile '{profile_id}' has no provider matching '{requested_provider}'"
            )
        raise LLMProfileConfigError(f"LLM profile '{profile_id}' has no configured providers")
    effective_provider = (
        _provider_name(provider)
        or (selected.provider if selected else None)
        or _provider_name(fallback_provider)
    )
    effective_model = model or (selected.model if selected else None) or fallback_model
    runtime_config = (
        resolve_llm_provider_config(effective_provider, effective_model, profile_id)
        if effective_provider and effective_model
        else {}
    )
    return effective_provider, effective_model, runtime_config


def resolve_llm_provider_config(
    provider: str,
    model: str,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """Return runtime kwargs for the selected provider from an LLM profile.

    Exact provider/model entries win. A provider-family default (or the first
    family match) supplies credentials when a caller overrides only the model.
    A profile entry for a different provider is never used.
    """
    if profile_id == "":
        profile_id = None
    profile_config = get_llm_profile_config()
    if profile_config.load_error:
        raise LLMProfileConfigError(
            f"Invalid LLM profile configuration: {profile_config.load_error}"
        )
    selected_profile_id = _runtime_profile_id(profile_config, profile_id)
    selected = select_llm_profile_provider(profile_id, provider, model)
    if selected is None or _provider_family(selected.provider) != _provider_family(provider):
        if profile_id is not None:
            raise LLMProfileConfigError(
                f"LLM profile '{profile_id}' has no provider matching '{provider}'"
            )
        return {}

    _ensure_profile_api_key_binding_resolved(selected, selected_profile_id)

    resolved = {
        field_name: value
        for field_name in _RUNTIME_PROVIDER_FIELDS
        if (value := getattr(selected, field_name, None)) is not None
    }
    if _provider_family(provider) == "claude-sdk" and profile_id is not None:
        resolved["llm_profile_id"] = profile_id
    from .scrubber import register_secret

    for field_name in ("api_key", "api_token", "api_secret"):
        register_secret(resolved.get(field_name))
    return resolved


def list_available_llm_profiles() -> list[str]:
    """List all available LLM profile IDs."""
    config = get_llm_profile_config()
    return config.list_profiles()


def get_default_llm_profile_id() -> str | None:
    """Get the default LLM profile ID."""
    config = get_llm_profile_config()
    resolved = _substitute_env_vars(config.default_profile_id)
    return resolved if isinstance(resolved, str) else None
