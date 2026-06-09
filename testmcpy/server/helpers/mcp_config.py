"""MCP configuration file helpers."""

import copy
import os
import shutil
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException

# Persistent fallback for config files whose primary location is on a
# read-only mount (e.g. Docker `:ro` bind mounts of mcp_services.yaml /
# llm_providers.yaml). Mirrors the `.testmcpy/storage.db` convention
# from `testmcpy/db.py` so a single named volume covers DB + config
# writes. SC-108367 #3.
_PERSISTENT_DIR_NAME = ".testmcpy"


def _persistent_dir_path() -> Path:
    """Return the persistent-fallback directory PATH without touching the
    filesystem. Read-side callers (``resolve_config_load_path``,
    ``get_mcp_config_path``) want a path to check existence on; they
    shouldn't have a write side-effect just for reading."""
    return Path.cwd() / _PERSISTENT_DIR_NAME


def _persistent_dir_ensure() -> Path:
    """Return the persistent-fallback directory, creating it if missing.
    Use this from WRITE paths only — reads should call
    ``_persistent_dir_path`` to avoid a mkdir side-effect when the user
    is just opening a config file (SC-108367 review finding #6)."""
    d = _persistent_dir_path()
    try:
        d.mkdir(exist_ok=True)
    except OSError:
        # `.testmcpy/` itself is read-only (very unusual deployment).
        # Caller will catch the eventual write error.
        pass
    return d


def _is_path_writable_for_replace(path: Path) -> bool:
    """``Path.replace`` requires write access to the TARGET file (not just
    the parent dir) when the target already exists, because it overwrites
    the inode. A ``:ro`` single-file bind mount has writable parent dir
    but read-only target — that's exactly the case this guards against.
    """
    if not path.exists():
        # Brand-new file — parent-dir writability is sufficient.
        return os.access(path.parent, os.W_OK)
    return os.access(path, os.W_OK)


def resolve_config_save_path(primary_path: Path) -> tuple[Path, bool]:
    """Pick where to actually write a config file.

    Returns ``(save_path, using_fallback)``. ``save_path`` is either
    ``primary_path`` itself (when writable) or the persistent fallback
    at ``.testmcpy/<filename>`` (when the primary is on a read-only
    mount). Callers MUST persist to ``save_path`` and skip the
    backup-restore-onto-primary dance when ``using_fallback`` is True
    (writing the backup to a read-only path produces the misleading
    "Failed to restore backup" 500 cascade — SC-108367 #3).
    """
    if _is_path_writable_for_replace(primary_path):
        return primary_path, False
    # Write path: ensure the fallback dir exists.
    fallback = _persistent_dir_ensure() / primary_path.name
    return fallback, True


def resolve_config_load_path(primary_path: Path) -> Path:
    """Pick where to read a config file from.

    Prefers a previous save in the persistent fallback location if one
    exists, so UI edits round-trip across container restarts. Otherwise
    falls back to the primary bind-mounted path. Either return value is
    safe to pass to ``open()``; callers must still check ``.exists()``.
    """
    # Read path: just check existence; don't materialise the dir.
    fallback = _persistent_dir_path() / primary_path.name
    if fallback.exists():
        return fallback
    return primary_path


def get_mcp_config_path() -> Path:
    """Get path to .mcp_services.yaml file.

    Returns the persistent fallback (``.testmcpy/.mcp_services.yaml``)
    when it exists from a previous save, otherwise the standard CWD or
    ancestor lookup. SC-108367 #3.
    """
    # Read path: don't materialise .testmcpy/ just to look for the file.
    fallback = _persistent_dir_path() / ".mcp_services.yaml"
    if fallback.exists():
        return fallback

    # Look in current directory first
    config_path = Path.cwd() / ".mcp_services.yaml"
    if config_path.exists():
        return config_path

    # Check parent directories
    current = Path.cwd()
    for _ in range(5):
        config_file = current / ".mcp_services.yaml"
        if config_file.exists():
            return config_file
        if current.parent == current:
            break
        current = current.parent

    # Default to current directory
    return Path.cwd() / ".mcp_services.yaml"


def load_mcp_yaml() -> dict[str, Any]:
    """Load MCP configuration from YAML file with error handling."""
    config_path = get_mcp_config_path()
    if not config_path.exists():
        return {"default": "local-dev", "profiles": {}}

    try:
        with open(config_path) as f:
            data = yaml.safe_load(f)
            return data or {"default": "local-dev", "profiles": {}}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse YAML configuration: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load configuration file: {str(e)}")


def validate_config(config_data: dict[str, Any]):
    """
    Validate MCP configuration before saving.

    Raises:
        ValueError: If validation fails with detailed error message
    """
    if "profiles" not in config_data:
        raise ValueError("Config must have 'profiles' field")

    if not isinstance(config_data["profiles"], dict):
        raise ValueError("'profiles' must be a dictionary")

    for profile_id, profile in config_data["profiles"].items():
        if not isinstance(profile, dict):
            raise ValueError(f"Profile '{profile_id}' must be a dictionary")

        if "name" not in profile:
            raise ValueError(f"Profile '{profile_id}' missing required 'name' field")

        if "mcps" in profile:
            if not isinstance(profile["mcps"], list):
                raise ValueError(f"Profile '{profile_id}' 'mcps' must be a list")

            for idx, mcp in enumerate(profile["mcps"]):
                if not isinstance(mcp, dict):
                    raise ValueError(f"MCP #{idx} in profile '{profile_id}' must be a dictionary")

                if "name" not in mcp:
                    raise ValueError(f"MCP #{idx} in profile '{profile_id}' missing 'name' field")

                if "mcp_url" not in mcp:
                    raise ValueError(
                        f"MCP '{mcp['name']}' in profile '{profile_id}' missing 'mcp_url' field"
                    )

                if "auth" not in mcp:
                    raise ValueError(
                        f"MCP '{mcp['name']}' in profile '{profile_id}' missing 'auth' field"
                    )

                auth = mcp["auth"]
                if not isinstance(auth, dict):
                    raise ValueError(
                        f"MCP '{mcp['name']}' in profile '{profile_id}' 'auth' must be a dictionary"
                    )

                if "type" not in auth:
                    raise ValueError(
                        f"MCP '{mcp['name']}' in profile '{profile_id}' auth missing 'type' field"
                    )

                auth_type = auth["type"]
                if auth_type not in ("bearer", "jwt", "oauth", "none"):
                    raise ValueError(
                        f"MCP '{mcp['name']}' in profile '{profile_id}' has invalid auth type: '{auth_type}'. "
                        f"Must be one of: bearer, jwt, oauth, none"
                    )


def clean_config_for_yaml(config_data: dict[str, Any]) -> dict[str, Any]:
    """
    Clean config data for YAML serialization.

    - Removes None values
    - Preserves empty strings and empty lists
    - Deep copies to avoid mutating original
    """

    def clean_value(value):
        """Recursively clean a value."""
        if value is None:
            return None
        elif isinstance(value, dict):
            cleaned = {}
            for k, v in value.items():
                cleaned_v = clean_value(v)
                if cleaned_v is not None:
                    cleaned[k] = cleaned_v
            return cleaned if cleaned else None
        elif isinstance(value, list):
            cleaned = [clean_value(item) for item in value]
            return [item for item in cleaned if item is not None]
        else:
            return value

    config_copy = copy.deepcopy(config_data)
    cleaned = clean_value(config_copy)

    if cleaned is None:
        return {"default": "local-dev", "profiles": {}}

    return cleaned


def save_mcp_yaml(config_data: dict[str, Any]):
    """
    Save MCP configuration to YAML file with robust error handling.

    Features:
    - Validates config before saving
    - Creates backup before overwrite (skipped on read-only fallback path)
    - Uses atomic write (temp file + rename)
    - Falls back to writable `.testmcpy/<filename>` when the primary
      config is on a read-only mount (Docker `:ro` bind, SC-108367 #3)
    - Automatic rollback on failure (only when writing to a writable
      primary — restoring onto a `:ro` path is what produced the
      misleading "Failed to restore backup" 500s)
    - Reloads profile config after save
    """
    # Resolve where to actually write. If the discovered config path is
    # on a read-only mount, switch to .testmcpy/.mcp_services.yaml.
    primary_path = get_mcp_config_path()
    save_path, using_fallback = resolve_config_save_path(primary_path)
    backup_path = save_path.with_suffix(".yaml.backup")
    temp_path = save_path.with_suffix(".yaml.tmp")

    try:
        validate_config(config_data)
        cleaned_config = clean_config_for_yaml(config_data)

        # Backup only when we'll actually be replacing an existing file
        # at the save location. (When falling back to .testmcpy/ for
        # the first time, there's nothing to back up; subsequent saves
        # will find a previous fallback copy and back it up there.)
        if save_path.exists():
            try:
                shutil.copy2(save_path, backup_path)
            except Exception as e:
                print(f"Warning: Failed to create backup: {e}")

        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    cleaned_config,
                    f,
                    default_flow_style=False,
                    sort_keys=False,
                    indent=2,
                    allow_unicode=True,
                    width=float("inf"),
                )
        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            raise ValueError(f"Failed to write YAML: {str(e)}")

        try:
            with open(temp_path, encoding="utf-8") as f:
                yaml.safe_load(f)
        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            raise ValueError(f"Generated invalid YAML: {str(e)}")

        temp_path.replace(save_path)
        if using_fallback:
            print(
                f"[testmcpy] {primary_path} is read-only; "
                f"persisted MCP config to writable fallback {save_path}"
            )

        from testmcpy.mcp_profiles import reload_profile_config

        reload_profile_config()

    except ValueError as e:
        if backup_path.exists() and not save_path.exists():
            try:
                shutil.copy2(backup_path, save_path)
            except Exception as restore_error:
                print(f"Error restoring backup: {restore_error}")
        raise HTTPException(status_code=400, detail=f"Invalid configuration: {str(e)}")

    except Exception as e:
        # Restore from backup ONLY when our save target is writable.
        # On a `:ro` mount the `copy2(backup, primary)` would itself
        # fail with EROFS and we'd log the misleading
        # "Failed to restore backup" cascade. The fallback resolution
        # above should mean we never hit this for the read-only case,
        # but guard explicitly so future changes don't reintroduce it.
        if backup_path.exists() and _is_path_writable_for_replace(save_path):
            try:
                shutil.copy2(backup_path, save_path)
                print(f"Restored configuration from backup after error: {e}")
            except Exception as restore_error:
                print(f"Failed to restore backup: {restore_error}")

        raise HTTPException(status_code=500, detail=f"Failed to save configuration: {str(e)}")

    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception as e:
                print(f"Warning: Failed to clean up temp file: {e}")


def generate_profile_id(name: str, existing_ids: list[str]) -> str:
    """Generate a unique profile ID from a name."""
    base_id = name.lower().replace(" ", "-").replace("_", "-")
    base_id = "".join(c for c in base_id if c.isalnum() or c == "-")

    profile_id = base_id
    counter = 1
    while profile_id in existing_ids:
        profile_id = f"{base_id}-{counter}"
        counter += 1

    return profile_id
