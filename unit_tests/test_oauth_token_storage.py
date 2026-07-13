"""Tests for the OAuth cache shared by MCP and SDK clients."""

import stat
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from fastmcp.client.auth.oauth import TokenStorageAdapter
from key_value.aio.stores.memory import MemoryStore
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from testmcpy.scrubber import REDACTED, reset_cache, scrub_text
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
    first = MCPOAuth(mcp_url, callback_port=51001)
    token = OAuthToken(access_token="persisted-access-token", refresh_token="refresh-token")
    client_info = OAuthClientInformationFull(
        redirect_uris=["http://localhost:51001/callback"],
        client_id="registered-client",
        client_secret="registered-secret",
    )

    await first.token_storage_adapter.set_client_info(client_info)
    await first.token_storage_adapter.set_tokens(token)

    second = MCPOAuth(f"{mcp_url}/", callback_port=51001)
    await second._initialize()

    assert await second.token_storage_adapter.get_tokens() == token
    assert await second.token_storage_adapter.get_client_info() == client_info
    assert second.context.client_info == client_info
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
async def test_oauth_storage_registers_tokens_when_written_and_loaded(tmp_path):
    access_token = "stored-oauth-access-token-12345"
    refresh_token = "stored-oauth-refresh-token-12345"
    storage = create_oauth_token_storage("https://mcp.example.com/mcp", tmp_path)
    reset_cache()
    try:
        await storage.set_tokens(OAuthToken(access_token=access_token, refresh_token=refresh_token))

        assert scrub_text(f"echo {access_token}") == f"echo {REDACTED}"
        assert scrub_text(f"echo {refresh_token}") == f"echo {REDACTED}"

        reset_cache()
        loaded = await storage.get_tokens()

        assert loaded is not None
        assert loaded.access_token == access_token
        assert loaded.refresh_token == refresh_token
        assert scrub_text(f"echo {access_token}") == f"echo {REDACTED}"
        assert scrub_text(f"echo {refresh_token}") == f"echo {REDACTED}"
    finally:
        reset_cache()


def test_mcp_oauth_leases_distinct_default_callback_ports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with patch(
        "testmcpy.src.mcp_client._find_available_port",
        side_effect=[51001, 51001, 51002],
    ) as find_port:
        first = MCPOAuth("https://mcp.example.com/mcp")
        second = MCPOAuth("https://mcp.example.com/mcp")

    assert first.redirect_port == 51001
    assert second.redirect_port == 51002
    assert find_port.call_count == 3
    assert (
        first.context.client_metadata.redirect_uris != second.context.client_metadata.redirect_uris
    )


@pytest.mark.asyncio
async def test_mcp_oauth_discards_registration_for_old_callback_port(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mcp_url = "https://mcp.example.com/mcp"
    first = MCPOAuth(mcp_url, callback_port=51001)
    token = OAuthToken(access_token="still-valid-access-token")
    client_info = OAuthClientInformationFull(
        redirect_uris=["http://localhost:51001/callback"],
        client_id="old-registration",
        client_secret="old-secret",
    )
    await first.token_storage_adapter.set_client_info(client_info)
    await first.token_storage_adapter.set_tokens(token)

    second = MCPOAuth(mcp_url, callback_port=51002)
    await second._initialize()

    assert second.context.client_info is None
    assert await second.token_storage_adapter.get_client_info() is None
    assert await second.token_storage_adapter.get_tokens() == token
    assert second.context.current_tokens == token


@pytest.mark.asyncio
async def test_oauth_sessions_keep_tokens_paired_with_client_registration():
    store = MemoryStore()
    mcp_url = "https://mcp.example.com/mcp"
    redirect_a = "http://localhost:51001/callback"
    redirect_b = "http://localhost:51002/callback"
    session_a = create_oauth_token_storage(
        mcp_url,
        key_value_store=store,
        redirect_uri=redirect_a,
    )
    session_b = create_oauth_token_storage(
        mcp_url,
        key_value_store=store,
        redirect_uri=redirect_b,
    )
    client_a = OAuthClientInformationFull(
        redirect_uris=[redirect_a],
        client_id="client-a",
        client_secret="secret-a",
    )
    client_b = OAuthClientInformationFull(
        redirect_uris=[redirect_b],
        client_id="client-b",
        client_secret="secret-b",
    )
    token_a = OAuthToken(access_token="token-a", refresh_token="refresh-a", expires_in=30)
    token_b = OAuthToken(access_token="token-b", refresh_token="refresh-b", expires_in=20)

    # DCR completes before token exchange. Neither pending registration can
    # become the endpoint-wide SDK token until its paired token is durable.
    await session_a.set_client_info(client_a)
    await session_b.set_client_info(client_b)
    assert await create_oauth_token_storage(mcp_url, key_value_store=store).get_tokens() is None

    with patch("testmcpy.src.oauth_storage.time.time", return_value=100.0):
        await session_b.set_tokens(token_b)
    with patch("testmcpy.src.oauth_storage.time.time", return_value=200.0):
        await session_a.set_tokens(token_a)

    reloaded_a = create_oauth_token_storage(
        mcp_url,
        key_value_store=store,
        redirect_uri=redirect_a,
    )
    reloaded_b = create_oauth_token_storage(
        mcp_url,
        key_value_store=store,
        redirect_uri=redirect_b,
    )
    assert await reloaded_a.get_tokens() == token_a
    assert await reloaded_a.get_client_info() == client_a
    assert await reloaded_a.get_token_expiry() == 230.0
    assert await reloaded_b.get_tokens() == token_b
    assert await reloaded_b.get_client_info() == client_b
    assert await reloaded_b.get_token_expiry() == 120.0

    sdk_reader = create_oauth_token_storage(mcp_url, key_value_store=store)
    assert await sdk_reader.get_tokens() == token_a
    assert await sdk_reader.get_client_info() is None
    assert await sdk_reader.get_token_expiry() == 230.0

    # A new callback may use the latest access token, but cannot refresh it
    # with another session's dynamically registered client.
    session_c = create_oauth_token_storage(
        mcp_url,
        key_value_store=store,
        redirect_uri="http://localhost:51003/callback",
    )
    assert await session_c.get_tokens() == token_a
    assert await session_c.get_client_info() is None

    # Clearing a non-active stale session cannot disturb the active pair.
    await session_b.clear()
    fresh_sdk_reader = create_oauth_token_storage(mcp_url, key_value_store=store)
    assert await fresh_sdk_reader.get_tokens() == token_a
    assert await fresh_sdk_reader.get_token_expiry() == 230.0


@pytest.mark.asyncio
async def test_same_redirect_concurrent_generations_never_cross_pair_credentials():
    store = MemoryStore()
    mcp_url = "https://mcp.example.com/mcp"
    redirect_uri = "http://localhost:51001/callback"
    generation_a = create_oauth_token_storage(
        mcp_url,
        key_value_store=store,
        redirect_uri=redirect_uri,
    )
    generation_b = create_oauth_token_storage(
        mcp_url,
        key_value_store=store,
        redirect_uri=redirect_uri,
    )
    client_a = OAuthClientInformationFull(
        redirect_uris=[redirect_uri],
        client_id="client-a",
        client_secret="secret-a",
    )
    client_b = OAuthClientInformationFull(
        redirect_uris=[redirect_uri],
        client_id="client-b",
        client_secret="secret-b",
    )
    token_a = OAuthToken(access_token="token-a", refresh_token="refresh-a")
    token_b = OAuthToken(access_token="token-b", refresh_token="refresh-b")

    await generation_a.set_client_info(client_a)
    await generation_b.set_client_info(client_b)
    await generation_a.set_tokens(token_a)

    after_a = create_oauth_token_storage(
        mcp_url,
        key_value_store=store,
        redirect_uri=redirect_uri,
    )
    assert await after_a.get_tokens() == token_a
    assert await after_a.get_client_info() == client_a

    await generation_b.set_tokens(token_b)
    after_b = create_oauth_token_storage(
        mcp_url,
        key_value_store=store,
        redirect_uri=redirect_uri,
    )
    assert await after_b.get_tokens() == token_b
    assert await after_b.get_client_info() == client_b

    # A stale adapter cannot delete or replace the newer generation on clear.
    await generation_a.clear()
    final_reader = create_oauth_token_storage(mcp_url, key_value_store=store)
    assert await final_reader.get_tokens() == token_b


@pytest.mark.asyncio
async def test_dangling_active_pointer_does_not_resurrect_legacy_token():
    store = MemoryStore()
    mcp_url = "https://mcp.example.com/mcp"
    legacy = TokenStorageAdapter(async_key_value=store, server_url=mcp_url)
    await legacy.set_tokens(OAuthToken(access_token="legacy-token"))
    session = create_oauth_token_storage(
        mcp_url,
        key_value_store=store,
        redirect_uri="http://localhost:51001/callback",
    )
    client_info = OAuthClientInformationFull(
        redirect_uris=["http://localhost:51001/callback"],
        client_id="new-client",
    )
    await session.set_client_info(client_info)
    await session.set_tokens(OAuthToken(access_token="new-token"))
    published_session_key = session._session_key
    await session._session_storage.delete(key=published_session_key)

    reader = create_oauth_token_storage(mcp_url, key_value_store=store)
    assert await reader.get_tokens() is None
    assert await reader.get_token_expiry() is None


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
