"""Security and lifecycle coverage for profile-backed test generation."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


def _write_profile(secret: str) -> None:
    Path(".llm_providers.yaml").write_text(
        f"""
default: secure
profiles:
  secure:
    name: Secure
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-test
        api_key: {secret}
        default: true
"""
    )


def _result(response: str):
    return SimpleNamespace(response=response, cost=0.01, token_usage={"total": 1})


def _request_body() -> dict:
    return {
        "tool_name": "list_items",
        "tool_description": "List items",
        "tool_schema": {"type": "object", "properties": {}},
        "coverage_level": "basic",
        "llm_profile": "secure",
    }


def _provider_with_echo(secret: str) -> AsyncMock:
    provider = AsyncMock()
    provider.generate_with_tools.side_effect = [
        _result(
            json.dumps(
                {
                    "test_scenarios": [
                        {"name": "basic", "description": f"echoed {secret}", "priority": "high"}
                    ],
                    "key_parameters": [],
                    "edge_cases": [],
                    "validation_points": [],
                }
            )
        ),
        _result(
            'version: "1.0"\n'
            "tests:\n"
            "  - name: test_secret_echo\n"
            f'    prompt: "upstream echoed {secret}"\n'
            "    evaluators:\n"
            "      - name: execution_successful\n"
        ),
    ]
    return provider


def test_regular_and_stream_generation_scrub_before_response_and_persistence(client):
    secret = "generation-profile-secret-12345"
    _write_profile(secret)
    regular_provider = _provider_with_echo(secret)
    stream_provider = _provider_with_echo(secret)

    with patch(
        "testmcpy.server.routers.tests.create_llm_provider",
        side_effect=[regular_provider, stream_provider],
    ):
        regular = client.post("/api/tests/generate", json=_request_body())
        streamed = client.post("/api/tests/generate/stream", json=_request_body())

    assert regular.status_code == 200
    assert streamed.status_code == 200
    assert secret not in regular.text
    assert secret not in streamed.text
    generated_files = list((Path.cwd() / "tests" / "list_items").glob("*.yaml"))
    assert generated_files
    assert all(secret not in path.read_text() for path in generated_files)
    log_files = [path for path in (Path.cwd() / ".generation_logs").rglob("*") if path.is_file()]
    assert all(secret not in path.read_text(errors="replace") for path in log_files)
    regular_provider.close.assert_awaited_once()
    stream_provider.close.assert_awaited_once()


def test_regular_and_stream_generation_close_provider_after_generation_error(client):
    _write_profile("generation-close-secret-12345")
    regular_provider = AsyncMock()
    regular_provider.generate_with_tools.side_effect = RuntimeError("generation failed")
    stream_provider = AsyncMock()
    stream_provider.generate_with_tools.side_effect = RuntimeError("generation failed")

    with patch(
        "testmcpy.server.routers.tests.create_llm_provider",
        side_effect=[regular_provider, stream_provider],
    ):
        regular = client.post("/api/tests/generate", json=_request_body())
        streamed = client.post("/api/tests/generate/stream", json=_request_body())

    assert regular.status_code == 500
    assert "generation failed" in regular.text
    assert streamed.status_code == 200
    assert "generation failed" in streamed.text
    regular_provider.close.assert_awaited_once()
    stream_provider.close.assert_awaited_once()


def test_optimize_docs_blank_profile_uses_default_profile_credentials(client):
    secret = "optimize-default-profile-secret-12345"
    _write_profile(secret)
    provider = AsyncMock()
    provider.generate_with_tools.return_value = SimpleNamespace(
        response="",
        tool_calls=[
            {
                "name": "submit_analysis",
                "arguments": {
                    "clarity_score": 80,
                    "issues": [
                        {
                            "category": "examples",
                            "severity": "low",
                            "issue": "No example",
                            "current": "List items",
                            "suggestion": "Add an example",
                        }
                    ],
                    "improved_description": "List items with a concrete example.",
                    "improvements": [
                        {
                            "issue": "No example",
                            "before": "List items",
                            "after": "List items, for example active records.",
                            "explanation": "Clarifies expected use.",
                        }
                    ],
                },
            }
        ],
        cost=0.01,
        duration=0.1,
    )

    with patch(
        "testmcpy.server.routers.tools.create_llm_provider",
        return_value=provider,
    ) as create_provider:
        response = client.post(
            "/api/mcp/optimize-docs",
            json={
                "tool_name": "list_items",
                "description": "List items",
                "input_schema": {"type": "object", "properties": {}},
                "provider": "openai",
                "model": "gpt-test",
                "llm_profile": "",
            },
        )

    assert response.status_code == 200
    assert create_provider.call_args.kwargs["api_key"] == secret
    provider.close.assert_awaited_once()
