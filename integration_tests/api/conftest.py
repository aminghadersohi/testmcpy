"""API-specific fixtures for integration tests."""

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Give every test its own TestStorage DB.

    get_storage() caches a module-level singleton whose default DB path is
    derived from Path.cwd() at first call — without a reset, the first test
    to touch storage pins the DB to its own tmp workspace and every later
    test reads/writes that stale DB.
    """
    import testmcpy.storage as storage_module

    monkeypatch.setenv("TESTMCPY_DB_PATH", str(tmp_path / "storage.db"))
    storage_module._storage = None
    yield
    storage_module._storage = None


@pytest.fixture
def client(mock_mcp_client, tmp_workspace, monkeypatch):
    """Create a TestClient with mocked MCP state and workspace directory."""
    monkeypatch.chdir(tmp_workspace)

    # Patch the module-level globals in api.py before importing app
    with (
        patch("testmcpy.server.api.mcp_client", mock_mcp_client),
        patch("testmcpy.server.api.mcp_clients", {"test:Test MCP": mock_mcp_client}),
        patch("testmcpy.server.state.mcp_client", mock_mcp_client),
        patch("testmcpy.server.state.mcp_clients", {"test:Test MCP": mock_mcp_client}),
    ):
        from testmcpy.server.api import app

        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


@pytest.fixture
def client_no_mcp(tmp_workspace, monkeypatch):
    """Create a TestClient with no MCP client connected."""
    monkeypatch.chdir(tmp_workspace)

    # Patch get_mcp_url to return None so the lifespan skips MCP init entirely
    with (
        patch("testmcpy.server.api.mcp_client", None),
        patch("testmcpy.server.api.mcp_clients", {}),
        patch("testmcpy.server.state.mcp_client", None),
        patch("testmcpy.server.state.mcp_clients", {}),
        patch("testmcpy.server.api.config") as mock_config,
    ):
        mock_config.get_mcp_url.return_value = None
        from testmcpy.server.api import app

        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
