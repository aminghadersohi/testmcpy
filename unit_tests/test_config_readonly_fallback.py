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

    def test_save_then_fresh_load_round_trips_via_fallback(self, chdir):
        """The exact user-reported failure (SC-108367 expanded): on
        /llm-profiles, creating a profile appeared to succeed but the
        profile was gone after reload. Pre-fix the load path returned
        the read-only primary whenever it existed, so the just-saved
        fallback was invisible — silent non-persistence.

        Drives the full round trip: read-only primary, save through the
        public API, instantiate a FRESH ``LLMProfileConfig`` (mimicking
        a server restart), and verify the profile loads back. Without
        the load-prefers-fallback fix this assertion would fail with
        the loaded profile missing entirely."""
        from testmcpy.llm_profiles import LLMProfile, LLMProfileConfig, LLMProviderConfig

        primary = chdir / ".llm_providers.yaml"
        _make_readonly_file(
            primary,
            "default: stale\nprofiles:\n  stale: {name: Stale, description: '', providers: []}\n",
        )
        try:
            # Initial load reads the stale primary (no fallback yet).
            cfg1 = LLMProfileConfig()
            assert cfg1.default_profile_id == "stale"
            assert "stale" in cfg1.profiles

            # User creates a new profile via the UI → save.
            cfg1.profiles["fresh"] = LLMProfile(
                profile_id="fresh",
                name="Fresh",
                description="created via UI",
                providers=[LLMProviderConfig(name="p", provider="anthropic", model="claude")],
            )
            cfg1.default_profile_id = "fresh"
            cfg1.save()

            # Fallback now holds the new state.
            fallback = chdir / ".testmcpy" / ".llm_providers.yaml"
            assert fallback.exists()

            # The primary is still the stale read-only file — proof we
            # didn't sneak a write through.
            assert "default: stale" in primary.read_text()

            # Simulate a fresh server boot — same CWD, no in-memory
            # state. Load must read the FALLBACK, not the stale primary.
            cfg2 = LLMProfileConfig()
            assert cfg2.default_profile_id == "fresh", (
                "Load fell back to stale primary instead of fresh fallback "
                "— SC-108367 silent-non-persistence regression"
            )
            assert "fresh" in cfg2.profiles
            assert cfg2.profiles["fresh"].providers[0].provider == "anthropic"
        finally:
            _restore_write(primary)

    def test_fallback_target_is_cwd_relative_not_home(self, chdir):
        """The named-volume in Docker is mounted at ``/app/.testmcpy``,
        NOT ``~/.testmcpy``. The latter is wiped on container recreate
        unless someone explicitly mounts it. Verify the fallback target
        is rooted at ``Path.cwd()`` so restart persistence Just Works
        on the standard testmcpy-data named volume."""
        from testmcpy.llm_profiles import LLMProfileConfig

        primary = chdir / ".llm_providers.yaml"
        _make_readonly_file(primary, "default: x\nprofiles: {}\n")
        try:
            cfg = LLMProfileConfig()
            cfg.default_profile_id = "fresh"
            cfg.save()

            # MUST land under CWD, not under home.
            assert (chdir / ".testmcpy" / ".llm_providers.yaml").exists()
            assert not (Path.home() / ".testmcpy" / ".llm_providers.yaml").exists() or (
                # If a previous test in this session happened to write under
                # home (unlikely but harmless), the important thing is our
                # CWD fallback also wrote — assert that, above.
                (chdir / ".testmcpy" / ".llm_providers.yaml").exists()
            )
        finally:
            _restore_write(primary)


class TestMCPProfileConfigPrefersFallback:
    """Reviewer finding #1 on PR #79: the higher-level
    ``MCPProfileConfig._find_config_file`` was reading CWD directly,
    ignoring the ``.testmcpy/`` fallback that ``save_mcp_yaml`` writes
    to. Net effect: ``GET /profiles`` and runtime ``load_profile()``
    kept reading the stale read-only primary, so saved MCP edits
    didn't appear in the list and weren't used at runtime — even
    though the 500 was gone. Pin the load-via-MCPProfileConfig path
    so the regression can't sneak back."""

    def test_mcp_profile_config_loader_prefers_fallback(self, chdir):
        from testmcpy.mcp_profiles import MCPProfileConfig
        from testmcpy.server.helpers.mcp_config import save_mcp_yaml

        primary = chdir / ".mcp_services.yaml"
        # Read-only primary holds an old profile the user wants to replace.
        _make_readonly_file(
            primary,
            "default: stale\n"
            "profiles:\n"
            "  stale:\n"
            "    name: Stale\n"
            "    description: ''\n"
            "    mcps:\n"
            "    - name: Stale MCP\n"
            "      mcp_url: http://stale/mcp\n"
            "      auth: {type: none}\n",
        )
        try:
            # User edits the config — save goes to .testmcpy fallback.
            save_mcp_yaml(
                {
                    "default": "fresh",
                    "profiles": {
                        "fresh": {
                            "name": "Fresh",
                            "description": "",
                            "mcps": [
                                {
                                    "name": "Fresh MCP",
                                    "mcp_url": "http://fresh/mcp",
                                    "auth": {"type": "none"},
                                }
                            ],
                        }
                    },
                }
            )

            # `GET /profiles` (and runtime test execution) routes through
            # MCPProfileConfig. Without the review-finding-#1 fix this
            # loader returns the STALE profile.
            cfg = MCPProfileConfig()
            assert cfg.default_profile == "fresh", (
                "MCPProfileConfig loaded the stale read-only primary instead "
                "of the .testmcpy fallback — review finding #1 regression"
            )
            assert "fresh" in cfg.profiles
            assert "stale" not in cfg.profiles
            fresh = cfg.profiles["fresh"]
            assert fresh.mcps[0].name == "Fresh MCP"
            assert fresh.mcps[0].mcp_url == "http://fresh/mcp"
        finally:
            _restore_write(primary)


class TestNoMkdirSideEffectOnReads:
    """Reviewer finding #6 on PR #79: ``_persistent_dir`` was creating
    ``.testmcpy/`` on every read just to look up a path. Reads
    shouldn't have a write side-effect."""

    def test_load_path_resolution_does_not_create_persistent_dir(self, chdir):
        from testmcpy.server.helpers.mcp_config import (
            get_mcp_config_path,
            resolve_config_load_path,
        )

        # No primary, no fallback, no .testmcpy/ dir.
        assert not (chdir / ".testmcpy").exists()

        # Read-only path resolution must NOT create the dir.
        get_mcp_config_path()
        resolve_config_load_path(chdir / ".whatever.yaml")
        assert not (chdir / ".testmcpy").exists(), (
            "Pure read paths created .testmcpy/ — review finding #6"
        )


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
