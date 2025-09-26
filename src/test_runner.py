"""
Test runner for executing MCP test cases with LLMs.
"""

import asyncio
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict, field
import json

from src.mcp_client import MCPClient, MCPToolCall, MCPToolResult
from src.llm_integration import LLMProvider, create_llm_provider
from evals.base_evaluators import BaseEvaluator, EvalResult, create_evaluator


@dataclass
class TestCase:
    """Represents a single test case."""
    name: str
    prompt: str
    evaluators: List[Dict[str, Any]]
    metadata: Dict[str, Any] = field(default_factory=dict)
    expected_tools: Optional[List[str]] = None
    timeout: float = 30.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TestCase":
        """Create TestCase from dictionary."""
        return cls(
            name=data["name"],
            prompt=data["prompt"],
            evaluators=data.get("evaluators", []),
            metadata=data.get("metadata", {}),
            expected_tools=data.get("expected_tools"),
            timeout=data.get("timeout", 30.0)
        )


@dataclass
class TestResult:
    """Result from running a test case."""
    test_name: str
    passed: bool
    score: float
    duration: float
    reason: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    response: Optional[str] = None
    evaluations: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class TestRunner:
    """Runs test cases against MCP service with LLM."""

    def __init__(
        self,
        model: str,
        provider: str = "ollama",
        mcp_url: str = "http://localhost:5008/mcp/",
        verbose: bool = False
    ):
        self.model = model
        self.provider = provider
        self.mcp_url = mcp_url
        self.verbose = verbose
        self.llm_provider: Optional[LLMProvider] = None
        self.mcp_client: Optional[MCPClient] = None

    async def initialize(self):
        """Initialize LLM provider and MCP client."""
        if not self.llm_provider:
            self.llm_provider = create_llm_provider(
                provider=self.provider,
                model=self.model
            )
            await self.llm_provider.initialize()

        if not self.mcp_client:
            self.mcp_client = MCPClient(self.mcp_url)
            await self.mcp_client.initialize()

    async def run_test(self, test_case: TestCase) -> TestResult:
        """Run a single test case."""
        start_time = time.time()

        try:
            # Ensure initialized
            await self.initialize()

            # Get available MCP tools
            mcp_tools = await self.mcp_client.list_tools()

            # Format tools for LLM
            formatted_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema
                    }
                }
                for tool in mcp_tools
            ]

            if self.verbose:
                print(f"Running test: {test_case.name}")
                print(f"Prompt: {test_case.prompt}")
                print(f"Available tools: {len(formatted_tools)}")

            # Get LLM response with tool calls
            llm_result = await self.llm_provider.generate_with_tools(
                prompt=test_case.prompt,
                tools=formatted_tools,
                timeout=test_case.timeout
            )

            # Execute tool calls if any
            tool_results = []
            if llm_result.tool_calls:
                for tool_call in llm_result.tool_calls:
                    mcp_tool_call = MCPToolCall(
                        name=tool_call["name"],
                        arguments=tool_call.get("arguments", {})
                    )
                    result = await self.mcp_client.call_tool(mcp_tool_call)
                    tool_results.append({
                        "tool_call_id": result.tool_call_id,
                        "content": result.content,
                        "is_error": result.is_error,
                        "error_message": result.error_message
                    })

            # Prepare context for evaluators
            context = {
                "prompt": test_case.prompt,
                "response": llm_result.response,
                "tool_calls": llm_result.tool_calls,
                "tool_results": tool_results,
                "metadata": {
                    "duration_seconds": time.time() - start_time,
                    "model": self.model,
                    "total_tokens": llm_result.token_usage.get("total", 0) if llm_result.token_usage else 0,
                    "cost": llm_result.cost
                }
            }

            # Run evaluators
            evaluations = []
            all_passed = True
            total_score = 0.0

            for eval_config in test_case.evaluators:
                evaluator = self._create_evaluator(eval_config)
                eval_result = evaluator.evaluate(context)

                evaluations.append({
                    "evaluator": evaluator.name,
                    "passed": eval_result.passed,
                    "score": eval_result.score,
                    "reason": eval_result.reason,
                    "details": eval_result.details
                })

                if not eval_result.passed:
                    all_passed = False
                total_score += eval_result.score

            avg_score = total_score / len(test_case.evaluators) if test_case.evaluators else 0.0

            return TestResult(
                test_name=test_case.name,
                passed=all_passed,
                score=avg_score,
                duration=time.time() - start_time,
                reason="All evaluators passed" if all_passed else "Some evaluators failed",
                tool_calls=llm_result.tool_calls,
                tool_results=tool_results,
                response=llm_result.response,
                evaluations=evaluations
            )

        except Exception as e:
            return TestResult(
                test_name=test_case.name,
                passed=False,
                score=0.0,
                duration=time.time() - start_time,
                reason=f"Test failed with error: {str(e)}",
                error=str(e)
            )

    async def run_tests(self, test_cases: List[TestCase]) -> List[TestResult]:
        """Run multiple test cases."""
        results = []

        try:
            await self.initialize()

            for test_case in test_cases:
                result = await self.run_test(test_case)
                results.append(result)

                if self.verbose:
                    print(f"Test {test_case.name}: {'PASS' if result.passed else 'FAIL'} (score: {result.score:.2f})")

        finally:
            await self.cleanup()

        return results

    def _create_evaluator(self, eval_config: Dict[str, Any]) -> BaseEvaluator:
        """Create evaluator from configuration."""
        if isinstance(eval_config, str):
            # Simple evaluator name
            return create_evaluator(eval_config)

        # Evaluator with configuration
        name = eval_config.get("name")
        args = eval_config.get("args", {})
        return create_evaluator(name, **args)

    async def cleanup(self):
        """Clean up resources."""
        if self.llm_provider:
            await self.llm_provider.close()
        if self.mcp_client:
            await self.mcp_client.close()


# Batch test runner for running multiple test suites

class BatchTestRunner:
    """Run multiple test suites with different models."""

    def __init__(self, mcp_url: str = "http://localhost:5008/mcp/"):
        self.mcp_url = mcp_url
        self.results: Dict[str, List[TestResult]] = {}

    async def run_suite_with_models(
        self,
        test_cases: List[TestCase],
        models: List[Dict[str, str]]
    ) -> Dict[str, List[TestResult]]:
        """
        Run test suite with multiple models.

        Args:
            test_cases: List of test cases to run
            models: List of dicts with 'provider' and 'model' keys

        Returns:
            Dictionary mapping model names to test results
        """
        for model_config in models:
            provider = model_config["provider"]
            model = model_config["model"]
            model_key = f"{provider}:{model}"

            print(f"\nRunning tests with {model_key}")

            runner = TestRunner(
                model=model,
                provider=provider,
                mcp_url=self.mcp_url
            )

            results = await runner.run_tests(test_cases)
            self.results[model_key] = results

        return self.results

    def generate_comparison_report(self) -> Dict[str, Any]:
        """Generate comparison report across all models."""
        report = {
            "models": list(self.results.keys()),
            "test_count": len(next(iter(self.results.values()))) if self.results else 0,
            "model_summaries": {},
            "test_comparisons": {}
        }

        # Generate per-model summaries
        for model, results in self.results.items():
            passed = sum(1 for r in results if r.passed)
            total = len(results)
            avg_score = sum(r.score for r in results) / total if total > 0 else 0
            avg_duration = sum(r.duration for r in results) / total if total > 0 else 0

            report["model_summaries"][model] = {
                "passed": passed,
                "failed": total - passed,
                "total": total,
                "success_rate": passed / total if total > 0 else 0,
                "avg_score": avg_score,
                "avg_duration": avg_duration
            }

        # Generate per-test comparisons
        if self.results:
            first_results = next(iter(self.results.values()))
            for i, test_result in enumerate(first_results):
                test_name = test_result.test_name
                report["test_comparisons"][test_name] = {}

                for model, results in self.results.items():
                    if i < len(results):
                        result = results[i]
                        report["test_comparisons"][test_name][model] = {
                            "passed": result.passed,
                            "score": result.score,
                            "duration": result.duration
                        }

        return report