"""Prompt Playground LLM-profile selection regressions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from testmcpy.llm_profiles import reload_llm_profile_config
from testmcpy.server.routers.tests import SingleTestRunRequest, run_single_test


@pytest.mark.asyncio
async def test_explicit_provider_uses_matching_entry_not_profile_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".llm_providers.yaml").write_text(
        """
default: mixed
profiles:
  mixed:
    name: Mixed
    providers:
      - name: OpenAI
        provider: openai
        model: gpt-test
        api_key: openai-secret
        default: true
      - name: Claude SDK
        provider: claude-sdk
        model: claude-test
        api_key: claude-secret
"""
    )
    reload_llm_profile_config()
    result = SimpleNamespace(passed=True, to_dict=lambda: {"passed": True})

    with patch("testmcpy.server.routers.tests.TestRunner") as runner_class:
        runner_class.return_value.run_tests = AsyncMock(return_value=[result])
        response = await run_single_test(
            SingleTestRunRequest(
                prompt="hello",
                provider="claude-sdk",
                model="claude-test",
                llm_profile="mixed",
            )
        )

    assert response["passed"] is True
    kwargs = runner_class.call_args.kwargs
    assert kwargs["provider"] == "claude-sdk"
    assert kwargs["model"] == "claude-test"
    assert kwargs["provider_config"]["api_key"] == "claude-secret"
    assert kwargs["provider_config"]["api_key"] != "openai-secret"
    assert kwargs["llm_profile"] == "mixed"
