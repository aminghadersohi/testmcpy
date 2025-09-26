"""
MCP Testing & Validation Framework

A comprehensive testing framework for validating LLM tool calling
capabilities with MCP (Model Context Protocol) services.
"""

__version__ = "0.1.0"

from src.mcp_client import MCPClient, MCPTool, MCPToolCall, MCPToolResult
from src.llm_integration import LLMProvider, create_llm_provider
from src.test_runner import TestRunner, TestCase, TestResult
from evals.base_evaluators import (
    BaseEvaluator,
    EvalResult,
    WasMCPToolCalled,
    ExecutionSuccessful,
    FinalAnswerContains,
    create_evaluator,
)

__all__ = [
    "MCPClient",
    "MCPTool",
    "MCPToolCall",
    "MCPToolResult",
    "LLMProvider",
    "create_llm_provider",
    "TestRunner",
    "TestCase",
    "TestResult",
    "BaseEvaluator",
    "EvalResult",
    "WasMCPToolCalled",
    "ExecutionSuccessful",
    "FinalAnswerContains",
    "create_evaluator",
]