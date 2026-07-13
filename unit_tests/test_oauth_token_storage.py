"""Tests for the OAuth cache shared by MCP and SDK clients."""

import stat
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from key_value.aio.stores.memory import MemoryStore
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from testmcpy.src.llm_integration import ClaudeSDKProvider
from testmcpy.src.mcp_client import MCPOAuth
from testmcpy.src.oauth_storage import (
    _load_or_create_encryption_key,
    create_oauth_token_storage,
    oauth_cache_dir,
)


@pytest.mark.asyncio
async def test_mcp_oauth_persists_tokens_and_client_registration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mcp_url = "http://localhost:8084/mcp"
    first = MCPOAuth(mcp_url)
    token = OAuthToken(access_token="persisted-access-token", refresh_token="refresh-token")
    client_info = OAuthClientInformationFull(
        redirect_uris=["http://localhost:12345/callback"],
        client_id="registered-client",
        client_secret="registered-secret",
    )

    await first.token_storage_adapter.set_tokens(token)
    await first.token_storage_adapter.set_client_info(client_info)

    second = MCPOAuth(f"{mcp_url}/")
    assert await second.token_storage_adapter.get_tokens() == token
    assert await second.token_storage_adapter.get_client_info() == client_info
    assert second.redirect_port == first.redirect_port
    assert (
        second.context.client_metadata.redirect_uris == first.context.client_metadata.redirect_uris
    )
    assert oauth_cache_dir() == tmp_path / ".testmcpy" / "oauth-cache"
    assert oauth_cache_dir().is_dir()
    assert stat.S_IMODE(oauth_cache_dir().stat().st_mode) == 0o700
    assert stat.S_IMODE((oauth_cache_dir() / "oauth.key").stat().st_mode) == 0o600
    cache_contents = b"".join(
        path.read_bytes() for path in oauth_cache_dir().iterdir() if path.is_file()
    )
    assert b"persisted-access-token" not in cache_contents
    assert b"registered-secret" not in cache_contents


@pytest.mark.asyncio
async def test_oauth_cache_isolated_by_full_mcp_url(tmp_path: Path):
    first = create_oauth_token_storage("https://mcp.example.com/one", tmp_path)
    second = create_oauth_token_storage("https://mcp.example.com/two", tmp_path)

    await first.set_tokens(OAuthToken(access_token="endpoint-one-token"))

    assert (await first.get_tokens()).access_token == "endpoint-one-token"
    assert await second.get_tokens() is None


@pytest.mark.asyncio
async def test_sdk_provider_reuses_interactive_oauth_token(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    storage = create_oauth_token_storage("https://mcp.example.com/mcp/")
    await storage.set_tokens(OAuthToken(access_token="shared-access-token"))
    provider = ClaudeSDKProvider(
        model="claude-sonnet-4-5",
        mcp_url="https://mcp.example.com/mcp",
        auth={"type": "oauth", "oauth_auto_discover": True},
    )

    assert await provider._read_cached_oauth_token() == "shared-access-token"


@pytest.mark.asyncio
async def test_sdk_provider_rejects_expired_cached_token(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    storage = create_oauth_token_storage("https://mcp.example.com/mcp")
    stored_at = time.time()
    with patch("testmcpy.src.oauth_storage.time.time", return_value=stored_at):
        await storage.set_tokens(OAuthToken(access_token="expired-token", expires_in=60))
    provider = ClaudeSDKProvider(
        model="claude-sonnet-4-5",
        mcp_url="https://mcp.example.com/mcp",
        auth={"type": "oauth", "oauth_auto_discover": True},
    )

    with patch("testmcpy.src.llm_integration.time.time", return_value=stored_at + 100):
        assert await provider._read_cached_oauth_token() is None


@pytest.mark.asyncio
async def test_mcp_oauth_restores_original_token_expiry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    oauth = MCPOAuth("https://mcp.example.com/mcp")
    stored_at = time.time()
    with patch("testmcpy.src.oauth_storage.time.time", return_value=stored_at):
        await oauth.token_storage_adapter.set_tokens(
            OAuthToken(access_token="expired-token", expires_in=60)
        )

    await oauth._initialize()

    assert oauth.context.token_expiry_time == stored_at + 60


def test_encryption_key_creation_is_race_safe(tmp_path):
    with ThreadPoolExecutor(max_workers=8) as pool:
        keys = list(pool.map(lambda _: _load_or_create_encryption_key(tmp_path), range(16)))

    assert len(set(keys)) == 1
    assert (tmp_path / "oauth.key").read_bytes() == keys[0]
    assert not list(tmp_path.glob(".oauth-key-*"))


@pytest.mark.asyncio
async def test_sdk_provider_treats_undecryptable_cache_as_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    storage = create_oauth_token_storage("https://mcp.example.com/mcp")
    await storage.set_tokens(OAuthToken(access_token="old-key-token"))
    (oauth_cache_dir() / "oauth.key").write_bytes(Fernet.generate_key())
    provider = ClaudeSDKProvider(
        model="claude-sonnet-4-5",
        mcp_url="https://mcp.example.com/mcp",
        auth={"type": "oauth", "oauth_auto_discover": True},
    )

    assert await provider._read_cached_oauth_token() is None


def test_mcp_oauth_preserves_explicit_token_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    memory_store = MemoryStore()

    oauth = MCPOAuth("https://mcp.example.com/mcp", token_storage=memory_store)

    assert oauth.token_storage_adapter._key_value_store is memory_store
    assert not oauth_cache_dir().exists()
