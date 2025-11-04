# testmcpy Server Backend

## Purpose

FastAPI backend server that powers the testmcpy web UI. Provides REST API endpoints for MCP (Model Context Protocol) profile management, test execution, tool discovery, and LLM-powered chat interactions.

## Architecture Overview

- **Framework**: FastAPI with async/await patterns
- **WebSocket Support**: Real-time streaming chat via `websocket.py`
- **Main File**: `api.py` (~2,800 lines) - contains all REST endpoints
- **Global State**:
  - `config`: Global configuration from `testmcpy.config`
  - `mcp_client`: Default MCP client (backwards compatibility)
  - `mcp_clients`: Dict cache of MCP clients by `{profile_id}:{mcp_name}`

## Key API Endpoints

### Configuration & Health
- `GET /` - Serves React UI from `testmcpy/ui/dist/index.html`
- `GET /api/health` - Health check with MCP connection status
- `GET /api/config` - Returns current config with masked sensitive values
- `GET /api/models` - Lists available LLM models

### MCP Profile Management
**Profile CRUD:**
- `GET /api/mcp/profiles` - List all profiles from `.mcp_services.yaml`
- `POST /api/mcp/profiles` - Create new profile
- `PUT /api/mcp/profiles/{profile_id}` - Update profile metadata
- `DELETE /api/mcp/profiles/{profile_id}` - Delete profile
- `POST /api/mcp/profiles/{profile_id}/duplicate` - Clone profile
- `PUT /api/mcp/profiles/default/{profile_id}` - Set default profile
- `GET /api/mcp/profiles/{profile_id}/export` - Export profile as YAML
- `POST /api/mcp/profiles/create-config` - Create `.mcp_services.yaml` from example

**MCP Server Management (within profiles):**
- `POST /api/mcp/profiles/{profile_id}/mcps` - Add MCP server to profile
- `PUT /api/mcp/profiles/{profile_id}/mcps/{mcp_index}` - Update MCP server
- `DELETE /api/mcp/profiles/{profile_id}/mcps/{mcp_index}` - Remove MCP server
- `PUT /api/mcp/profiles/{profile_id}/mcps/reorder` - Reorder MCP servers
- `POST /api/mcp/profiles/{profile_id}/test-connection/{mcp_index}` - Test MCP connection

### MCP Tool Discovery
- `GET /api/mcp/tools` - List all available tools from connected MCPs
- `GET /api/mcp/resources` - List MCP resources
- `GET /api/mcp/prompts` - List MCP prompt templates

### LLM & Chat
- `POST /api/chat` - Send message to LLM with tool execution
  - Accepts `profiles` array to select which MCP servers to use
  - Format: `["profile_id:mcp_name"]` or legacy `["profile_id"]`
  - Returns tool calls with results
- WebSocket at `/ws/chat` - Streaming chat with real-time responses

### Test Management
- `GET /api/tests` - List all test files in `tests/` directory
- `GET /api/tests/{filename:path}` - Get specific test file content
- `POST /api/tests` - Create new test file
- `PUT /api/tests/{filename:path}` - Update test file
- `DELETE /api/tests/{filename:path}` - Delete test file
- `POST /api/tests/run` - Execute test file and return results
- `POST /api/tests/run-tool/{tool_name}` - Quick test of single tool
- `POST /api/tests/generate` - LLM-powered test case generation

### Evaluation & Analysis
- `POST /api/eval/run` - Run evaluators on LLM output
  - Validates tool calls against expected behavior
  - Returns pass/fail with detailed feedback
- `POST /api/format` - Format tool schema for different clients
  - Supports: `python_client`, `javascript_client`, `typescript_client`, `curl`
- `POST /api/mcp/optimize-docs` - **NEW**: LLM-powered tool documentation analysis
  - Analyzes tool descriptions and input schemas
  - Scores on: clarity, completeness, actionability, examples, constraints
  - Returns actionable suggestions for improvement

## Authentication Patterns

The server supports multiple auth types for MCP services (configured via profiles):

1. **Bearer Token**: Simple token-based auth
   ```python
   auth_dict = {"type": "bearer", "token": "..."}
   ```

2. **JWT**: API-based JWT generation
   ```python
   auth_dict = {
       "type": "jwt",
       "api_url": "https://api.example.com/auth",
       "api_token": "...",
       "api_secret": "..."
   }
   ```

3. **OAuth**: OAuth2 client credentials flow
   ```python
   auth_dict = {
       "type": "oauth",
       "client_id": "...",
       "client_secret": "...",
       "token_url": "https://oauth.example.com/token",
       "scopes": ["read", "write"]
   }
   ```

4. **None**: No authentication

Auth configs are defined in `testmcpy/mcp_profiles.py` as `AuthConfig` dataclass and converted to dict via `.to_dict()` method.

## Important Implementation Patterns

### Request/Response Models
All endpoints use Pydantic models for validation:
```python
class MyRequest(BaseModel):
    field: str
    optional_field: str | None = None

@app.post("/api/my-endpoint")
async def my_endpoint(request: MyRequest):
    # Auto-validated by Pydantic
    return {"result": request.field}
```

### Error Handling
Use FastAPI's `HTTPException` for errors:
```python
from fastapi import HTTPException

if not resource_exists:
    raise HTTPException(status_code=404, detail="Resource not found")
```

### YAML Config Manipulation
Helper functions for `.mcp_services.yaml`:
- `get_mcp_config_path()` - Finds config file in current/parent dirs
- `load_mcp_yaml()` - Loads and parses YAML
- `validate_config(config_data)` - Validates structure before saving
- `save_mcp_yaml(config_data)` - Writes validated config

### MCP Client Management
```python
# Get clients for entire profile (all MCP servers)
clients = await get_mcp_clients_for_profile(profile_id)
# Returns: list[tuple[mcp_name, MCPClient]]

# Get client for specific MCP server
client = await get_mcp_client_for_server(profile_id, mcp_name)
# Returns: MCPClient | None
```

Clients are cached in `mcp_clients` dict with key `"{profile_id}:{mcp_name}"`.

### Async/Await Everywhere
All I/O operations are async:
```python
@app.post("/api/my-endpoint")
async def my_endpoint(request: MyRequest):
    # Use await for async operations
    result = await mcp_client.call_tool(tool_call)
    return result
```

### LLM Integration Pattern
```python
# Initialize provider
llm_provider = create_llm_provider(provider, model)
await llm_provider.initialize()

# Generate with tools
result = await llm_provider.generate_with_tools(
    prompt=message,
    tools=formatted_tools,
    timeout=30.0
)

# Clean up
await llm_provider.close()
```

## Adding New Endpoints

### Example: Adding a New Analysis Endpoint

1. **Define Pydantic models** (top of `api.py`, after imports):
```python
class AnalyzeRequest(BaseModel):
    tool_name: str
    depth: str  # "basic" or "deep"
    model: str | None = None

class AnalyzeResponse(BaseModel):
    analysis: dict[str, Any]
    cost: float
    duration: float
```

2. **Implement endpoint** (add to appropriate section):
```python
@app.post("/api/mcp/analyze")
async def analyze_tool(request: AnalyzeRequest) -> AnalyzeResponse:
    """
    Analyze tool usage patterns.

    Uses LLM to evaluate tool documentation and usage.
    """
    model = request.model or config.default_model
    provider = config.default_provider

    try:
        # Initialize LLM
        llm_provider = create_llm_provider(provider, model)
        await llm_provider.initialize()

        # Build prompt
        prompt = f"Analyze tool: {request.tool_name}"

        # Generate
        result = await llm_provider.generate_with_tools(
            prompt=prompt,
            tools=[],
            timeout=30.0
        )

        await llm_provider.close()

        return AnalyzeResponse(
            analysis={"result": result.response},
            cost=result.cost,
            duration=result.duration
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

3. **Test manually** via UI or curl:
```bash
curl -X POST http://localhost:8000/api/mcp/analyze \
  -H "Content-Type: application/json" \
  -d '{"tool_name": "my_tool", "depth": "basic"}'
```

### Where to Find Examples

- **MCP profile operations**: Lines 702-1401 (`/api/mcp/profiles/*`)
- **Tool discovery**: Lines 1465-1576 (`/api/mcp/tools`, `/api/mcp/resources`, etc.)
- **Test management**: Lines 1713-2303 (`/api/tests/*`)
- **LLM analysis**: Lines 2346-2783 (`/api/mcp/optimize-docs`) - **Best example for new LLM features**
- **Chat with tool execution**: Lines 1576-1713 (`/api/chat`)
- **WebSocket streaming**: `websocket.py` - `handle_chat_websocket()`

## CORS & Security

CORS is permissive for development:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

CSP (Content Security Policy) is also permissive for ngrok/dev. See `CSPMiddleware` class.

## Tips for Development

1. **Sensitive data masking**: Always mask API keys/tokens in responses (see `/api/config` for example)
2. **Profile ID format**: Use kebab-case (`local-dev`, `my-profile`)
3. **Server IDs**: Format is `{profile_id}:{mcp_name}` when referencing specific servers
4. **File paths**: Use `Path` objects, check existence before operations
5. **YAML safety**: Always use `validate_config()` before `save_mcp_yaml()`
6. **Cost tracking**: Return cost/duration for all LLM operations
7. **Error messages**: Be specific - include what failed and why
8. **Timeouts**: Default to 30s for MCP/LLM operations, make configurable via request

## Common Gotchas

- **YAML persistence**: Changes to profiles must call `save_mcp_yaml()` or they're lost
- **Client caching**: Cached clients may be stale - consider invalidation strategy
- **Path handling**: Tests are relative to `tests/` dir, profiles relative to `.mcp_services.yaml`
- **Auth token masking**: Show first 8 and last 4 chars only, unless it's a variable like `${ENV_VAR}`
- **Model defaults**: Always fall back to `config.default_model` and `config.default_provider`
