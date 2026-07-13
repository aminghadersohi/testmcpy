"""LLM provider profile and model registry endpoints."""

import hashlib
import hmac
import json
import os
import re
import secrets
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from testmcpy.llm_profiles import (
    LLM_PROFILE_ID_MAX_LENGTH,
    LLM_PROFILE_ID_PATTERN,
    validate_assistant_endpoint_path,
)

router = APIRouter(prefix="/api/llm", tags=["llm"])


def _none_if_blank(value):
    """Treat blank optional connection fields as absent without rewriting values."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


class CostEstimateRequest(BaseModel):
    model_id: str
    input_tokens: int = Field(ge=0, le=2_000_000_000)
    output_tokens: int = Field(ge=0, le=2_000_000_000)


class LLMTestRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=255)
    api_key: str | None = None  # Direct API key
    api_key_env: str | None = None  # Or env var name
    base_url: str | None = None
    timeout: int = Field(default=30, ge=1, le=300)
    profile_id: str | None = None
    provider_index: int | None = Field(default=None, ge=0)

    _normalize_blank_connection_fields = field_validator(
        "api_key",
        "api_key_env",
        "base_url",
        mode="before",
    )(_none_if_blank)


class AssistantAuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_token: str | None = None
    api_secret: str | None = None
    api_url: str | None = None

    _normalize_blank_connection_fields = field_validator(
        "api_token",
        "api_secret",
        "api_url",
        mode="before",
    )(_none_if_blank)


class LLMProviderRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=255)
    provider: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    model: str = Field(min_length=1, max_length=255)
    api_key: str | None = None
    api_key_env: str | None = Field(default=None, max_length=255)
    base_url: str | None = Field(default=None, max_length=2048)
    timeout: int = Field(default=60, ge=1, le=300)
    default: bool = False
    workspace_hash: str | None = Field(default=None, max_length=255)
    domain: str | None = Field(default=None, max_length=255)
    api_token: str | None = None
    api_secret: str | None = None
    api_url: str | None = Field(default=None, max_length=2048)
    conversations_path: str | None = Field(default=None, max_length=2048)
    completions_path: str | None = Field(default=None, max_length=2048)
    auth: AssistantAuthRequest | None = None

    _normalize_blank_connection_fields = field_validator(
        "api_key",
        "api_key_env",
        "base_url",
        "workspace_hash",
        "domain",
        "api_token",
        "api_secret",
        "api_url",
        "conversations_path",
        "completions_path",
        mode="before",
    )(_none_if_blank)


class LLMProfileRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    providers: list[LLMProviderRequest]

    @model_validator(mode="after")
    def one_default_provider(self):
        if sum(provider.default for provider in self.providers) > 1:
            raise ValueError("Only one provider can be the default")
        return self


ProfileId = Annotated[
    str,
    Path(min_length=1, max_length=LLM_PROFILE_ID_MAX_LENGTH, pattern=LLM_PROFILE_ID_PATTERN),
]

_ENV_REF = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")
_SECRET_FIELDS = ("api_key", "api_token", "api_secret")
_SECRET_KEY_PARTS = (
    "secret",
    "token",
    "password",
    "api_key",
    "apikey",
    "private_key",
    "privatekey",
    "access_key",
    "accesskey",
    "authorization",
    "auth",
    "bearer",
    "credential",
    "cookie",
)
_SECRET_CONTAINERS = {"headers", "http_headers", "extra_headers"}
_PUBLIC_CREDENTIAL_METADATA = {"api_key_env"}
_ENV_REFERENCE = re.compile(r"\$\{")
_ALLOWED_HTTP_ENV_NAMES = {
    "anthropic": {"ANTHROPIC_API_KEY"},
    "claude-code": {"ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"},
    "claude-cli": {"ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"},
    "claude-sdk": {"ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"},
    "openai": {"OPENAI_API_KEY"},
    "codex": {"OPENAI_API_KEY"},
    "codex-cli": {"OPENAI_API_KEY"},
    "codex-sdk": {"OPENAI_API_KEY"},
    "google": {"GOOGLE_API_KEY", "GEMINI_API_KEY"},
    "gemini": {"GOOGLE_API_KEY", "GEMINI_API_KEY"},
    "gemini-cli": {"GOOGLE_API_KEY", "GEMINI_API_KEY"},
    "gemini-sdk": {"GOOGLE_API_KEY", "GEMINI_API_KEY"},
    "openrouter": {"OPENROUTER_API_KEY"},
    "xai": {"XAI_API_KEY"},
    "grok": {"XAI_API_KEY"},
}
_OFFICIAL_TEST_BASE_URLS = {
    "anthropic": {"https://api.anthropic.com"},
    "openai": {"https://api.openai.com/v1"},
    "xai": {"https://api.x.ai/v1"},
    "grok": {"https://api.x.ai/v1"},
}
_CREDENTIAL_BINDING_FIELDS = (
    "provider",
    "api_key_env",
    "base_url",
    "workspace_hash",
    "domain",
    "api_url",
    "conversations_path",
    "completions_path",
)
_PROVIDER_IDENTITY_FIELDS = ("provider", "name", "model")
_PUBLIC_RESOLVED_FIELDS = (
    "name",
    "provider",
    "model",
    "api_key_env",
    "base_url",
    "workspace_hash",
    "domain",
    "api_url",
    "conversations_path",
    "completions_path",
)
_CONFIG_TOKEN_FIELD = "_config_token"
_CONFIG_TOKEN_KEY = secrets.token_bytes(32)


def _require_allowed_origin(request: Request) -> None:
    """Block cross-site browsers while keeping loopback Vite development working."""
    origin = request.headers.get("origin")
    if not origin:
        return

    configured = os.environ.get(
        "TESTMCPY_CORS_ORIGINS",
        "http://127.0.0.1:3000,http://localhost:3000,http://[::1]:3000,"
        "http://127.0.0.1:8000,http://localhost:8000,http://[::1]:8000",
    )
    configured_origins = {
        item.strip().rstrip("/") for item in configured.split(",") if item.strip()
    }
    if "*" in configured_origins:
        return
    expected = str(request.base_url).rstrip("/")
    trusted_host = request.scope.get("state", {}).get("testmcpy_trusted_host", False)
    if trusted_host and origin.rstrip("/") == expected:
        return
    if origin.rstrip("/") not in configured_origins:
        raise HTTPException(status_code=403, detail="Cross-origin LLM configuration request denied")


def _mask_secret(value: str | None) -> str | None:
    if not value or _ENV_REF.fullmatch(value):
        return value
    return "***"


def _public_provider(provider) -> dict:
    data = _redact_unknown_secrets(provider.to_dict())
    # Runtime/display values must be usable by the UI. The PUT path restores
    # unchanged raw environment expressions before saving them back to disk.
    for field in _PUBLIC_RESOLVED_FIELDS:
        if field in data:
            data[field] = getattr(provider, field)
    for field in _SECRET_FIELDS:
        if field in data:
            data[field] = _mask_secret(data[field])
    return data


def _redact_unknown_secrets(value, key: str = ""):
    if isinstance(value, dict):
        public = {}
        for item_key, item in value.items():
            if not isinstance(item_key, str):
                continue
            normalized_key = re.sub(r"[^a-z0-9]+", "_", item_key.lower()).strip("_")
            if item_key not in (*_SECRET_FIELDS, *_PUBLIC_CREDENTIAL_METADATA) and (
                normalized_key in _SECRET_CONTAINERS
                or normalized_key.endswith("_headers")
                or any(part in normalized_key for part in _SECRET_KEY_PARTS)
            ):
                continue
            public[item_key] = _redact_unknown_secrets(item, item_key)
        return public
    if isinstance(value, list):
        return [_redact_unknown_secrets(item, key) for item in value]
    normalized_key = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    if key in _PUBLIC_CREDENTIAL_METADATA:
        return value
    if any(part in normalized_key for part in _SECRET_KEY_PARTS):
        return _mask_secret(str(value)) if value is not None else None
    return value


def _resolve_secret(incoming: str | None, existing: str | None) -> str | None:
    return existing if incoming == "***" else incoming


def _stored_value(provider, field: str):
    return vars(provider).get(field) if provider is not None else None


def _preserve_unchanged_env_value(value: str, existing, field: str) -> str:
    """Keep an environment expression raw when the UI returns its resolved value."""
    stored = _stored_value(existing, field)
    if (
        isinstance(stored, str)
        and _ENV_REFERENCE.search(stored)
        and value == getattr(existing, field)
    ):
        return stored
    return value


def _request_value(request: LLMProviderRequest, field: str, existing=None):
    if field in request.model_fields_set:
        return getattr(request, field)
    if request.auth and field in request.auth.model_fields_set:
        return getattr(request.auth, field)
    return _stored_value(existing, field)


def _credential_binding_matches(request: LLMProviderRequest, existing) -> bool:
    """Only reuse a stored secret when its source and destination are unchanged."""
    if existing is None:
        return False
    for field in _CREDENTIAL_BINDING_FIELDS:
        incoming = _request_value(request, field, existing)
        stored = _stored_value(existing, field)
        if incoming == stored:
            continue
        if (
            isinstance(stored, str)
            and _ENV_REFERENCE.search(stored)
            and incoming == getattr(existing, field)
        ):
            continue
        return False
    return True


def _provider_identity_matches(request: LLMProviderRequest, existing) -> bool:
    for field in _PROVIDER_IDENTITY_FIELDS:
        incoming = _request_value(request, field, existing)
        stored = _stored_value(existing, field)
        if incoming == stored:
            continue
        if (
            isinstance(stored, str)
            and _ENV_REFERENCE.search(stored)
            and incoming == getattr(existing, field)
        ):
            continue
        return False
    return True


def _provider_config_token(profile_id: str, index: int, provider) -> str:
    """Bind a masked row to its exact source revision without exposing secrets."""

    def canonicalize(value):
        if isinstance(value, dict):
            items = [
                (
                    f"{type(key).__module__}.{type(key).__qualname__}:{key!r}",
                    canonicalize(item),
                )
                for key, item in value.items()
            ]
            return {"mapping": sorted(items, key=lambda item: item[0])}
        if isinstance(value, (list, tuple)):
            return {"sequence": [canonicalize(item) for item in value]}
        if value is None or isinstance(value, (bool, int, float, str)):
            return {"type": type(value).__name__, "value": value}
        return {
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": repr(value),
        }

    payload = json.dumps(
        {
            "profile_id": profile_id,
            "index": index,
            "provider": canonicalize(provider.to_dict()),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=repr,
    ).encode()
    return hmac.new(_CONFIG_TOKEN_KEY, payload, hashlib.sha256).hexdigest()


def _validate_http_provider_credentials(request: LLMProviderRequest, existing=None) -> None:
    """Prevent HTTP-managed profiles from referencing arbitrary process secrets."""
    for field in _PUBLIC_RESOLVED_FIELDS:
        incoming = _request_value(request, field, existing)
        stored = _stored_value(existing, field)
        if isinstance(incoming, str) and _ENV_REFERENCE.search(incoming) and incoming != stored:
            raise ValueError(
                f"{field} cannot add an environment reference through the API; "
                "edit the local profile file instead"
            )

    for field in _SECRET_FIELDS:
        incoming = _request_value(request, field, existing)
        stored = _stored_value(existing, field)
        if (
            isinstance(incoming, str)
            and incoming != "***"
            and _ENV_REFERENCE.search(incoming)
            and incoming != stored
        ):
            raise ValueError(
                f"{field} cannot add an environment reference through the API; "
                "use api_key_env or edit the local profile file"
            )

    incoming_env = _request_value(request, "api_key_env", existing)
    stored_env = _stored_value(existing, "api_key_env")
    resolved_stored_env = getattr(existing, "api_key_env", None) if existing else None
    allowed_envs = _ALLOWED_HTTP_ENV_NAMES.get(request.provider, set())
    if (
        incoming_env
        and incoming_env not in {stored_env, resolved_stored_env}
        and incoming_env not in allowed_envs
    ):
        raise ValueError(
            f"Environment variable '{incoming_env}' is not allowed for {request.provider} "
            "through the API; use the provider's standard variable or edit the local profile file"
        )

    base_url = _request_value(request, "base_url", existing)
    if not base_url or request.provider not in _OFFICIAL_TEST_BASE_URLS:
        return
    normalized_url = str(base_url).rstrip("/")
    if normalized_url in _OFFICIAL_TEST_BASE_URLS[request.provider]:
        return

    direct_key = _request_value(request, "api_key", existing)
    supplied_direct_key = bool(direct_key and direct_key != "***")
    if not supplied_direct_key and not _credential_binding_matches(request, existing):
        raise ValueError(
            "A custom provider base URL requires a direct API key supplied in the same request"
        )


def _validate_profile_environment_references(body: LLMProfileRequest, existing=None) -> None:
    """Only profile-file authors may introduce lazily resolved public values."""
    for field in ("name", "description"):
        incoming = getattr(body, field)
        stored = _stored_value(existing, field)
        if isinstance(incoming, str) and _ENV_REFERENCE.search(incoming) and incoming != stored:
            raise ValueError(
                f"{field} cannot add an environment reference through the API; "
                "edit the local profile file instead"
            )


def _provider_from_request(request: LLMProviderRequest, existing=None):
    from testmcpy.llm_profiles import LLMProviderConfig

    _validate_http_provider_credentials(request, existing)
    known_fields = set(LLMProviderConfig.__dataclass_fields__) - {"_extra"}
    existing_values = existing.to_dict() if existing else {}
    dumped = request.model_dump(exclude={"auth"}, exclude_unset=existing is not None)
    dumped.pop("_config_index", None)
    dumped.pop(_CONFIG_TOKEN_FIELD, None)
    values = {key: value for key, value in dumped.items() if key in known_fields}
    if request.auth:
        auth_values = request.auth.model_dump(exclude_unset=True)
        for key, value in auth_values.items():
            # Explicit top-level fields are the canonical representation and
            # take precedence. Nested auth remains supported for older clients.
            if key not in request.model_fields_set:
                values[key] = value
    if existing:
        for field in known_fields - values.keys():
            if field in existing_values:
                values[field] = existing_values[field]
        for field in _PUBLIC_RESOLVED_FIELDS:
            raw_value = existing_values.get(field)
            if (
                isinstance(raw_value, str)
                and _ENV_REFERENCE.search(raw_value)
                and values.get(field) == getattr(existing, field)
            ):
                values[field] = raw_value
    extra = dict(getattr(existing, "_extra", {}) or {})
    extra.update({key: value for key, value in dumped.items() if key not in known_fields})

    for field in _SECRET_FIELDS:
        old_value = existing_values.get(field)
        if values.get(field) == "***" and old_value is None:
            raise ValueError(
                "A masked credential cannot be reused after its provider or destination changes"
            )
        values[field] = _resolve_secret(values.get(field), old_value)
    provider_config = LLMProviderConfig(**values, _extra=extra)
    if provider_config.provider in {"assistant", "chatbot"}:
        required = {
            "workspace_hash": "workspace_hash",
            "domain": "domain",
            "api_token": "api_token",
            "api_secret": "api_secret",
            "api_url": "api_url",
            "conversations_path": "conversations_path",
            "completions_path": "completions_path",
        }
        missing = [
            label for field, label in required.items() if not getattr(provider_config, field)
        ]
        if missing:
            raise ValueError(f"Assistant provider requires {', '.join(missing)}")

        api_url = str(provider_config.api_url)
        if not _ENV_REF.fullmatch(api_url):
            parsed = urlsplit(api_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("Assistant api_url must be an absolute HTTP(S) URL")
        for field in ("conversations_path", "completions_path"):
            path = str(getattr(provider_config, field))
            validate_assistant_endpoint_path(path, field)
    return provider_config


def _match_existing_providers(
    profile_id: str,
    requests: list[LLMProviderRequest],
    existing: list,
) -> list:
    """Match masked update rows to their stored provider even after deletion/reordering."""
    unmatched = set(range(len(existing)))
    matches = []
    legacy_request = not any(
        (provider.model_extra or {}).get(_CONFIG_TOKEN_FIELD) is not None for provider in requests
    )
    for index, provider in enumerate(requests):
        index_hint = (provider.model_extra or {}).get("_config_index")
        token_hint = (provider.model_extra or {}).get(_CONFIG_TOKEN_FIELD)
        token_valid = (
            isinstance(index_hint, int)
            and 0 <= index_hint < len(existing)
            and isinstance(token_hint, str)
            and hmac.compare_digest(
                token_hint,
                _provider_config_token(profile_id, index_hint, existing[index_hint]),
            )
        )
        if token_hint is not None and not token_valid:
            raise HTTPException(
                status_code=409,
                detail="LLM provider configuration changed; reload the profile before saving",
            )
        exact = (
            index_hint
            if token_valid
            and index_hint in unmatched
            and _credential_binding_matches(provider, existing[index_hint])
            else None
        )
        # Older API clients did not receive revision tokens. Preserve their
        # unchanged-row behavior, but never fall back when a supplied token is
        # stale or paired with a forged index.
        if exact is None and legacy_request:
            exact = next(
                (
                    candidate
                    for candidate in unmatched
                    if _credential_binding_matches(provider, existing[candidate])
                    and (
                        _stored_value(existing[candidate], "provider"),
                        _stored_value(existing[candidate], "name"),
                        _stored_value(existing[candidate], "model"),
                    )
                    == (provider.provider, provider.name, provider.model)
                ),
                None,
            )
        if (
            exact is None
            and legacy_request
            and index in unmatched
            and _credential_binding_matches(provider, existing[index])
            and _provider_identity_matches(provider, existing[index])
        ):
            exact = index
        matches.append(existing[exact] if exact is not None else None)
        if exact is not None:
            unmatched.remove(exact)
    return matches


def _load_profile_config():
    from testmcpy.llm_profiles import reload_llm_profile_config

    config = reload_llm_profile_config()
    if config.load_error:
        raise HTTPException(
            status_code=409,
            detail=f"Invalid .llm_providers.yaml: {config.load_error}",
        )
    return config


def _validate_ad_hoc_test_request(body: LLMTestRequest) -> None:
    """Keep caller-selected destinations from receiving server-owned secrets."""
    provider = body.provider.strip().lower()
    if body.api_key == "***":
        raise HTTPException(
            status_code=400,
            detail="A masked credential can only be tested with its profile and provider index",
        )
    if body.api_key and _ENV_REFERENCE.search(body.api_key):
        raise HTTPException(
            status_code=400, detail="API keys cannot contain environment references"
        )

    allowed_envs = _ALLOWED_HTTP_ENV_NAMES.get(provider, set())
    if body.api_key_env and body.api_key_env not in allowed_envs:
        raise HTTPException(
            status_code=400,
            detail=f"Environment variable '{body.api_key_env}' is not allowed for {provider}",
        )

    if body.base_url and provider in _OFFICIAL_TEST_BASE_URLS and not body.api_key:
        normalized_url = body.base_url.rstrip("/")
        if normalized_url not in _OFFICIAL_TEST_BASE_URLS[provider]:
            raise HTTPException(
                status_code=400,
                detail="A custom provider base URL requires a direct API key",
            )


# LLM Provider Profile endpoints


@router.get("/profiles")
async def list_llm_profiles(response: Response):
    """List available LLM provider profiles from .llm_providers.yaml."""
    try:
        response.headers["Cache-Control"] = "no-store"
        profile_config = _load_profile_config()
        if not profile_config.has_profiles():
            return {
                "profiles": [],
                "default": None,
                "message": "No .llm_providers.yaml file found",
            }

        profiles_list = []
        for profile_id in profile_config.list_profiles():
            profile = profile_config.get_profile(profile_id)
            if not profile:
                continue

            providers_info = []
            for index, provider in enumerate(profile.providers):
                public_provider = _public_provider(provider)
                public_provider["_config_index"] = index
                public_provider[_CONFIG_TOKEN_FIELD] = _provider_config_token(
                    profile.profile_id,
                    index,
                    provider,
                )
                providers_info.append(public_provider)

            profiles_list.append(
                {
                    "profile_id": profile.profile_id,
                    "name": profile.name,
                    "description": profile.description,
                    "providers": providers_info,
                }
            )

        default_profile = profile_config.get_profile()
        return {
            "profiles": profiles_list,
            "default": default_profile.profile_id if default_profile else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/profiles/{profile_id}")
async def create_llm_profile(
    profile_id: ProfileId,
    body: LLMProfileRequest,
    http_request: Request,
):
    """Create a new LLM provider profile."""
    from testmcpy.llm_profiles import (
        LLMProfile,
        reload_llm_profile_config,
    )

    _require_allowed_origin(http_request)
    try:
        profile_config = _load_profile_config()
        if profile_id in profile_config.profiles:
            raise HTTPException(status_code=409, detail=f"Profile '{profile_id}' already exists")
        _validate_profile_environment_references(body)

        profile = LLMProfile(
            profile_id=profile_id,
            name=body.name,
            description=body.description,
            providers=[_provider_from_request(provider) for provider in body.providers],
            _extra=dict(body.model_extra or {}),
        )

        profile_config.add_profile(profile)
        profile_config.save()
        reload_llm_profile_config()

        return {"success": True, "profile_id": profile_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/profiles/{profile_id}")
async def update_llm_profile(
    profile_id: ProfileId,
    body: LLMProfileRequest,
    http_request: Request,
):
    """Update an existing LLM provider profile."""
    from testmcpy.llm_profiles import (
        LLMProfile,
        reload_llm_profile_config,
    )

    _require_allowed_origin(http_request)
    try:
        profile_config = _load_profile_config()

        if profile_id not in profile_config.profiles:
            raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")

        existing_profile = profile_config.profiles[profile_id]
        _validate_profile_environment_references(body, existing_profile)
        matched_existing = _match_existing_providers(
            profile_id,
            body.providers,
            existing_profile.providers,
        )
        providers = [
            _provider_from_request(provider, matched_existing[index])
            for index, provider in enumerate(body.providers)
        ]

        profile_extra = dict(existing_profile._extra)
        profile_extra.update(body.model_extra or {})

        profile = LLMProfile(
            profile_id=profile_id,
            name=_preserve_unchanged_env_value(body.name, existing_profile, "name"),
            description=_preserve_unchanged_env_value(
                body.description,
                existing_profile,
                "description",
            ),
            providers=providers,
            _extra=profile_extra,
        )

        profile_config.add_profile(profile)
        profile_config.save()
        reload_llm_profile_config()

        return {"success": True, "profile_id": profile_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/profiles/{profile_id}")
async def delete_llm_profile(profile_id: ProfileId, http_request: Request):
    """Delete an LLM provider profile."""
    from testmcpy.llm_profiles import reload_llm_profile_config

    _require_allowed_origin(http_request)
    try:
        profile_config = _load_profile_config()

        if profile_id not in profile_config.profiles:
            raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")

        profile_config.remove_profile(profile_id)
        profile_config.save()
        reload_llm_profile_config()

        return {"success": True, "profile_id": profile_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/profiles/default/{profile_id}")
async def set_default_llm_profile(profile_id: ProfileId, http_request: Request):
    """Set the default LLM provider profile."""
    from testmcpy.llm_profiles import reload_llm_profile_config

    _require_allowed_origin(http_request)
    try:
        profile_config = _load_profile_config()
        profile_config.set_default_profile(profile_id)
        profile_config.save()
        reload_llm_profile_config()

        return {"success": True, "default_profile": profile_id}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Model Registry endpoints


@router.get("/models")
async def list_all_models():
    """List all available LLM models with metadata."""
    from testmcpy.src.model_registry import list_all_models

    return {"models": list_all_models()}


@router.get("/providers")
async def list_all_providers():
    """List all available LLM providers with their models."""
    from testmcpy.src.model_registry import list_providers

    return {"providers": list_providers()}


@router.get("/models/{model_id}")
async def get_model_info(model_id: str):
    """Get detailed info for a specific model."""
    from testmcpy.src.model_registry import get_model

    model = get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")

    return model.to_dict()


@router.get("/providers/{provider}/models")
async def get_provider_models(provider: str):
    """Get all models for a specific provider."""
    from testmcpy.src.model_registry import get_default_model, get_models_by_provider

    models = get_models_by_provider(provider)
    if not models:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not found")

    default = get_default_model(provider)
    return {
        "provider": provider,
        "models": [m.to_dict() for m in models],
        "default_model": default.id if default else None,
    }


@router.post("/estimate-cost")
async def estimate_model_cost(request: CostEstimateRequest):
    """Estimate cost for a model with given token usage."""
    from testmcpy.src.model_registry import estimate_cost, get_model

    model = get_model(request.model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{request.model_id}' not found")

    cost = estimate_cost(request.model_id, request.input_tokens, request.output_tokens)
    return {
        "model_id": request.model_id,
        "input_tokens": request.input_tokens,
        "output_tokens": request.output_tokens,
        "estimated_cost_usd": round(cost, 6),
        "input_price_per_1m": model.input_price_per_1m,
        "output_price_per_1m": model.output_price_per_1m,
    }


@router.post("/test")
async def test_llm_provider(body: LLMTestRequest, http_request: Request):
    """Test a provider with a bounded request, resolving masked saved secrets server-side."""
    from testmcpy.llm_testing import test_llm_provider_connection

    _require_allowed_origin(http_request)
    values = body.model_dump(exclude={"profile_id", "provider_index"})

    if body.profile_id is not None or body.provider_index is not None:
        if body.profile_id is None or body.provider_index is None:
            raise HTTPException(
                status_code=422,
                detail="profile_id and provider_index must be provided together",
            )
        config = _load_profile_config()
        profile = config.get_profile(body.profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail=f"Profile '{body.profile_id}' not found")
        if body.provider_index >= len(profile.providers):
            raise HTTPException(status_code=404, detail="Provider not found")
        provider = profile.providers[body.provider_index]
        values.update(
            provider=provider.provider,
            model=provider.model,
            api_key=provider.api_key,
            api_key_env=provider.api_key_env,
            base_url=provider.base_url,
            timeout=provider.timeout,
        )
    else:
        _validate_ad_hoc_test_request(body)

    return await test_llm_provider_connection(**values)
