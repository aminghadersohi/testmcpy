"""Unit tests for SC-108367 #3 — config saves survive a read-only mount.

Pre-fix: when ``mcp_services.yaml`` was mounted ``:ro`` (Docker single-
file bind), the atomic ``Path.replace`` and the subsequent
backup-restore both raised ``EROFS`` and the endpoint 500'd with the
misleading ``"Failed to restore backup"`` cascade.

Post-fix: the save detects a read-only primary, writes to
``.testmcpy/<filename>`` instead, and ``load_mcp_yaml`` / LLM-profile
load prefers the fallback if present.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def chdir(tmp_path, monkeypatch):
    """Run each test from a fresh tmp dir to isolate Path.cwd() lookups."""
    monkeypatch.chdir(tmp_path)
    yield tmp_path


def _make_readonly_file(path: Path, content: str = "default: foo\nprofiles: {}\n") -> None:
    """Create ``path`` with content and clear write bits — simulates the
    Docker `:ro` single-file bind mount. Restored by tmp_path teardown."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    # Strip write bits from owner/group/other.
    path.chmod(path.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _restore_write(path: Path) -> None:
    """tmp_path can't clean up paths it can't write to — re-add write
    bits before the fixture teardown."""
    if path.exists():
        path.chmod(path.stat().st_mode | stat.S_IWUSR)


class TestMcpYamlReadOnlyFallback:
    def test_writable_primary_uses_primary(self, chdir):
        """When the primary path IS writable, save MUST keep using it
        — the fallback is a last resort, not the default."""
        from testmcpy.server.helpers.mcp_config import (
            get_mcp_config_path,
            save_mcp_yaml,
        )

        primary = chdir / ".mcp_services.yaml"
        primary.write_text("default: x\nprofiles: {x: {name: x, mcps: []}}\n")

        save_mcp_yaml({"default": "x", "profiles": {"x": {"name": "x", "mcps": []}}})

        # Same file got updated; no fallback created.
        assert primary.exists()
        assert not (chdir / ".testmcpy" / ".mcp_services.yaml").exists()
        # get_mcp_config_path keeps returning primary.
        assert get_mcp_config_path() == primary

    def test_readonly_primary_falls_back_to_persistent_dir(self, chdir):
        """The bug repro: read-only primary → save into .testmcpy/."""
        from testmcpy.server.helpers.mcp_config import save_mcp_yaml

        primary = chdir / ".mcp_services.yaml"
        _make_readonly_file(primary)
        try:
            new_cfg = {"default": "x", "profiles": {"x": {"name": "x", "mcps": []}}}
            save_mcp_yaml(new_cfg)

            fallback = chdir / ".testmcpy" / ".mcp_services.yaml"
            assert fallback.exists(), "save should have created the fallback"
            # The primary is untouched (we DIDN'T sneak a write through).
            assert "default: foo" in primary.read_text()
            # The fallback has the new content.
            loaded = yaml.safe_load(fallback.read_text())
            assert loaded["default"] == "x"
            assert loaded["profiles"]["x"]["name"] == "x"
        finally:
            _restore_write(primary)

    def test_subsequent_load_prefers_fallback(self, chdir):
        """Once a fallback exists, ``get_mcp_config_path`` must prefer
        it — otherwise the save round-trip is broken (user edits, saves
        to fallback, then load reads stale primary)."""
        from testmcpy.server.helpers.mcp_config import (
            get_mcp_config_path,
            load_mcp_yaml,
            save_mcp_yaml,
        )

        primary = chdir / ".mcp_services.yaml"
        _make_readonly_file(primary, "default: stale\nprofiles: {}\n")
        try:
            save_mcp_yaml(
                {"default": "fresh", "profiles": {"fresh": {"name": "Fresh", "mcps": []}}}
            )
            assert get_mcp_config_path() == chdir / ".testmcpy" / ".mcp_services.yaml"
            loaded = load_mcp_yaml()
            assert loaded["default"] == "fresh"
        finally:
            _restore_write(primary)

    def test_no_failed_to_restore_backup_log_on_readonly(self, chdir, capsys):
        """Pre-fix: the except-block ran ``shutil.copy2(backup, primary)``
        even when primary was ``:ro``, producing a misleading
        ``"Failed to restore backup"`` line on every save attempt. The
        fix routes around it — that string MUST NOT appear when the
        save succeeded via fallback."""
        from testmcpy.server.helpers.mcp_config import save_mcp_yaml

        primary = chdir / ".mcp_services.yaml"
        _make_readonly_file(primary)
        try:
            save_mcp_yaml({"default": "x", "profiles": {"x": {"name": "x", "mcps": []}}})
            captured = capsys.readouterr()
            assert "Failed to restore backup" not in captured.out
            assert "Failed to restore backup" not in captured.err
        finally:
            _restore_write(primary)


class TestLlmProvidersReadOnlyFallback:
    def test_readonly_primary_falls_back(self, chdir):
        """Same fix for `.llm_providers.yaml`."""
        from testmcpy.llm_profiles import LLMProfile, LLMProfileConfig, LLMProviderConfig

        primary = chdir / ".llm_providers.yaml"
        _make_readonly_file(primary, "default: stale\nprofiles: {}\n")
        try:
            cfg = LLMProfileConfig()
            cfg.default_profile_id = "fresh"
            cfg.profiles["fresh"] = LLMProfile(
                profile_id="fresh",
                name="Fresh",
                description="",
                providers=[LLMProviderConfig(name="p", provider="anthropic", model="claude")],
            )
            cfg.save()
            fallback = chdir / ".testmcpy" / ".llm_providers.yaml"
            assert fallback.exists()
            assert "default: stale" in primary.read_text()
            loaded = yaml.safe_load(fallback.read_text())
            assert loaded["default"] == "fresh"
        finally:
            _restore_write(primary)

    def test_load_prefers_fallback(self, chdir):
        """The ``_load_profiles`` path used by every server boot must
        also prefer the fallback so persisted edits actually load."""
        from testmcpy.llm_profiles import LLMProfileConfig

        primary = chdir / ".llm_providers.yaml"
        _make_readonly_file(primary, "default: stale\nprofiles: {}\n")
        fallback_dir = chdir / ".testmcpy"
        fallback_dir.mkdir(exist_ok=True)
        (fallback_dir / ".llm_providers.yaml").write_text(
            "default: fresh\nprofiles:\n"
            "  fresh:\n"
            "    name: Fresh\n"
            "    description: ''\n"
            "    providers:\n"
            "    - {name: p, provider: anthropic, model: claude}\n"
        )
        try:
            cfg = LLMProfileConfig()
            assert cfg.default_profile_id == "fresh"
            assert "fresh" in cfg.profiles
        finally:
            _restore_write(primary)


class TestPathResolutionHelpers:
    """Pin the smaller helper contract so future refactors that move
    the fallback dir don't silently re-introduce the EROFS regression."""

    def test_resolve_save_path_returns_primary_when_writable(self, tmp_path):
        from testmcpy.server.helpers.mcp_config import resolve_config_save_path

        p = tmp_path / ".cfg.yaml"
        p.write_text("x")
        save_path, using_fallback = resolve_config_save_path(p)
        assert save_path == p
        assert using_fallback is False

    def test_resolve_save_path_returns_fallback_when_readonly(self, tmp_path, monkeypatch):
        from testmcpy.server.helpers.mcp_config import resolve_config_save_path

        monkeypatch.chdir(tmp_path)
        p = tmp_path / ".cfg.yaml"
        _make_readonly_file(p)
        try:
            save_path, using_fallback = resolve_config_save_path(p)
            assert save_path == tmp_path / ".testmcpy" / ".cfg.yaml"
            assert using_fallback is True
        finally:
            _restore_write(p)

    def test_resolve_load_path_prefers_fallback_when_present(self, tmp_path, monkeypatch):
        from testmcpy.server.helpers.mcp_config import resolve_config_load_path

        monkeypatch.chdir(tmp_path)
        p = tmp_path / ".cfg.yaml"
        p.write_text("primary")
        (tmp_path / ".testmcpy").mkdir()
        (tmp_path / ".testmcpy" / ".cfg.yaml").write_text("fallback")

        assert resolve_config_load_path(p) == tmp_path / ".testmcpy" / ".cfg.yaml"

    def test_resolve_load_path_falls_back_to_primary_when_no_fallback(self, tmp_path, monkeypatch):
        from testmcpy.server.helpers.mcp_config import resolve_config_load_path

        monkeypatch.chdir(tmp_path)
        p = tmp_path / ".cfg.yaml"
        p.write_text("primary")
        assert resolve_config_load_path(p) == p
