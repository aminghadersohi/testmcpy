"""Persistent storage shared by interactive OAuth and SDK providers."""

import hashlib
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import cast

from cryptography.fernet import Fernet
from fastmcp.client.auth.oauth import TokenStorageAdapter
from key_value.aio.adapters.pydantic import PydanticAdapter
from key_value.aio.protocols import AsyncKeyValue
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import BaseModel

from testmcpy.scrubber import register_secret

_KEY_FILE_NAME = "oauth.key"
_TOKEN_METADATA_COLLECTION = "testmcpy-oauth-token-metadata"
_OAUTH_SESSION_COLLECTION = "testmcpy-oauth-sessions"
_OAUTH_ACTIVE_SESSION_COLLECTION = "testmcpy-oauth-active-session"
_OAUTH_REDIRECT_SESSION_COLLECTION = "testmcpy-oauth-redirect-session"
_CACHE_TTL_SECONDS = 60 * 60 * 24 * 365


class _OAuthSessionBundle(BaseModel):
    """One atomic DCR registration, token set, and acquisition timestamp."""

    redirect_uri: str | None = None
    client_info: OAuthClientInformationFull | None = None
    tokens: OAuthToken | None = None
    stored_at: float | None = None


class PersistentTokenStorageAdapter(TokenStorageAdapter):
    """Keep each callback registration paired with the tokens it issued."""

    def __init__(
        self,
        async_key_value: AsyncKeyValue,
        server_url: str,
        redirect_uri: str | None = None,
    ) -> None:
        super().__init__(async_key_value=async_key_value, server_url=server_url)
        self._redirect_uri = redirect_uri
        session_identity = redirect_uri or "endpoint-access-only"
        self._redirect_hash = hashlib.sha256(session_identity.encode()).hexdigest()
        self._session_key = self._new_session_key()
        self._active_session_key = f"{self._server_url}/active-oauth-session"
        self._redirect_session_key = f"{self._server_url}/oauth-redirects/{self._redirect_hash}"
        self._session_storage = PydanticAdapter[_OAuthSessionBundle](
            default_collection=_OAUTH_SESSION_COLLECTION,
            key_value=async_key_value,
            pydantic_model=_OAuthSessionBundle,
            raise_on_validation_error=True,
        )
        self._read_snapshot: _OAuthSessionBundle | None = None
        self._read_snapshot_is_owned = False
        self._read_snapshot_is_legacy = False
        self._snapshot_loaded = False
        self._redirect_pointer_loaded = redirect_uri is None
        self._ignore_redirect_pointer = False

    def _new_session_key(self) -> str:
        generation = secrets.token_hex(16)
        return f"{self._server_url}/oauth-sessions/{self._redirect_hash}/{generation}"

    def _metadata_key(self) -> str:
        return f"{self._server_url}/token_metadata"

    async def _read_session(self, key: str) -> _OAuthSessionBundle | None:
        return cast(_OAuthSessionBundle | None, await self._session_storage.get(key=key))

    async def _read_pointer(
        self,
        key: str,
        collection: str,
    ) -> tuple[bool, str | None, _OAuthSessionBundle | None]:
        pointer = await self._key_value_store.get(
            key=key,
            collection=collection,
        )
        if pointer is None:
            return False, None, None
        session_key = pointer.get("session_key") if isinstance(pointer, dict) else None
        if not isinstance(session_key, str):
            return True, None, None
        bundle = await self._read_session(session_key)
        return True, session_key, bundle

    async def _read_active_session(
        self,
    ) -> tuple[bool, str | None, _OAuthSessionBundle | None]:
        return await self._read_pointer(
            self._active_session_key,
            _OAUTH_ACTIVE_SESSION_COLLECTION,
        )

    async def _resolve_redirect_session(self) -> None:
        if self._redirect_pointer_loaded or self._ignore_redirect_pointer:
            return
        self._redirect_pointer_loaded = True
        exists, session_key, bundle = await self._read_pointer(
            self._redirect_session_key,
            _OAUTH_REDIRECT_SESSION_COLLECTION,
        )
        if (
            exists
            and session_key is not None
            and bundle is not None
            and bundle.redirect_uri == self._redirect_uri
        ):
            self._session_key = session_key

    async def _load_snapshot(self) -> _OAuthSessionBundle | None:
        await self._resolve_redirect_session()
        owned = await self._read_session(self._session_key)

        # Endpoint-only readers (SDK providers) always follow the latest complete
        # session. Interactive clients prefer their own paired registration.
        if self._redirect_uri is None:
            active_exists, _, bundle = await self._read_active_session()
            if bundle is not None and bundle.tokens is not None:
                self._set_snapshot(bundle, owned=False)
                return bundle
        elif owned is not None and owned.tokens is not None:
            self._set_snapshot(owned, owned=True)
            return owned
        else:
            active_exists = False

        if self._redirect_uri is not None:
            active_exists, session_key, bundle = await self._read_active_session()
        else:
            session_key = None
        if bundle is not None and bundle.tokens is not None:
            self._set_snapshot(bundle, owned=session_key == self._session_key)
            return bundle

        if owned is not None:
            self._set_snapshot(owned, owned=True)
            return owned

        if not active_exists:
            # Migrate the pre-session cache as access-only state. Never pair its
            # client registration with a new callback URI. A dangling active
            # pointer is intentionally a cache miss, not permission to resurrect
            # credentials that a new-format flow superseded.
            legacy_tokens = await super().get_tokens()
            if legacy_tokens is not None:
                snapshot = _OAuthSessionBundle(tokens=legacy_tokens)
                self._set_snapshot(snapshot, owned=False, legacy=True)
                return snapshot

        self._set_snapshot(None, owned=False)
        return None

    def _set_snapshot(
        self,
        snapshot: _OAuthSessionBundle | None,
        *,
        owned: bool,
        legacy: bool = False,
    ) -> None:
        self._read_snapshot = snapshot
        self._read_snapshot_is_owned = owned
        self._read_snapshot_is_legacy = legacy
        self._snapshot_loaded = True

    async def get_tokens(self) -> OAuthToken | None:
        snapshot = await self._load_snapshot()
        tokens = snapshot.tokens if snapshot is not None else None
        if tokens is not None:
            register_secret(tokens.access_token)
            register_secret(tokens.refresh_token)
        return tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        register_secret(tokens.access_token)
        register_secret(tokens.refresh_token)
        if not self._snapshot_loaded:
            await self._load_snapshot()
        client_info = (
            self._read_snapshot.client_info
            if self._read_snapshot is not None and self._read_snapshot_is_owned
            else None
        )
        bundle = _OAuthSessionBundle(
            redirect_uri=self._redirect_uri,
            client_info=client_info,
            tokens=tokens,
            stored_at=time.time(),
        )
        await self._session_storage.put(
            key=self._session_key,
            value=bundle,
            ttl=_CACHE_TTL_SECONDS,
        )
        if self._redirect_uri is not None:
            await self._key_value_store.put(
                key=self._redirect_session_key,
                collection=_OAUTH_REDIRECT_SESSION_COLLECTION,
                value={"session_key": self._session_key},
                ttl=_CACHE_TTL_SECONDS,
            )
        # Publish only after the complete bundle is durable. Concurrent writers
        # can replace this pointer, but it always identifies one coherent bundle.
        await self._key_value_store.put(
            key=self._active_session_key,
            collection=_OAUTH_ACTIVE_SESSION_COLLECTION,
            value={"session_key": self._session_key},
            ttl=_CACHE_TTL_SECONDS,
        )
        self._set_snapshot(bundle, owned=True)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        if not self._snapshot_loaded:
            await self._load_snapshot()
        if self._redirect_uri is None or not self._read_snapshot_is_owned:
            return None
        snapshot = self._read_snapshot
        return snapshot.client_info if snapshot is not None else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        if not self._snapshot_loaded:
            await self._load_snapshot()
        snapshot = self._read_snapshot if self._read_snapshot_is_owned else None
        preserve_tokens = snapshot is not None and snapshot.client_info == client_info
        if not preserve_tokens:
            self._session_key = self._new_session_key()
            self._ignore_redirect_pointer = True
        tokens = snapshot.tokens if snapshot is not None and preserve_tokens else None
        stored_at = snapshot.stored_at if snapshot is not None and preserve_tokens else None
        bundle = _OAuthSessionBundle(
            redirect_uri=self._redirect_uri,
            client_info=client_info,
            tokens=tokens,
            stored_at=stored_at,
        )
        await self._session_storage.put(
            key=self._session_key,
            value=bundle,
            ttl=_CACHE_TTL_SECONDS,
        )
        self._set_snapshot(bundle, owned=True)

    async def clear(self) -> None:
        # Abandon this generation instead of deleting a bundle that another
        # process may have refreshed after this adapter loaded it.
        self._session_key = self._new_session_key()
        self._ignore_redirect_pointer = True
        self._redirect_pointer_loaded = True
        self._set_snapshot(None, owned=False)

    async def clear_client_info(self) -> None:
        """Delete a stale DCR registration without discarding reusable tokens."""
        if not self._snapshot_loaded:
            await self._load_snapshot()
        snapshot = self._read_snapshot
        if snapshot is None:
            return
        self._session_key = self._new_session_key()
        self._ignore_redirect_pointer = True
        bundle = _OAuthSessionBundle(
            redirect_uri=self._redirect_uri,
            tokens=snapshot.tokens,
            stored_at=snapshot.stored_at,
        )
        await self._session_storage.put(
            key=self._session_key,
            value=bundle,
            ttl=_CACHE_TTL_SECONDS,
        )
        self._set_snapshot(bundle, owned=True)

    async def get_token_expiry(self) -> float | None:
        if not self._snapshot_loaded:
            await self._load_snapshot()
        snapshot = self._read_snapshot
        if snapshot is None or snapshot.tokens is None or snapshot.tokens.expires_in is None:
            return None
        if snapshot.stored_at is not None:
            return snapshot.stored_at + snapshot.tokens.expires_in
        if not self._read_snapshot_is_legacy:
            return None

        # Legacy caches stored acquisition time separately from the token.
        metadata = await self._key_value_store.get(
            key=self._metadata_key(),
            collection=_TOKEN_METADATA_COLLECTION,
        )
        stored_at = metadata.get("stored_at") if metadata else None
        if not isinstance(stored_at, int | float):
            return None
        return float(stored_at) + snapshot.tokens.expires_in


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
    redirect_uri: str | None = None,
) -> PersistentTokenStorageAdapter:
    """Create a paired OAuth session or endpoint-wide SDK token view."""
    return PersistentTokenStorageAdapter(
        async_key_value=key_value_store or create_oauth_key_value_store(cache_dir),
        server_url=mcp_url.rstrip("/"),
        redirect_uri=redirect_uri,
    )
