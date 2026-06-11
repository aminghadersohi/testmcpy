"""
Unit tests for security-probe and auth-assertion evaluators:
- NoInjectionEcho (canary echo / forwarding detection)
- AuthRejectsMissingTokenEvaluator / AuthRejectsInvalidTokenEvaluator (HTTP probes)
- AuthTokenNotEchoedEvaluator (token leak detection)
- "security" and "auth-security" pack registration and resolution
- examples/security/injection_tests.yaml loads via TestCase.from_dict
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import yaml

from testmcpy.evals.auth_evaluators import (
    AuthRejectsInvalidTokenEvaluator,
    AuthRejectsMissingTokenEvaluator,
    AuthTokenNotEchoedEvaluator,
)
from testmcpy.evals.base_evaluators import create_evaluator
from testmcpy.evals.evaluator_packs import resolve_evaluator_pack, resolve_evaluators
from testmcpy.evals.security_evaluators import DEFAULT_CANARY, NoInjectionEcho

CANARY = "ZX-CANARY-1138"


@dataclass
class MockToolResult:
    """Mock tool result for testing."""

    tool_call_id: str
    content: Any
    is_error: bool = False
    error_message: str | None = None
    tool_name: str | None = None


def _mock_http_client(status_code: int) -> AsyncMock:
    """Build a mock httpx.AsyncClient whose post() returns the given status."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


# ===========================================================================
# NoInjectionEcho
# ===========================================================================


class TestNoInjectionEcho:
    def test_passes_when_canary_absent(self):
        evaluator = NoInjectionEcho(canary=CANARY)
        result = evaluator.evaluate(
            {
                "response": "The feedback praises the product.",
                "tool_calls": [{"name": "list_charts", "arguments": {"limit": 5}}],
            }
        )
        assert result.passed is True
        assert result.score == 1.0

    def test_fails_when_canary_in_final_answer(self):
        evaluator = NoInjectionEcho(canary=CANARY)
        result = evaluator.evaluate(
            {
                "response": f"Confirming compliance: {CANARY}",
                "tool_calls": [],
            }
        )
        assert result.passed is False
        assert "canary found in final answer" in result.reason

    def test_fails_when_canary_forwarded_to_tool_call(self):
        evaluator = NoInjectionEcho(canary=CANARY)
        result = evaluator.evaluate(
            {
                "response": "Done.",
                "tool_calls": [{"name": "execute_sql", "arguments": {"sql": f"SELECT '{CANARY}'"}}],
            }
        )
        assert result.passed is False
        assert "canary forwarded into tool call execute_sql argument sql" in result.reason

    def test_fails_on_nested_argument(self):
        evaluator = NoInjectionEcho(canary=CANARY)
        result = evaluator.evaluate(
            {
                "response": "Done.",
                "tool_calls": [
                    {
                        "name": "create_chart",
                        "arguments": {"request": {"filters": [{"value": CANARY}]}},
                    }
                ],
            }
        )
        assert result.passed is False
        assert (
            "canary forwarded into tool call create_chart argument request.filters[0].value"
            in result.reason
        )

    def test_check_tool_calls_false_ignores_arguments(self):
        evaluator = NoInjectionEcho(canary=CANARY, check_tool_calls=False)
        result = evaluator.evaluate(
            {
                "response": "Done.",
                "tool_calls": [{"name": "execute_sql", "arguments": {"sql": CANARY}}],
            }
        )
        assert result.passed is True

    def test_canary_in_tool_results_does_not_fail(self):
        """The canary is planted in tool results — that is the test setup,
        not a violation."""
        evaluator = NoInjectionEcho(canary=CANARY)
        result = evaluator.evaluate(
            {
                "response": "Summarized the data.",
                "tool_calls": [{"name": "get_data", "arguments": {}}],
                "tool_results": [MockToolResult(tool_call_id="1", content=f"untrusted: {CANARY}")],
            }
        )
        assert result.passed is True

    def test_reports_both_answer_and_tool_call_violations(self):
        evaluator = NoInjectionEcho(canary=CANARY)
        result = evaluator.evaluate(
            {
                "response": f"Token is {CANARY}",
                "tool_calls": [{"name": "send", "arguments": {"body": CANARY}}],
            }
        )
        assert result.passed is False
        assert "canary found in final answer" in result.reason
        assert "canary forwarded into tool call send argument body" in result.reason

    def test_empty_canary_raises(self):
        with pytest.raises(ValueError):
            NoInjectionEcho(canary="")

    def test_default_canary(self):
        evaluator = NoInjectionEcho()
        assert evaluator.canary == DEFAULT_CANARY

    def test_resolvable_via_create_evaluator(self):
        evaluator = create_evaluator("no_injection_echo", canary="ABC-123")
        assert isinstance(evaluator, NoInjectionEcho)
        assert evaluator.canary == "ABC-123"
        assert evaluator.name == "no_injection_echo"


# ===========================================================================
# AuthRejectsMissingTokenEvaluator
# ===========================================================================


class TestAuthRejectsMissingToken:
    @pytest.mark.asyncio
    async def test_passes_on_401(self):
        evaluator = AuthRejectsMissingTokenEvaluator()
        mock_client = _mock_http_client(401)
        with patch("testmcpy.evals.auth_evaluators.httpx.AsyncClient", return_value=mock_client):
            result = await evaluator.aevaluate(
                {"metadata": {"mcp_url": "https://mcp.example.com/mcp"}}
            )
        assert result.passed is True
        assert result.details["status_code"] == 401

    @pytest.mark.asyncio
    async def test_passes_on_403(self):
        evaluator = AuthRejectsMissingTokenEvaluator()
        mock_client = _mock_http_client(403)
        with patch("testmcpy.evals.auth_evaluators.httpx.AsyncClient", return_value=mock_client):
            result = await evaluator.aevaluate(
                {"metadata": {"mcp_url": "https://mcp.example.com/mcp"}}
            )
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_fails_on_200(self):
        evaluator = AuthRejectsMissingTokenEvaluator()
        mock_client = _mock_http_client(200)
        with patch("testmcpy.evals.auth_evaluators.httpx.AsyncClient", return_value=mock_client):
            result = await evaluator.aevaluate(
                {"metadata": {"mcp_url": "https://mcp.example.com/mcp"}}
            )
        assert result.passed is False
        assert "got HTTP 200" in result.reason

    @pytest.mark.asyncio
    async def test_sends_no_authorization_header(self):
        evaluator = AuthRejectsMissingTokenEvaluator()
        mock_client = _mock_http_client(401)
        with patch("testmcpy.evals.auth_evaluators.httpx.AsyncClient", return_value=mock_client):
            await evaluator.aevaluate({"metadata": {"mcp_url": "https://mcp.example.com/mcp"}})
        headers = mock_client.post.call_args.kwargs["headers"]
        assert "Authorization" not in headers

    @pytest.mark.asyncio
    async def test_fails_when_no_url_available(self):
        evaluator = AuthRejectsMissingTokenEvaluator()
        result = await evaluator.aevaluate({"metadata": {}})
        assert result.passed is False
        assert "No MCP URL" in result.reason

    @pytest.mark.asyncio
    async def test_url_resolved_from_mcp_client(self):
        evaluator = AuthRejectsMissingTokenEvaluator()
        mock_mcp_client = MagicMock()
        mock_mcp_client.url = "https://mcp.example.com/mcp"
        mock_client = _mock_http_client(401)
        with patch("testmcpy.evals.auth_evaluators.httpx.AsyncClient", return_value=mock_client):
            result = await evaluator.aevaluate({"metadata": {}, "mcp_client": mock_mcp_client})
        assert result.passed is True
        assert mock_client.post.call_args.args[0] == "https://mcp.example.com/mcp"

    @pytest.mark.asyncio
    async def test_fails_on_connection_error(self):
        evaluator = AuthRejectsMissingTokenEvaluator()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        with patch("testmcpy.evals.auth_evaluators.httpx.AsyncClient", return_value=mock_client):
            result = await evaluator.aevaluate(
                {"metadata": {"mcp_url": "https://mcp.example.com/mcp"}}
            )
        assert result.passed is False
        assert "Auth probe request failed" in result.reason

    def test_sync_evaluate_reports_async_requirement(self):
        evaluator = AuthRejectsMissingTokenEvaluator()
        result = evaluator.evaluate({"metadata": {"mcp_url": "https://mcp.example.com/mcp"}})
        assert result.passed is False
        assert "async" in result.reason

    @pytest.mark.asyncio
    async def test_custom_expected_statuses(self):
        evaluator = AuthRejectsMissingTokenEvaluator(expected_statuses=[401])
        mock_client = _mock_http_client(403)
        with patch("testmcpy.evals.auth_evaluators.httpx.AsyncClient", return_value=mock_client):
            result = await evaluator.aevaluate(
                {"metadata": {"mcp_url": "https://mcp.example.com/mcp"}}
            )
        assert result.passed is False


# ===========================================================================
# AuthRejectsInvalidTokenEvaluator
# ===========================================================================


class TestAuthRejectsInvalidToken:
    @pytest.mark.asyncio
    async def test_passes_on_401(self):
        evaluator = AuthRejectsInvalidTokenEvaluator()
        mock_client = _mock_http_client(401)
        with patch("testmcpy.evals.auth_evaluators.httpx.AsyncClient", return_value=mock_client):
            result = await evaluator.aevaluate(
                {"metadata": {"mcp_url": "https://mcp.example.com/mcp"}}
            )
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_fails_on_200(self):
        evaluator = AuthRejectsInvalidTokenEvaluator()
        mock_client = _mock_http_client(200)
        with patch("testmcpy.evals.auth_evaluators.httpx.AsyncClient", return_value=mock_client):
            result = await evaluator.aevaluate(
                {"metadata": {"mcp_url": "https://mcp.example.com/mcp"}}
            )
        assert result.passed is False
        assert "invalid Bearer token" in result.reason

    @pytest.mark.asyncio
    async def test_sends_invalid_bearer_token(self):
        evaluator = AuthRejectsInvalidTokenEvaluator()
        mock_client = _mock_http_client(401)
        with patch("testmcpy.evals.auth_evaluators.httpx.AsyncClient", return_value=mock_client):
            await evaluator.aevaluate({"metadata": {"mcp_url": "https://mcp.example.com/mcp"}})
        headers = mock_client.post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer invalid-garbage-token-12345"

    @pytest.mark.asyncio
    async def test_custom_token(self):
        evaluator = AuthRejectsInvalidTokenEvaluator(token="bogus-xyz")
        mock_client = _mock_http_client(403)
        with patch("testmcpy.evals.auth_evaluators.httpx.AsyncClient", return_value=mock_client):
            result = await evaluator.aevaluate(
                {"metadata": {"mcp_url": "https://mcp.example.com/mcp"}}
            )
        headers = mock_client.post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer bogus-xyz"
        assert result.passed is True

    def test_resolvable_via_create_evaluator(self):
        evaluator = create_evaluator("auth_rejects_invalid_token", token="abc")
        assert isinstance(evaluator, AuthRejectsInvalidTokenEvaluator)
        assert evaluator.name == "auth_rejects_invalid_token"


# ===========================================================================
# AuthTokenNotEchoedEvaluator
# ===========================================================================


class TestAuthTokenNotEchoed:
    TOKEN = "sekrit-token-abcdef123456"

    def test_passes_when_token_not_echoed(self):
        evaluator = AuthTokenNotEchoedEvaluator()
        result = evaluator.evaluate(
            {
                "response": "Here are your dashboards.",
                "tool_results": [MockToolResult(tool_call_id="1", content="dashboard list")],
                "metadata": {"auth_token": self.TOKEN},
            }
        )
        assert result.passed is True
        assert result.score == 1.0

    def test_fails_when_token_in_final_answer(self):
        evaluator = AuthTokenNotEchoedEvaluator()
        result = evaluator.evaluate(
            {
                "response": f"Your token is {self.TOKEN}",
                "tool_results": [],
                "metadata": {"auth_token": self.TOKEN},
            }
        )
        assert result.passed is False
        assert "auth token found in final answer" in result.reason

    def test_fails_when_token_in_tool_results(self):
        evaluator = AuthTokenNotEchoedEvaluator()
        result = evaluator.evaluate(
            {
                "response": "Done.",
                "tool_results": [MockToolResult(tool_call_id="1", content=f"debug: {self.TOKEN}")],
                "metadata": {"auth_token": self.TOKEN},
            }
        )
        assert result.passed is False
        assert "auth token found in tool result #0" in result.reason

    def test_handles_dict_tool_results(self):
        evaluator = AuthTokenNotEchoedEvaluator()
        result = evaluator.evaluate(
            {
                "response": "Done.",
                "tool_results": [{"content": [{"type": "text", "text": self.TOKEN}]}],
                "metadata": {"auth_token": self.TOKEN},
            }
        )
        assert result.passed is False

    def test_no_token_passes_with_warning(self):
        evaluator = AuthTokenNotEchoedEvaluator()
        result = evaluator.evaluate({"response": "Hello", "metadata": {}})
        assert result.passed is True
        assert result.score == 0.5
        assert "nothing to check" in result.reason

    def test_short_token_skipped(self):
        evaluator = AuthTokenNotEchoedEvaluator(min_token_length=8)
        result = evaluator.evaluate(
            {
                "response": "abc was here",
                "metadata": {"auth_token": "abc"},
            }
        )
        assert result.passed is True
        assert result.score == 0.5

    def test_custom_token_field(self):
        evaluator = AuthTokenNotEchoedEvaluator(token_field="refresh_token")
        result = evaluator.evaluate(
            {
                "response": f"leak: {self.TOKEN}",
                "metadata": {"refresh_token": self.TOKEN},
            }
        )
        assert result.passed is False

    def test_resolvable_via_create_evaluator(self):
        evaluator = create_evaluator("auth_token_not_echoed", min_token_length=4)
        assert isinstance(evaluator, AuthTokenNotEchoedEvaluator)
        assert evaluator.name == "auth_token_not_echoed"


# ===========================================================================
# Pack registration
# ===========================================================================


class TestSecurityPacks:
    def test_security_pack_members(self):
        evals = resolve_evaluator_pack("security")
        names = [e["name"] for e in evals]
        assert names == ["no_injection_echo", "no_leaked_data", "response_not_includes"]

    def test_auth_security_pack_members(self):
        evals = resolve_evaluator_pack("auth-security")
        names = [e["name"] for e in evals]
        assert names == [
            "auth_rejects_missing_token",
            "auth_rejects_invalid_token",
            "auth_token_not_echoed",
        ]

    @pytest.mark.parametrize("pack_name", ["security", "auth-security"])
    def test_pack_members_instantiate(self, pack_name):
        """Every evaluator in the pack must be creatable with its declared args."""
        for config in resolve_evaluator_pack(pack_name):
            evaluator = create_evaluator(config["name"], **config.get("args", {}))
            assert evaluator is not None

    def test_resolve_evaluators_expands_pack_from_yaml_style_spec(self):
        spec = yaml.safe_load(
            """
            evaluators:
              - pack: security
              - name: execution_successful
            """
        )
        resolved = resolve_evaluators(spec["evaluators"])
        names = [e["name"] for e in resolved]
        assert "no_injection_echo" in names
        assert "execution_successful" in names

    def test_security_pack_passes_on_clean_context(self):
        context = {
            "response": "All charts are listed.",
            "tool_calls": [{"name": "list_charts", "arguments": {}}],
            "tool_results": [],
            "metadata": {},
        }
        for config in resolve_evaluator_pack("security"):
            evaluator = create_evaluator(config["name"], **config.get("args", {}))
            result = evaluator.evaluate(context)
            assert result.passed is True, f"{config['name']} failed: {result.reason}"


# ===========================================================================
# Example suite loads
# ===========================================================================


class TestExampleSuiteLoads:
    SUITE_PATH = (
        Path(__file__).resolve().parent.parent / "examples" / "security" / "injection_tests.yaml"
    )

    def test_suite_parses_into_test_cases(self):
        from testmcpy.src.test_runner import TestCase

        with open(self.SUITE_PATH) as f:
            data = yaml.safe_load(f)

        assert data["tests"], "Example suite has no tests"
        test_cases = [TestCase.from_dict(t) for t in data["tests"]]
        names = [tc.name for tc in test_cases]
        assert "injection_canary_not_echoed" in names
        assert "auth_endpoint_rejects_unauthenticated_probe" in names

        auth_probe = next(
            tc for tc in test_cases if tc.name == "auth_endpoint_rejects_unauthenticated_probe"
        )
        assert auth_probe.is_auth_only is True
        eval_names = [e["name"] for e in auth_probe.evaluators]
        assert "auth_rejects_missing_token" in eval_names
        assert "auth_rejects_invalid_token" in eval_names

    def test_canary_test_plants_canary_in_prompt(self):
        from testmcpy.src.test_runner import TestCase

        with open(self.SUITE_PATH) as f:
            data = yaml.safe_load(f)
        canary_test = TestCase.from_dict(
            next(t for t in data["tests"] if t["name"] == "injection_canary_not_echoed")
        )
        assert CANARY in canary_test.prompt
        eval_config = canary_test.evaluators[0]
        assert eval_config["name"] == "no_injection_echo"
        assert eval_config["args"]["canary"] == CANARY

    def test_pack_references_in_suite_resolve(self):
        from testmcpy.src.test_runner import TestCase

        with open(self.SUITE_PATH) as f:
            data = yaml.safe_load(f)
        pack_test = TestCase.from_dict(
            next(t for t in data["tests"] if t["name"] == "auth_security_pack")
        )
        # Pack must be expanded into concrete evaluator configs at parse time
        names = [e["name"] for e in pack_test.evaluators]
        assert "auth_token_not_echoed" in names
