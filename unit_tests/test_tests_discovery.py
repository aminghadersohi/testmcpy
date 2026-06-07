"""
Unit tests for /api/tests discovery.

Verifies that the Tests page surfaces YAML files discovered via:
  - a regular subdirectory under <cwd>/tests
  - a symlinked subdirectory under <cwd>/tests (rglob in 3.11 misses these)
  - an external directory listed in TESTMCPY_EXTRA_TESTS_DIRS

Also covers the symlink-cycle guard so a misconfigured `tests/loop -> tests/`
can't pin the server.
"""

import os
from pathlib import Path

import pytest

from testmcpy.server.routers.tests import (
    _discover_yaml_tests,
    _extra_tests_dirs,
    list_tests,
)

# ----------------------------------------------------------------------
# Fixtures: build a temp tests tree the production scanner would see.
# ----------------------------------------------------------------------


def _write_yaml(path: Path, *names: str) -> None:
    """Write a minimal valid YAML test file with N test cases."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "tests:\n" + "\n".join(f"  - name: {n}\n    prompt: hi" for n in names)
    path.write_text(body)


@pytest.fixture
def cwd_with_tests(tmp_path: Path, monkeypatch):
    """Plant a tests/ tree under tmp_path and cd into it. Returns
    (tmp_path, tests_dir)."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    _write_yaml(tests_dir / "smoke.yaml", "t1", "t2")
    _write_yaml(tests_dir / "chatbot" / "C01.yaml", "c1")
    _write_yaml(tests_dir / "mcp-direct" / "M01.yaml", "m1", "m2", "m3")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TESTMCPY_EXTRA_TESTS_DIRS", raising=False)
    return tmp_path, tests_dir


# ----------------------------------------------------------------------
# Symlinked subdirs under tests/
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_symlinked_subdir_under_tests_is_discovered(tmp_path, monkeypatch):
    """`ln -s /external/some-suite tests/some-suite` must surface in the
    listing — this is the open-source contributor's workflow for keeping
    evals in a separate repo. Path.rglob in 3.11 silently skips these."""
    cwd = tmp_path / "cwd"
    (cwd / "tests").mkdir(parents=True)
    _write_yaml(cwd / "tests" / "smoke.yaml", "smoke_a")

    external = tmp_path / "external" / "chatbot"
    _write_yaml(external / "C01.yaml", "c1")
    _write_yaml(external / "C02.yaml", "c2", "c3")

    os.symlink(external, cwd / "tests" / "chatbot")

    monkeypatch.chdir(cwd)
    monkeypatch.delenv("TESTMCPY_EXTRA_TESTS_DIRS", raising=False)
    result = await list_tests()

    # The symlinked folder shows up grouped as 'chatbot' just like a real dir.
    assert "chatbot" in result["folders"], result
    chatbot_files = result["folders"]["chatbot"]
    names = sorted(f["filename"] for f in chatbot_files)
    assert names == ["C01.yaml", "C02.yaml"]
    # The runner needs an openable absolute path, NOT a path that goes
    # through the broken symlink later (resolve() canonicalizes it).
    for f in chatbot_files:
        assert os.path.isabs(f["path"]), f
        assert Path(f["path"]).is_file(), f["path"]
    # Test counts honour the YAML body.
    by_name = {f["filename"]: f for f in chatbot_files}
    assert by_name["C02.yaml"]["test_count"] == 2


@pytest.mark.asyncio
async def test_symlink_cycle_is_broken(tmp_path, monkeypatch):
    """`tests/loop -> tests/` would walk forever under followlinks=True.
    The cycle guard via realpath must terminate it without raising."""
    cwd = tmp_path / "cwd"
    tests_dir = cwd / "tests"
    tests_dir.mkdir(parents=True)
    _write_yaml(tests_dir / "a.yaml", "a")
    os.symlink(tests_dir, tests_dir / "loop")

    monkeypatch.chdir(cwd)
    monkeypatch.delenv("TESTMCPY_EXTRA_TESTS_DIRS", raising=False)
    result = await list_tests()

    # `a.yaml` exists exactly once, even though the loop technically lets
    # the walker re-enter the same dir.
    flat = list(result["files"]) + [f for v in result["folders"].values() for f in v]
    a_yaml = [f for f in flat if f["filename"] == "a.yaml"]
    assert len(a_yaml) == 1, flat


# ----------------------------------------------------------------------
# Extra roots via TESTMCPY_EXTRA_TESTS_DIRS
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extra_tests_dir_is_discovered_and_namespaced(tmp_path, monkeypatch):
    """An entry in TESTMCPY_EXTRA_TESTS_DIRS is walked and bucketed under
    its basename — different external suites stay visually distinct in
    the UI tree."""
    cwd = tmp_path / "cwd"
    (cwd / "tests").mkdir(parents=True)
    _write_yaml(cwd / "tests" / "local.yaml", "l1")

    external = tmp_path / "preset-mcp-tests" / "tests"
    _write_yaml(external / "chatbot" / "C01.yaml", "c1")
    _write_yaml(external / "mcp-direct" / "M01.yaml", "m1")

    monkeypatch.chdir(cwd)
    monkeypatch.setenv("TESTMCPY_EXTRA_TESTS_DIRS", str(external))
    result = await list_tests()

    # Local file unchanged.
    assert any(f["filename"] == "local.yaml" for f in result["files"]), result

    # External files appear under <basename>/<sub>/ folder keys.
    assert "tests/chatbot" in result["folders"], result["folders"].keys()
    assert "tests/mcp-direct" in result["folders"], result["folders"].keys()
    chatbot = result["folders"]["tests/chatbot"]
    assert len(chatbot) == 1
    assert chatbot[0]["relative_path"].startswith("tests/")
    # Path is absolute and points at the real external file.
    assert chatbot[0]["path"] == str(external.resolve() / "chatbot" / "C01.yaml")


@pytest.mark.asyncio
async def test_extra_tests_dir_supports_multiple_roots(tmp_path, monkeypatch):
    """pathsep-separated TESTMCPY_EXTRA_TESTS_DIRS pulls in multiple
    external suites at once."""
    cwd = tmp_path / "cwd"
    (cwd / "tests").mkdir(parents=True)
    e1 = tmp_path / "suite-one"
    e2 = tmp_path / "suite-two"
    _write_yaml(e1 / "a.yaml", "a")
    _write_yaml(e2 / "b" / "x.yaml", "x")

    monkeypatch.chdir(cwd)
    monkeypatch.setenv("TESTMCPY_EXTRA_TESTS_DIRS", f"{e1}{os.pathsep}{e2}")
    result = await list_tests()

    folder_keys = set(result["folders"].keys())
    # a.yaml is at the root of suite-one → grouped under "suite-one"
    assert "suite-one" in folder_keys, folder_keys
    # x.yaml lives in suite-two/b → grouped under "suite-two/b"
    assert "suite-two/b" in folder_keys, folder_keys


def test_missing_extra_tests_dirs_entries_are_silently_skipped(tmp_path, monkeypatch):
    """Stale config in TESTMCPY_EXTRA_TESTS_DIRS must not break /api/tests
    — log a warning and skip the entry."""
    real = tmp_path / "real"
    real.mkdir()
    fake = tmp_path / "does-not-exist"
    rel = "tests"  # not absolute → also skipped

    monkeypatch.setenv("TESTMCPY_EXTRA_TESTS_DIRS", f"{real}{os.pathsep}{fake}{os.pathsep}{rel}")
    out = _extra_tests_dirs()
    assert out == [real]


def test_no_extra_tests_dirs_env_returns_empty_list(monkeypatch):
    monkeypatch.delenv("TESTMCPY_EXTRA_TESTS_DIRS", raising=False)
    assert _extra_tests_dirs() == []


# ----------------------------------------------------------------------
# Baseline behaviour — make sure the rewrite didn't regress the boring case.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_baseline_tests_dir_grouping_is_preserved(cwd_with_tests):
    """Plain subdirs under tests/ still group as before."""
    result = await list_tests()
    assert "chatbot" in result["folders"]
    assert "mcp-direct" in result["folders"]
    assert any(f["filename"] == "smoke.yaml" for f in result["files"])


@pytest.mark.asyncio
async def test_no_tests_dir_returns_empty(tmp_path, monkeypatch):
    """If the user has no tests/ dir AND no extra roots, the endpoint
    returns an empty payload instead of 500."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TESTMCPY_EXTRA_TESTS_DIRS", raising=False)
    result = await list_tests()
    assert result == {"folders": {}, "files": []}


def test_discover_yaml_tests_returns_empty_for_nonexistent_root(tmp_path):
    """Lower-level helper guard — feeding it a bogus path returns empty
    rather than raising."""
    folders, files = _discover_yaml_tests(tmp_path / "does-not-exist")
    assert folders == {}
    assert files == []
