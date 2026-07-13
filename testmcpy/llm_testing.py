"""Shared LLM provider connection checks for the API and CLI."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any
from urllib.parse import urlparse

from testmcpy.llm_profiles import _substitute_env_vars
from testmcpy.scrubber import register_secret, scrub_obj, scrub_text

_DEFAULT_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "gemini-sdk": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
    "grok": "XAI_API_KEY",
}

_UNSUPPORTED_LIVE_TESTS = {
    "assistant": "Assistant profiles require a workspace conversation to verify",
    "chatbot": "Assistant profiles require a workspace conversation to verify",
    "claude-code": "Claude Code authentication cannot be verified with a model API call",
    "claude-cli": "Claude CLI authentication cannot be verified with a model API call",
    "claude-sdk": "Claude Agent SDK authentication cannot be verified with a model API call",
    "codex": "Codex authentication cannot be verified with a model API call",
    "codex-cli": "Codex authentication cannot be verified with a model API call",
    "codex-sdk": "Codex SDK authentication cannot be verified with a model API call",
    "gemini-cli": "Gemini CLI authentication cannot be verified with a model API call",
    "gemini-sdk": "Gemini SDK authentication cannot be verified without starting an agent run",
}


def _result(started: float, *, success: bool, **values: Any) -> dict[str, Any]:
    return scrub_obj(
        {
            "success": success,
            "tested": values.pop("tested", True),
            "duration": time.monotonic() - started,
            **values,
        }
    )


def _safe_error(exc: Exception, secret: str | None) -> str:
    message = str(exc)
    if secret:
        message = message.replace(secret, "***")
    return scrub_text(message)


def _validate_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Base URL must not contain credentials or a fragment")
    return base_url.rstrip("/")


def _resolve_api_key(provider: str, api_key: str | None, api_key_env: str | None) -> str | None:
    if api_key:
        return str(_substitute_env_vars(api_key))
    if api_key_env:
        return os.environ.get(api_key_env)
    env_name = _DEFAULT_KEY_ENV.get(provider)
    return os.environ.get(env_name) if env_name else None


async def test_llm_provider_connection(
    *,
    provider: str,
    model: str,
    api_key: str | None = None,
    api_key_env: str | None = None,
    base_url: str | None = None,
    timeout: int = 30,
    workspace_hash: str | None = None,
    domain: str | None = None,
    api_token: str | None = None,
    api_secret: str | None = None,
    api_url: str | None = None,
    conversations_path: str | None = None,
    completions_path: str | None = None,
) -> dict[str, Any]:
    """Perform one bounded provider request without requiring a running web server."""
    started = time.monotonic()
    provider = provider.strip().lower()

    if not provider or not model.strip():
        return _result(started, success=False, error="Provider and model are required")
    if timeout < 1 or timeout > 300:
        return _result(started, success=False, error="Timeout must be between 1 and 300 seconds")
    if provider in _UNSUPPORTED_LIVE_TESTS:
        return _result(
            started,
            success=False,
            tested=False,
            error=_UNSUPPORTED_LIVE_TESTS[provider],
        )

    secret = _resolve_api_key(provider, api_key, api_key_env)
    register_secret(secret)
    required_env = _DEFAULT_KEY_ENV.get(provider)
    if required_env and not secret:
        source = api_key_env or required_env
        return _result(
            started,
            success=False,
            error=f"Environment variable {source} is not set; provide an API key or set the variable",
        )

    prompt = "Say 'test successful' in exactly 2 words."
    try:
        if provider == "anthropic":
            import anthropic

            async with anthropic.AsyncAnthropic(
                api_key=secret,
                base_url=_validate_base_url(base_url) if base_url else None,
                timeout=timeout,
                max_retries=0,
            ) as anthropic_client:
                anthropic_response = await asyncio.wait_for(
                    anthropic_client.messages.create(
                        model=model,
                        max_tokens=50,
                        messages=[{"role": "user", "content": prompt}],
                    ),
                    timeout=timeout,
                )
            response_text = next(
                (
                    block.text
                    for block in anthropic_response.content
                    if getattr(block, "type", None) == "text" and hasattr(block, "text")
                ),
                "",
            )
            return _result(
                started,
                success=True,
                response=response_text,
                model=model,
            )

        if provider in {"openai", "xai", "grok"}:
            from openai import AsyncOpenAI

            resolved_url = base_url
            if provider in {"xai", "grok"} and not resolved_url:
                resolved_url = "https://api.x.ai/v1"
            async with AsyncOpenAI(
                api_key=secret,
                base_url=_validate_base_url(resolved_url) if resolved_url else None,
                timeout=timeout,
                max_retries=0,
            ) as openai_client:
                openai_response = await asyncio.wait_for(
                    openai_client.chat.completions.create(
                        model=model,
                        max_tokens=50,
                        messages=[{"role": "user", "content": prompt}],
                    ),
                    timeout=timeout,
                )
            return _result(
                started,
                success=True,
                response=openai_response.choices[0].message.content or "",
                model=model,
            )

        if provider in {"google", "gemini"}:
            from google.genai import Client

            google_client = Client(api_key=secret, http_options={"timeout": timeout * 1000})
            try:
                google_response = await asyncio.wait_for(
                    google_client.aio.models.generate_content(model=model, contents=prompt),
                    timeout=timeout,
                )
            finally:
                await google_client.aio.aclose()
                google_client.close()
            return _result(
                started,
                success=True,
                response=google_response.text or "",
                model=model,
            )

        if provider == "ollama":
            import httpx

            resolved_url = _validate_base_url(base_url or "http://127.0.0.1:11434")
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as http_client:
                http_response = await http_client.post(
                    f"{resolved_url}/api/generate",
                    json={"model": model, "prompt": prompt, "stream": False},
                )
                http_response.raise_for_status()
                data = http_response.json()
            return _result(
                started,
                success=True,
                response=data.get("response", ""),
                model=model,
            )

        return _result(started, success=False, error=f"Unknown provider: {provider}")
    except asyncio.TimeoutError:
        return _result(
            started, success=False, error=f"Connection timed out after {timeout} seconds"
        )
    except Exception as exc:
        return _result(started, success=False, error=_safe_error(exc, secret))
