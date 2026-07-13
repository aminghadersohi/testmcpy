"""Persistent storage shared by interactive OAuth and SDK providers."""

import os
import tempfile
import time
from pathlib import Path

from cryptography.fernet import Fernet
from fastmcp.client.auth.oauth import TokenStorageAdapter
from key_value.aio.protocols import AsyncKeyValue
from mcp.client.auth.oauth2 import TokenStorage
from mcp.shared.auth import OAuthToken

_KEY_FILE_NAME = "oauth.key"
_TOKEN_METADATA_COLLECTION = "testmcpy-oauth-token-metadata"


class PersistentTokenStorageAdapter(TokenStorageAdapter):
    """Token adapter that also records acquisition time for SDK consumers."""

    def _metadata_key(self) -> str:
        return f"{self._server_url}/token_metadata"

    async def set_tokens(self, tokens: OAuthToken) -> None:
        await super().set_tokens(tokens)
        await self._key_value_store.put(
            key=self._metadata_key(),
            collection=_TOKEN_METADATA_COLLECTION,
            value={"stored_at": time.time()},
            ttl=60 * 60 * 24 * 365,
        )

    async def clear(self) -> None:
        await super().clear()
        await self._key_value_store.delete(
            key=self._metadata_key(),
            collection=_TOKEN_METADATA_COLLECTION,
        )

    async def get_token_expiry(self) -> float | None:
        tokens = await self.get_tokens()
        if tokens is None or tokens.expires_in is None:
            return None
        metadata = await self._key_value_store.get(
            key=self._metadata_key(),
            collection=_TOKEN_METADATA_COLLECTION,
        )
        stored_at = metadata.get("stored_at") if metadata else None
        if not isinstance(stored_at, int | float):
            return None
        return float(stored_at) + tokens.expires_in


def oauth_cache_dir() -> Path:
    """Return the workspace-local OAuth cache directory."""
    return Path.cwd() / ".testmcpy" / "oauth-cache"


def _load_or_create_encryption_key(directory: Path) -> bytes:
    """Load the cache key, creating it once without cross-process races."""
    key_path = directory / _KEY_FILE_NAME
    try:
        key = key_path.read_bytes()
    except FileNotFoundError:
        candidate = Fernet.generate_key()
        fd, temp_name = tempfile.mkstemp(prefix=".oauth-key-", dir=directory)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as key_file:
                key_file.write(candidate)
                key_file.flush()
                os.fsync(key_file.fileno())
            try:
                # A hard link publishes the fully-written key only if the
                # destination is still absent, without overwriting a winner.
                os.link(temp_path, key_path)
            except FileExistsError:
                key = key_path.read_bytes()
            else:
                key = candidate
        finally:
            temp_path.unlink(missing_ok=True)

    try:
        key_path.chmod(0o600)
    except OSError:
        pass
    # Validate eagerly so a corrupt key produces a clear cache-read failure.
    Fernet(key)
    return key


def create_oauth_key_value_store(cache_dir: Path | None = None) -> AsyncKeyValue:
    """Create FastMCP's encrypted, persistent AsyncKeyValue backend."""
    from key_value.aio.stores.disk import DiskStore
    from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

    directory = cache_dir or oauth_cache_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        directory.chmod(0o700)
    except OSError:
        # Some filesystems do not expose POSIX permissions. DiskStore still
        # provides the required cross-process persistence and locking.
        pass
    return FernetEncryptionWrapper(
        key_value=DiskStore(directory=directory),
        fernet=Fernet(_load_or_create_encryption_key(directory)),
        # A missing/replaced key invalidates old entries. Treat those as a
        # cache miss so interactive OAuth can repair the cache by logging in.
        raise_on_decryption_error=False,
    )


def create_oauth_token_storage(
    mcp_url: str,
    cache_dir: Path | None = None,
    key_value_store: AsyncKeyValue | None = None,
) -> TokenStorage:
    """Create the MCP SDK TokenStorage view for one normalized endpoint."""
    return PersistentTokenStorageAdapter(
        async_key_value=key_value_store or create_oauth_key_value_store(cache_dir),
        server_url=mcp_url.rstrip("/"),
    )
