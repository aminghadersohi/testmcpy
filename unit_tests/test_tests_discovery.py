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
from fastapi import HTTPException

from testmcpy.server.routers.tests import TestFileUpdate as _TestFileUpdate
from testmcpy.server.routers.tests import (
    _discover_yaml_tests,
    _extra_tests_dirs,
    _resolve_test_file,
    get_test_file,
    list_tests,
    update_test_file,
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


# ----------------------------------------------------------------------
# Dedup: same dir via symlink AND extra-root must not list files twice
# (Copilot review on PR #73, line 115).
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_dir_via_symlink_and_extra_root_is_deduped(tmp_path, monkeypatch):
    """The realpath dedup check kicks in BEFORE the walk so YAMLs that
    sit directly under a root reachable both as a `tests/<sym>` symlink
    AND a `TESTMCPY_EXTRA_TESTS_DIRS` entry don't appear twice. The
    symlink label wins because the primary scan runs first."""
    cwd = tmp_path / "cwd"
    (cwd / "tests").mkdir(parents=True)
    external = tmp_path / "external"
    _write_yaml(external / "A.yaml", "a")
    os.symlink(external, cwd / "tests" / "external")

    monkeypatch.chdir(cwd)
    monkeypatch.setenv("TESTMCPY_EXTRA_TESTS_DIRS", str(external))
    result = await list_tests()

    # Every file appears at most once across the flattened listing.
    flat = list(result["files"]) + [f for v in result["folders"].values() for f in v]
    a_yaml = [f for f in flat if f["filename"] == "A.yaml"]
    assert len(a_yaml) == 1, flat
    # Symlink-label group wins because the primary `tests/` walk ran first.
    assert "external" in result["folders"], result["folders"].keys()


# ----------------------------------------------------------------------
# Bad YAMLs: a single unreadable file must not 500 the endpoint
# (Copilot review on PR #73, line 172).
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unreadable_yaml_does_not_break_discovery(tmp_path, monkeypatch):
    """A YAML with invalid UTF-8 (or other parse fault) used to surface
    as a 500 because the catch was narrowed to (OSError, yaml.YAMLError).
    Discovery must skip the file and keep listing the rest of the tree."""
    cwd = tmp_path / "cwd"
    (cwd / "tests").mkdir(parents=True)
    _write_yaml(cwd / "tests" / "ok.yaml", "ok")
    # Write invalid UTF-8 bytes to a .yaml file — open(f).read() will raise
    # UnicodeDecodeError before yaml.safe_load is even called.
    (cwd / "tests" / "broken.yaml").write_bytes(b"\xff\xfe\x00\x00not utf-8")

    monkeypatch.chdir(cwd)
    monkeypatch.delenv("TESTMCPY_EXTRA_TESTS_DIRS", raising=False)
    result = await list_tests()

    filenames = [f["filename"] for f in result["files"]]
    assert "ok.yaml" in filenames
    # The broken file is silently skipped (a print() goes to stderr
    # in real life; nothing leaks to the API response).
    assert "broken.yaml" not in filenames


# ----------------------------------------------------------------------
# _resolve_test_file + view/edit endpoints for extra-root files
# (Amin review on PR #73, item 1).
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_view_endpoint_resolves_extra_root_file(tmp_path, monkeypatch):
    """`GET /api/tests/{filename}` must succeed for a file discovered
    via `TESTMCPY_EXTRA_TESTS_DIRS`. Before this fix the endpoint
    short-circuited to 404 because it only checked under <cwd>/tests."""
    cwd = tmp_path / "cwd"
    (cwd / "tests").mkdir(parents=True)
    external = tmp_path / "preset-mcp-tests"
    _write_yaml(external / "chatbot" / "C01.yaml", "c1")

    monkeypatch.chdir(cwd)
    monkeypatch.setenv("TESTMCPY_EXTRA_TESTS_DIRS", str(external))

    # Discovery key for that file is `<root.name>/<rel>` (the same shape
    # the file tree uses as `relative_path`).
    response = await get_test_file("preset-mcp-tests/chatbot/C01.yaml")
    assert "C01.yaml" in response["path"]
    assert "name: c1" in response["content"]


@pytest.mark.asyncio
async def test_view_endpoint_404_for_missing_extra_root_file(tmp_path, monkeypatch):
    """Asking for a path that doesn't exist under any allowed root must
    still 404 — the new resolver must not accidentally open arbitrary
    files (path-traversal guard)."""
    cwd = tmp_path / "cwd"
    (cwd / "tests").mkdir(parents=True)
    external = tmp_path / "preset-mcp-tests"
    external.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("TESTMCPY_EXTRA_TESTS_DIRS", str(external))

    with pytest.raises(HTTPException) as exc:
        await get_test_file("preset-mcp-tests/does-not-exist.yaml")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_view_endpoint_blocks_path_traversal_via_extra_root(tmp_path, monkeypatch):
    """`preset-mcp-tests/../../../etc/passwd`-style paths must NOT
    resolve to anything outside the extra root, even though they have
    the right prefix."""
    cwd = tmp_path / "cwd"
    (cwd / "tests").mkdir(parents=True)
    external = tmp_path / "preset-mcp-tests"
    external.mkdir()
    # A real file outside the extra root that traversal would otherwise hit.
    (tmp_path / "secret.yaml").write_text("name: leaked")
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("TESTMCPY_EXTRA_TESTS_DIRS", str(external))

    assert _resolve_test_file("preset-mcp-tests/../secret.yaml") is None
    with pytest.raises(HTTPException) as exc:
        await get_test_file("preset-mcp-tests/../secret.yaml")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_endpoint_writes_back_to_extra_root(tmp_path, monkeypatch):
    """The save flow must write to the file's original on-disk location
    (under the extra root), not silently create a fresh copy under
    <cwd>/tests."""
    cwd = tmp_path / "cwd"
    (cwd / "tests").mkdir(parents=True)
    external = tmp_path / "preset-mcp-tests"
    _write_yaml(external / "chatbot" / "C01.yaml", "c1")

    monkeypatch.chdir(cwd)
    monkeypatch.setenv("TESTMCPY_EXTRA_TESTS_DIRS", str(external))

    new_yaml = "tests:\n  - name: c1_updated\n    prompt: changed"
    body = _TestFileUpdate(content=new_yaml)
    response = await update_test_file("preset-mcp-tests/chatbot/C01.yaml", body)
    # The on-disk file actually changed and stays under the external root.
    on_disk = (external / "chatbot" / "C01.yaml").read_text()
    assert "c1_updated" in on_disk
    # A local mirror was NOT created under <cwd>/tests.
    assert not (cwd / "tests" / "preset-mcp-tests").exists()
    assert response["filename"] == "preset-mcp-tests/chatbot/C01.yaml"


def test_resolve_test_file_local_files_still_work(tmp_path, monkeypatch):
    """Sanity-check the local path: a plain <cwd>/tests file resolves
    without going through the extra-root branch."""
    cwd = tmp_path / "cwd"
    (cwd / "tests").mkdir(parents=True)
    _write_yaml(cwd / "tests" / "smoke.yaml", "s")
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("TESTMCPY_EXTRA_TESTS_DIRS", raising=False)

    resolved = _resolve_test_file("smoke.yaml")
    assert resolved is not None
    assert resolved.name == "smoke.yaml"


def test_resolve_test_file_returns_none_for_unknown_root(tmp_path, monkeypatch):
    """If the head of the filename doesn't match any extra root's
    basename, _resolve_test_file returns None (no silent walks)."""
    cwd = tmp_path / "cwd"
    (cwd / "tests").mkdir(parents=True)
    external = tmp_path / "preset-mcp-tests"
    external.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("TESTMCPY_EXTRA_TESTS_DIRS", str(external))

    assert _resolve_test_file("some-other-suite/file.yaml") is None
