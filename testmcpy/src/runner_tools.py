"""
Runner Tool Abstraction for MCP test execution.

Defines a pluggable interface for different test execution backends:
- MCPRunner: Uses testmcpy's built-in MCP client + LLM
- AnthropicAPIRunner: Direct Anthropic API with tool use
- OpenAIAPIRunner: Direct OpenAI API with function calling
- ClaudeCodeRunner: Uses Claude Code CLI (future)
- ClaudeAgentSDKRunner: Uses Claude Agent SDK (future)
"""

import asyncio
import contextlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..llm_profiles import resolve_llm_provider_selection
from .llm_integration import LLMProvider, create_llm_provider
from .mcp_client import MCPClient, MCPToolCall


@dataclass
class ToolDefinition:
    """A tool available for the LLM to call."""

    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic_format(self) -> dict[str, Any]:
        """Convert to Anthropic tool use format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


@dataclass
class ToolCall:
    """A tool call made by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """Result from executing a tool."""

    tool_call_id: str
    content: Any
    is_error: bool = False


@dataclass
class RunnerResult:
    """Result from executing a prompt with a runner tool."""

    response: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    tokens_input: int = 0
    tokens_output: int = 0
    tti_ms: int | None = None  # Time to first token
    duration_ms: int = 0
    cost: float = 0.0
    error: str | None = None
    raw_response: Any = None  # Provider-specific raw response

    def to_dict(self) -> dict[str, Any]:
        return {
            "response": self.response,
            "tool_calls": [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in self.tool_calls
            ],
            "tool_results": [
                {"tool_call_id": tr.tool_call_id, "content": tr.content, "is_error": tr.is_error}
                for tr in self.tool_results
            ],
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "tti_ms": self.tti_ms,
            "duration_ms": self.duration_ms,
            "cost": self.cost,
            "error": self.error,
        }


@runtime_checkable
class RunnerTool(Protocol):
    """Protocol for test runner tool implementations.

    A runner tool handles the execution of prompts against an LLM,
    including tool calling and response handling.
    """

    @property
    def name(self) -> str:
        """Unique identifier for this runner tool."""
        ...

    async def initialize(self) -> None:
        """Initialize the runner (connect to services, etc.)."""
        ...

    async def execute(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        timeout: float = 30.0,
        messages: list[dict] | None = None,
    ) -> RunnerResult:
        """
        Execute a prompt and return the result.

        Args:
            prompt: The prompt to send to the LLM
            tools: Available tools for the LLM to call
            timeout: Maximum time to wait for response
            messages: Optional conversation history

        Returns:
            RunnerResult with response, tool calls, and metrics
        """
        ...

    async def execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """
        Execute a tool call and return the result.

        Args:
            tool_call: The tool call to execute

        Returns:
            ToolResult with the execution output
        """
        ...

    async def close(self) -> None:
        """Clean up resources."""
        ...


class BaseRunnerTool(ABC):
    """Base class for runner tool implementations."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this runner tool."""
        pass

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the runner."""
        pass

    @abstractmethod
    async def execute(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        timeout: float = 30.0,
        messages: list[dict] | None = None,
    ) -> RunnerResult:
        """Execute a prompt."""
        pass

    @abstractmethod
    async def execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources."""
        pass


class MCPRunner(BaseRunnerTool):
    """
    Runner using testmcpy's built-in MCP client and LLM provider.

    This is the default runner that uses:
    - MCPClient for tool execution
    - LLMProvider for LLM calls (Anthropic, OpenAI, Gemini)
    """

    def __init__(
        self,
        mcp_url: str | None = None,
        mcp_client: MCPClient | None = None,
        model: str | None = None,
        provider: str | None = None,
        llm_profile: str | None = None,
    ):
        self._name = "mcp-client"
        self.mcp_url = mcp_url
        self.mcp_client = mcp_client
        self._owns_mcp_client = mcp_client is None
        self._model_override = model
        self._provider_override = provider
        # Preserve the historical pre-initialize attributes while allowing an
        # omitted provider/model to be supplied by the selected LLM profile.
        self.model = model or "claude-sonnet-4-6"
        self.provider_name = provider or "anthropic"
        self.llm_profile = llm_profile
        self.llm_provider: LLMProvider | None = None
        self._initialized = False

    @property
    def name(self) -> str:
        return self._name

    async def initialize(self) -> None:
        """Initialize MCP client and LLM provider."""
        if self._initialized:
            return

        # Resolve the profile before opening an MCP connection so an invalid
        # explicit profile fails without allocating external resources.
        provider, model, provider_config = resolve_llm_provider_selection(
            self._provider_override,
            self._model_override,
            self.llm_profile,
            fallback_provider="anthropic",
            fallback_model="claude-sonnet-4-6",
        )
        if not provider or not model:
            raise ValueError("Model and provider must be configured")
        self.provider_name = provider
        self.model = model

        try:
            if self.mcp_client is None and self.mcp_url:
                self.mcp_client = MCPClient(self.mcp_url)
                await self.mcp_client.initialize()

            provider_kwargs = dict(provider_config)
            provider_mcp_url = self.mcp_url or getattr(self.mcp_client, "base_url", None)
            if provider_mcp_url:
                provider_kwargs.setdefault("mcp_url", provider_mcp_url)
            provider_auth = getattr(self.mcp_client, "auth_config", None)
            if provider_auth:
                provider_kwargs.setdefault("auth", provider_auth)
            self.llm_provider = create_llm_provider(provider, model, **provider_kwargs)
            await self.llm_provider.initialize()
        except BaseException:
            await self._close_resources()
            raise

        self._initialized = True

    async def get_available_tools(self) -> list[ToolDefinition]:
        """Get tools from the MCP server."""
        if not self.mcp_client:
            return []

        mcp_tools = await self.mcp_client.list_tools()
        return [
            ToolDefinition(
                name=tool.name,
                description=tool.description or "",
                parameters=tool.input_schema or {},
            )
            for tool in mcp_tools
        ]

    async def execute(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        timeout: float = 30.0,
        messages: list[dict] | None = None,
    ) -> RunnerResult:
        """Execute prompt using LLM provider with MCP tools."""
        if not self._initialized:
            await self.initialize()

        if not self.llm_provider:
            return RunnerResult(error="LLM provider not initialized")

        start_time = time.time()
        tti_start = time.time()
        tti_ms = None

        try:
            # Format tools for LLM
            formatted_tools = [t.to_openai_format() for t in tools]

            # Call LLM
            result = await asyncio.wait_for(
                self.llm_provider.generate_with_tools(
                    prompt=prompt,
                    tools=formatted_tools,
                    timeout=timeout,
                    messages=messages,
                ),
                timeout=timeout,
            )

            # Record TTI (approximate - when we get the response)
            tti_ms = int((time.time() - tti_start) * 1000)

            # Parse tool calls from result
            tool_calls = []
            for i, tc in enumerate(result.tool_calls or []):
                tool_calls.append(
                    ToolCall(
                        id=tc.get("id", f"call_{i}"),
                        name=tc["name"],
                        arguments=tc.get("arguments", {}),
                    )
                )

            # SDK-backed providers execute MCP calls themselves. Mirror the
            # TestRunner contract and never replay those state-changing calls.
            tool_results = []
            if result.tool_results:
                for index, native_result in enumerate(result.tool_results):
                    fallback_id = (
                        tool_calls[index].id if index < len(tool_calls) else f"call_{index}"
                    )
                    if isinstance(native_result, dict):
                        tool_results.append(
                            ToolResult(
                                tool_call_id=native_result.get("tool_call_id") or fallback_id,
                                content=native_result.get("content", native_result.get("result")),
                                is_error=bool(native_result.get("is_error", False)),
                            )
                        )
                    else:
                        tool_results.append(
                            ToolResult(
                                tool_call_id=getattr(native_result, "tool_call_id", None)
                                or fallback_id,
                                content=getattr(native_result, "content", native_result),
                                is_error=bool(getattr(native_result, "is_error", False)),
                            )
                        )
            else:
                for tc in tool_calls:
                    tool_results.append(await self.execute_tool(tc))

            duration_ms = int((time.time() - start_time) * 1000)

            return RunnerResult(
                response=result.response,
                tool_calls=tool_calls,
                tool_results=tool_results,
                tokens_input=result.token_usage.get("prompt", 0) if result.token_usage else 0,
                tokens_output=result.token_usage.get("completion", 0) if result.token_usage else 0,
                tti_ms=tti_ms,
                duration_ms=duration_ms,
                cost=result.cost,
                raw_response=result.raw_response,
            )

        except asyncio.TimeoutError:
            return RunnerResult(
                error=f"Timeout after {timeout}s",
                duration_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as e:
            return RunnerResult(
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )

    async def execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """Execute tool via MCP client."""
        if not self.mcp_client:
            return ToolResult(
                tool_call_id=tool_call.id,
                content="MCP client not available",
                is_error=True,
            )

        try:
            mcp_call = MCPToolCall(
                name=tool_call.name,
                arguments=tool_call.arguments,
            )
            result = await self.mcp_client.call_tool(mcp_call)

            # Convert result to string
            if hasattr(result, "to_dict"):
                content = result.to_dict()
            elif hasattr(result, "content"):
                content = result.content
            else:
                content = str(result)

            return ToolResult(
                tool_call_id=tool_call.id,
                content=content,
                is_error=False,
            )
        except Exception as e:
            return ToolResult(
                tool_call_id=tool_call.id,
                content=str(e),
                is_error=True,
            )

    async def close(self) -> None:
        """Clean up resources."""
        await self._close_resources()

    async def _close_resources(self) -> None:
        """Roll back owned resources without masking the triggering error."""
        llm_provider, self.llm_provider = self.llm_provider, None
        owned_mcp_client = self.mcp_client if self._owns_mcp_client else None
        if self._owns_mcp_client:
            self.mcp_client = None
        self._initialized = False
        if llm_provider:
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await llm_provider.close()
        if owned_mcp_client:
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await owned_mcp_client.close()


class AnthropicDirectRunner(BaseRunnerTool):
    """
    Runner using Anthropic API directly without MCP.

    Useful for testing LLM behavior without MCP infrastructure.
    Tools are simulated or use mock responses.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        api_key: str | None = None,
    ):
        self._name = "anthropic-direct"
        self.model = model
        self.api_key = api_key
        self.client = None
        self._initialized = False

    @property
    def name(self) -> str:
        return self._name

    async def initialize(self) -> None:
        """Initialize Anthropic client."""
        if self._initialized:
            return

        try:
            import anthropic

            if not self.api_key:
                raise RuntimeError(
                    "Anthropic API key not provided. Configure it in "
                    ".llm_providers.yaml via ${ANTHROPIC_API_KEY} substitution, "
                    "or pass api_key directly."
                )
            self.client = anthropic.AsyncAnthropic(api_key=self.api_key)
            self._initialized = True
        except ImportError:
            raise RuntimeError("anthropic package not installed")

    async def execute(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        timeout: float = 30.0,
        messages: list[dict] | None = None,
    ) -> RunnerResult:
        """Execute prompt using Anthropic API directly."""
        if not self._initialized:
            await self.initialize()

        if not self.client:
            return RunnerResult(error="Anthropic client not initialized")

        start_time = time.time()

        try:
            # Build messages
            msgs = list(messages or [])
            msgs.append({"role": "user", "content": prompt})

            # Format tools for Anthropic
            anthropic_tools = [t.to_anthropic_format() for t in tools] if tools else None

            # Call API
            response = await asyncio.wait_for(
                self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    messages=msgs,
                    tools=anthropic_tools,
                ),
                timeout=timeout,
            )

            tti_ms = int((time.time() - start_time) * 1000)

            # Parse response
            text_content = ""
            tool_calls = []

            for block in response.content:
                if block.type == "text":
                    text_content += block.text
                elif block.type == "tool_use":
                    tool_calls.append(
                        ToolCall(
                            id=block.id,
                            name=block.name,
                            arguments=block.input,
                        )
                    )

            duration_ms = int((time.time() - start_time) * 1000)

            return RunnerResult(
                response=text_content,
                tool_calls=tool_calls,
                tokens_input=response.usage.input_tokens,
                tokens_output=response.usage.output_tokens,
                tti_ms=tti_ms,
                duration_ms=duration_ms,
                raw_response=response,
            )

        except asyncio.TimeoutError:
            return RunnerResult(
                error=f"Timeout after {timeout}s",
                duration_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as e:
            return RunnerResult(
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )

    async def execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """Execute tool - returns mock for direct API runner."""
        # Direct API runner doesn't have real tool execution
        # Return a mock result or error
        return ToolResult(
            tool_call_id=tool_call.id,
            content=f"Mock result for {tool_call.name}",
            is_error=False,
        )

    async def close(self) -> None:
        """Clean up resources."""
        if self.client:
            await self.client.close()


# Registry of available runner tools
RUNNER_TOOLS: dict[str, type[BaseRunnerTool]] = {
    "mcp-client": MCPRunner,
    "anthropic-direct": AnthropicDirectRunner,
}


def create_runner_tool(
    name: str,
    **kwargs,
) -> BaseRunnerTool:
    """
    Create a runner tool by name.

    Args:
        name: Runner tool name (e.g., "mcp-client", "anthropic-direct")
        **kwargs: Arguments passed to the runner constructor

    Returns:
        Configured runner tool instance
    """
    if name not in RUNNER_TOOLS:
        available = ", ".join(RUNNER_TOOLS.keys())
        raise ValueError(f"Unknown runner tool: {name}. Available: {available}")

    return RUNNER_TOOLS[name](**kwargs)


def register_runner_tool(name: str, runner_class: type[BaseRunnerTool]) -> None:
    """Register a custom runner tool."""
    RUNNER_TOOLS[name] = runner_class
