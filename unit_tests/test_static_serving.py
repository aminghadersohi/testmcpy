"""Focused tests for production UI static serving and CORS defaults."""

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from testmcpy.server import api


@pytest.fixture
def ui_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>test UI</html>", encoding="utf-8")
    monkeypatch.setattr(api, "_UI_DIST_DIR", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_root_and_spa_index_require_revalidation(ui_dist: Path) -> None:
    root_response = await api.root()
    spa_response = await api.serve_react_app("llm-profiles")

    assert root_response.headers["cache-control"] == "no-cache"
    assert spa_response.headers["cache-control"] == "no-cache"


@pytest.mark.asyncio
async def test_hashed_asset_is_cached_immutably(ui_dist: Path) -> None:
    asset = ui_dist / "assets" / "index-abc123.js"
    asset.write_text("export default true", encoding="utf-8")

    response = await api.serve_react_app("assets/index-abc123.js")

    assert response.path == asset
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_path",
    ["assets/index-old.js", "src/main.jsx", "vite.svg", "styles/missing.css"],
)
async def test_missing_static_file_returns_404(ui_dist: Path, request_path: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await api.serve_react_app(request_path)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Static asset not found"


@pytest.mark.asyncio
async def test_static_file_parent_traversal_is_rejected(ui_dist: Path) -> None:
    outside = ui_dist.parent / "secret.txt"
    outside.write_text("must not be served", encoding="utf-8")

    with pytest.raises(HTTPException) as exc_info:
        await api.serve_react_app("../secret.txt")

    assert exc_info.value.status_code == 404


def test_missing_module_http_response_is_not_spa_html(ui_dist: Path) -> None:
    response = TestClient(api.app).get("/assets/index-stale.js")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert "<html" not in response.text.lower()


def test_default_cors_origins_are_loopback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TESTMCPY_CORS_ORIGINS", raising=False)

    origins, allow_credentials = api._get_cors_settings()

    assert origins == list(api._DEFAULT_CORS_ORIGINS)
    assert all(
        origin.startswith("http://localhost:") or "127.0.0.1" in origin or "[::1]" in origin
        for origin in origins
    )
    assert allow_credentials is True


def test_explicit_cors_origins_are_trimmed_and_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "TESTMCPY_CORS_ORIGINS",
        " https://ui.example.com,https://ui.example.com,http://127.0.0.1:4173 ",
    )

    origins, allow_credentials = api._get_cors_settings()

    assert origins == ["https://ui.example.com", "http://127.0.0.1:4173"]
    assert allow_credentials is True


def test_explicit_wildcard_cors_disables_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TESTMCPY_CORS_ORIGINS", "*")

    origins, allow_credentials = api._get_cors_settings()

    assert origins == ["*"]
    assert allow_credentials is False
