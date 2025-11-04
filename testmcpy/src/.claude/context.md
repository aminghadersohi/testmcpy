# testmcpy/src/ - Core Business Logic

## Purpose
The `src/` directory contains the core business logic for testmcpy, a testing framework for evaluating LLM tool-calling capabilities against MCP (Model Context Protocol) services.

## Key Modules

### test_runner.py - Test Execution Engine
**Purpose:** Orchestrates test execution, manages rate limiting, and coordinates between LLMs, MCP clients, and evaluators.

**Key Components:**
- `TestRunner`: Main test execution class that runs test cases against MCP services
- `RateLimitTracker`: Tracks token usage and manages rate limiting for API providers
- `TestCase`: Represents a single test with prompt, evaluators, and metadata
- `TestResult`: Contains test execution results, scores, tool calls, and performance metrics
- `BatchTestRunner`: Runs multiple test suites across different models for comparison

**Important Patterns:**
- Rate limiting uses conservative token estimation (46K cache tokens for Anthropic)
- Automatic retry logic for rate limit failures (3 attempts with progressive backoff)
- Duration tracking excludes wait times for accurate performance measurement
- Tool calls are displayed before execution for transparency

### llm_integration.py - LLM Provider Abstractions
**Purpose:** Provides unified interface for multiple LLM providers with strict MCP URL security.

**Supported Providers:**
1. **OllamaProvider**: Local models via Ollama API
2. **OpenAIProvider**: OpenAI and OpenAI-compatible APIs
3. **AnthropicProvider**: Anthropic Claude API with prompt caching
4. **ClaudeSDKProvider**: Claude Agent SDK with native MCP integration
5. **ClaudeCodeProvider**: Claude Code CLI via subprocess
6. **LocalModelProvider**: Hugging Face transformers (experimental)

**Key Components:**
- `LLMProvider`: Abstract base class defining the provider interface
- `LLMResult`: Standardized result format (response, tool_calls, token_usage, cost)
- `ToolDiscoveryService`: Discovers MCP tools locally and creates sanitized schemas
- `MCPURLFilter`: Security class preventing MCP URLs from reaching external APIs

**Important Patterns:**
- All providers implement `initialize()`, `generate_with_tools()`, and `close()`
- Tool schemas are sanitized to remove internal URLs before sending to external APIs
- Anthropic provider uses prompt caching (ephemeral cache_control on system messages)
- Token usage includes both charged and cached tokens for rate limiting
- Factory function `create_llm_provider()` simplifies provider instantiation

**Security:**
- MCP URLs are never sent to external APIs
- `MCPURLFilter.validate_request_data()` blocks requests containing local endpoints
- Tool execution happens locally via `ToolDiscoveryService`

### mcp_client.py - MCP Protocol Client
**Purpose:** Client implementation for interacting with MCP services using FastMCP.

**Key Components:**
- `MCPClient`: Main client for MCP service interaction
- `MCPTool`: Represents an MCP tool definition with name, description, and input schema
- `MCPToolCall`: Represents a tool call to be executed
- `MCPToolResult`: Result from executing an MCP tool
- `BearerAuth`: Bearer token authentication for httpx

**Authentication Methods:**
1. **Bearer**: Direct bearer token (`MCP_AUTH_TOKEN`)
2. **JWT**: Dynamic JWT fetched from API endpoint (requires `MCP_AUTH_API_URL`, `MCP_AUTH_API_TOKEN`, `MCP_AUTH_API_SECRET`)
3. **OAuth**: Client credentials flow (requires `client_id`, `client_secret`, `token_url`)
4. **None**: No authentication

**Important Patterns:**
- Async context manager support (`async with MCPClient(url) as client`)
- Tools are cached after first `list_tools()` call (use `force_refresh=True` to refresh)
- All operations are async and use FastMCP client under the hood
- Authentication is set up during `initialize()` based on config or explicit auth dict

**Usage Example:**
```python
async with MCPClient("http://localhost:5008/mcp/") as client:
    tools = await client.list_tools()
    result = await client.call_tool(MCPToolCall(name="tool_name", arguments={...}))
```

### evaluators.py - Test Evaluation Logic
**Location:** `../evals/base_evaluators.py`

**Purpose:** Provides evaluators to validate LLM responses and tool calling behavior.

**Base Classes:**
- `BaseEvaluator`: Abstract base for all evaluators
- `EvalResult`: Result with passed/failed status, score (0.0-1.0), reason, and details

**Categories:**

1. **Basic Evaluators:**
   - `WasMCPToolCalled`: Check if specific or any tool was called
   - `ExecutionSuccessful`: Verify tool execution completed without errors
   - `FinalAnswerContains`: Check response contains expected content
   - `AnswerContainsLink`: Verify response includes expected URLs
   - `WithinTimeLimit`: Check execution completed within time limit
   - `TokenUsageReasonable`: Validate token usage and cost

2. **Parameter Validation:**
   - `ToolCalledWithParameter`: Check tool called with specific parameter
   - `ToolCalledWithParameters`: Validate multiple parameters (exact or partial match)
   - `ParameterValueInRange`: Check numeric parameter is within range
   - `ToolCallCount`: Verify number of tool calls (exact, min, max)
   - `ToolCallSequence`: Validate tools called in specific order

3. **Domain-Specific:**
   - `WasSupersetChartCreated`: Superset-specific chart creation check
   - `SQLQueryValid`: Basic SQL syntax validation

**Important Patterns:**
- All evaluators return `EvalResult` with `passed`, `score`, `reason`, `details`
- Factory function `create_evaluator(name, **kwargs)` creates evaluators by name
- Evaluators receive context dict with prompt, response, tool_calls, tool_results, metadata

## Architecture Patterns

### How LLM Providers Work
1. Provider is created via `create_llm_provider(provider, model, **kwargs)`
2. `initialize()` sets up client, checks credentials, pre-discovers MCP tools
3. `generate_with_tools(prompt, tools, timeout)` sends prompt with tool schemas
4. Provider returns `LLMResult` with response, tool_calls, token_usage, cost
5. Test runner executes tool calls locally via MCP client
6. `close()` cleans up resources

### How to Add a New LLM Provider
1. Create class inheriting from `LLMProvider`
2. Implement required methods: `initialize()`, `generate_with_tools()`, `close()`
3. Parse provider-specific tool call format into standardized dict format
4. Calculate token usage and cost (if applicable)
5. Add provider to `create_llm_provider()` factory function
6. Handle provider-specific errors and timeouts

### How Evaluators Validate Test Results
1. Test runner executes test case and collects results
2. For each evaluator in test case configuration:
   - Create evaluator instance (via factory or direct instantiation)
   - Pass context dict to `evaluate()` method
   - Receive `EvalResult` with pass/fail, score, and reason
3. Aggregate scores: average score across all evaluators
4. Test passes only if all evaluators pass

### How MCP Client Connects and Executes Tools
1. Client initializes with MCP service URL
2. Authentication is set up based on config or provided auth dict
3. FastMCP client connects to MCP service (HTTP or WebSocket)
4. `list_tools()` discovers available tools and caches them
5. `call_tool()` executes tool with arguments and returns result
6. Tool results include content and error status

## Common Tasks

### Adding a New Test
1. Create YAML test file in `tests/` directory
2. Define test case with `name`, `prompt`, `evaluators`
3. Run with: `testmcpy run tests/your_test.yaml --model MODEL --provider PROVIDER`

### Adding a New Evaluator
1. Create class inheriting from `BaseEvaluator` in `evals/base_evaluators.py`
2. Implement `evaluate(context)` returning `EvalResult`
3. Implement `name` and `description` properties
4. Add to `create_evaluator()` factory function
5. Use in test YAML: `evaluators: [{name: "your_evaluator", args: {...}}]`

### Debugging Test Failures
1. Run with `--verbose` flag to see detailed execution logs
2. Check evaluator reasons in test results
3. Examine tool_calls and tool_results in test output
4. Review token usage and rate limiting messages
5. Use `--hide-tool-output` to reduce noise if needed

### Testing Against a New MCP Service
1. Set `MCP_URL` environment variable or pass `--mcp-url` flag
2. Configure authentication if needed (bearer, JWT, or OAuth)
3. Run discovery: `testmcpy discover --url YOUR_URL`
4. Create tests targeting discovered tools

### Performance Optimization
- Anthropic provider uses prompt caching (tools cached in system message)
- Rate limiter prevents 429 errors with conservative token estimation
- Tool schemas cached after first discovery (use `force_refresh=True` to refresh)
- Batch runner adds 15s delay between tests to prevent rate limiting

## Configuration
Configuration is managed by `testmcpy/config.py` which loads from:
1. Environment variables
2. `.env` file in project root
3. `~/.testmcpy` config file

Key config values:
- `MCP_URL`: MCP service endpoint (default: http://localhost:5008/mcp/)
- `ANTHROPIC_API_KEY`: Anthropic API key
- `OPENAI_API_KEY`: OpenAI API key
- `MCP_AUTH_TOKEN`: Static bearer token for MCP authentication
- `MCP_AUTH_API_URL`, `MCP_AUTH_API_TOKEN`, `MCP_AUTH_API_SECRET`: Dynamic JWT auth
