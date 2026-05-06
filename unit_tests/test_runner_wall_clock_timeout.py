"""
Unit tests for the wall-clock timeout in TestRunner._run_test_with_retry.

The wall-clock timeout is a hard cap on each test's total duration —
provider-side stuck SSE streams or infinite retry loops can keep a single
LLM call alive far longer than the per-call timeout if the call keeps
emitting partial events. The wall-clock timeout breaks out of that.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from testmcpy.src.test_runner import TestCase, TestResult, TestRunner


class _FakeProvider:
    """Stand-in for an LLM provider that just hangs."""

    async def initialize(self):
        pass

    async def close(self):
        pass


def _make_runner(provider_name: str = "anthropic") -> TestRunner:
    runner = TestRunner(model="test-model", provider=provider_name)
    runner.llm_provider = _FakeProvider()  # type: ignore[assignment]
    runner.mcp_client = None
    # Shrink the slack so the unit test runs in well under a second
    # rather than waiting the production 60s margin.
    runner.WALL_CLOCK_SLACK_SECONDS = 0.2
    return runner


def _make_test_case(timeout: float = 0.1) -> TestCase:
    return TestCase(
        name="hang_test",
        prompt="hang please",
        evaluators=[],
        timeout=timeout,
    )


@pytest.mark.asyncio
async def test_wall_clock_timeout_aborts_hung_test():
    """If run_test never returns, _run_test_with_retry must NOT hang;
    it must construct a failed TestResult with a clear wall-clock-timeout
    error.
    """
    runner = _make_runner()
    test_case = _make_test_case(timeout=0.1)

    async def _hang_forever(_test_case):
        await asyncio.sleep(3600)
        return TestResult(test_name=_test_case.name, passed=True, score=1.0, duration=0.0)

    runner.run_test = AsyncMock(side_effect=_hang_forever)

    # Wall-clock budget here is 0.1 + 0.2 = 0.3s. Give a 5s outer cap
    # to make the test failure mode actionable if the wall-clock guard
    # were broken.
    result = await asyncio.wait_for(
        runner._run_test_with_retry(test_case, max_test_retries=0),
        timeout=5.0,
    )

    assert result.passed is False
    assert result.score == 0.0
    assert result.reason == "wall-clock timeout"
    assert result.error == "wall-clock timeout"
    assert "wall-clock timeout" in (result.response or "").lower()


@pytest.mark.asyncio
async def test_wall_clock_timeout_does_not_fire_when_test_completes_quickly():
    """A test that returns quickly should pass through unaffected — the
    wall-clock guard is invisible on the happy path.
    """
    runner = _make_runner()
    test_case = _make_test_case(timeout=1.0)

    expected = TestResult(
        test_name=test_case.name, passed=True, score=1.0, duration=0.05, response="ok"
    )

    async def _quick(_test_case):
        await asyncio.sleep(0.01)
        return expected

    runner.run_test = AsyncMock(side_effect=_quick)

    result = await runner._run_test_with_retry(test_case, max_test_retries=0)

    assert result is expected
    assert result.passed is True


@pytest.mark.asyncio
async def test_cli_provider_gets_120s_floor_on_wall_clock_budget():
    """For CLI providers (claude-sdk, claude-cli, codex-cli) the per-call
    timeout is floored at 120s before adding the slack. This protects
    long-running CLI invocations from being killed prematurely.
    """
    runner = _make_runner(provider_name="claude-sdk")
    runner.WALL_CLOCK_SLACK_SECONDS = 0.05
    test_case = _make_test_case(timeout=0.1)

    # The wall-clock budget for a CLI provider here is max(0.1, 120) +
    # 0.05 = 120.05s. We expect the test to NOT time out within 0.5s.
    async def _quick(_test_case):
        await asyncio.sleep(0.01)
        return TestResult(test_name=_test_case.name, passed=True, score=1.0, duration=0.01)

    runner.run_test = AsyncMock(side_effect=_quick)

    # If the budget were wrongly computed as ~0.15s, the test below
    # would fail with a wall-clock timeout despite returning in 0.01s.
    result = await asyncio.wait_for(
        runner._run_test_with_retry(test_case, max_test_retries=0),
        timeout=2.0,
    )

    assert result.passed is True
