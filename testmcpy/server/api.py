"""
FastAPI server for testmcpy web UI.
"""

import warnings

# Suppress all deprecation warnings from websockets before any imports
warnings.filterwarnings("ignore", category=DeprecationWarning, module="websockets")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="websockets.legacy")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="uvicorn")

import json
import re
from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from testmcpy.config import get_config
from testmcpy.mcp_profiles import load_profile
from testmcpy.server.routers import auth as auth_router
from testmcpy.server.routers import llm as llm_router
from testmcpy.server.routers import mcp_profiles as mcp_profiles_router
from testmcpy.server.routers import test_profiles as test_profiles_router
from testmcpy.server.routers import tests as tests_router
from testmcpy.src.llm_integration import create_llm_provider
from testmcpy.src.mcp_client import MCPClient, MCPToolCall


# Enums for validation
class LLMProvider(str, Enum):
    OLLAMA = "ollama"
    OPENAI = "openai"
    LOCAL = "local"
    ANTHROPIC = "anthropic"
    CLAUDE_SDK = "claude-sdk"
    CLAUDE_CLI = "claude-cli"


class AuthType(str, Enum):
    NONE = "none"
    BEARER = "bearer"
    JWT = "jwt"
    OAUTH = "oauth"


# Pydantic models for request/response
class AuthConfig(BaseModel):
    type: AuthType
    token: str | None = None
    api_url: str | None = None
    api_token: str | None = None
    api_secret: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    token_url: str | None = None
    scopes: list[str] | None = None
    insecure: bool = False  # Skip SSL verification
    oauth_auto_discover: bool = False  # Use RFC 8414 auto-discovery for OAuth


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    model: str | None = None
    provider: LLMProvider | None = None
    llm_profile: str | None = None  # LLM profile ID to use
    profiles: list[str] | None = None  # List of MCP profile IDs to use
    history: list[dict[str, Any]] | None = None  # Chat history for context


class ChatResponse(BaseModel):
    response: str
    tool_calls: list[dict[str, Any]] = []
    thinking: str | None = None  # Extended thinking content (Claude 4 models)
    token_usage: dict[str, int] | None = None
    cost: float = 0.0
    duration: float = 0.0


class FormatSchemaRequest(BaseModel):
    tool_schema: dict[str, Any] = Field(..., alias="schema")
    tool_name: str
    format: str  # e.g., "python_client", "javascript_client", "typescript_client"
    mcp_url: str | None = None  # For curl format with actual values
    auth_token: str | None = None  # For curl format with actual values
    profile: str | None = (
        None  # MCP profile to get auth from (e.g., "sandbox:Preset Sandbox 66d22a6f")
    )

    model_config = {"populate_by_name": True}


class OptimizeDocsRequest(BaseModel):
    tool_name: str
    description: str
    input_schema: dict[str, Any]
    model: str | None = None
    provider: str | None = None


class OptimizeDocsResponse(BaseModel):
    analysis: dict[str, Any]
    suggestions: dict[str, Any]
    original: dict[str, Any]
    cost: float
    duration: float


class ToolCompareRequest(BaseModel):
    tool_name: str
    profile1: str  # Format: "profile_id:mcp_name"
    profile2: str  # Format: "profile_id:mcp_name"
    parameters: dict[str, Any] = {}
    iterations: int = 3


class ToolDebugRequest(BaseModel):
    parameters: dict[str, Any]
    profile: str | None = None


class ToolDebugResponse(BaseModel):
    success: bool
    response: dict[str, Any] | list[Any] | str | None
    steps: list[dict[str, Any]]
    total_time: float
    error: str | None = None


# Global state
config = get_config()
mcp_client: MCPClient | None = None  # Default MCP client (for backwards compat)
mcp_clients: dict[str, MCPClient] = {}  # Cache of MCP clients by "{profile_id}:{mcp_name}"
active_websockets: list[WebSocket] = []


async def get_mcp_clients_for_profile(profile_id: str) -> list[tuple[str, MCPClient]]:
    """
    Get or create MCP clients for all MCP servers in a profile.

    Returns:
        List of tuples (mcp_name, MCPClient) for all MCPs in the profile
    """
    global mcp_clients

    # Load profile
    profile = load_profile(profile_id)
    if not profile:
        raise ValueError(f"Profile '{profile_id}' not found in .mcp_services.yaml")

    clients = []

    # Handle case where profile has no MCPs (backward compatibility check)
    if not profile.mcps:
        raise ValueError(f"Profile '{profile_id}' has no MCP servers configured")

    # Initialize a client for each MCP server in the profile
    for mcp_server in profile.mcps:
        cache_key = f"{profile_id}:{mcp_server.name}"

        # Return cached client if exists
        if cache_key in mcp_clients:
            clients.append((mcp_server.name, mcp_clients[cache_key]))
            continue

        # Create client with auth configuration
        auth_dict = mcp_server.auth.to_dict()
        client = MCPClient(mcp_server.mcp_url, auth=auth_dict)
        await client.initialize()

        # Cache the client
        mcp_clients[cache_key] = client
        clients.append((mcp_server.name, client))
        print(
            f"MCP client initialized for profile '{profile_id}', MCP '{mcp_server.name}' at {mcp_server.mcp_url}"
        )

    return clients


async def get_mcp_client_for_server(profile_id: str, mcp_name: str) -> MCPClient | None:
    """
    Get or create MCP client for a specific MCP server in a profile.

    Args:
        profile_id: The profile ID
        mcp_name: The name of the specific MCP server within the profile

    Returns:
        MCPClient instance or None if not found
    """
    global mcp_clients

    # Load profile
    profile = load_profile(profile_id)
    if not profile:
        print(f"Profile '{profile_id}' not found")
        return None

    # Find the specific MCP server
    mcp_server = None
    for server in profile.mcps:
        if server.name == mcp_name:
            mcp_server = server
            break

    if not mcp_server:
        print(f"MCP server '{mcp_name}' not found in profile '{profile_id}'")
        return None

    # Check cache
    cache_key = f"{profile_id}:{mcp_server.name}"
    if cache_key in mcp_clients:
        return mcp_clients[cache_key]

    # Create client with auth configuration
    auth_dict = mcp_server.auth.to_dict()
    client = MCPClient(mcp_server.mcp_url, auth=auth_dict)
    await client.initialize()

    # Cache the client
    mcp_clients[cache_key] = client
    print(f"MCP client initialized for '{profile_id}:{mcp_server.name}' at {mcp_server.mcp_url}")

    return client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for startup and shutdown."""
    global mcp_client, mcp_clients
    # Startup
    try:
        mcp_url = config.get_mcp_url()
        if mcp_url:
            mcp_client = MCPClient(mcp_url)
            await mcp_client.initialize()
            print(f"MCP client initialized at {mcp_url}")
        else:
            print("No default MCP URL configured")
    except Exception as e:
        print(f"Warning: Failed to initialize MCP client: {e}")

    yield

    # Shutdown
    if mcp_client:
        await mcp_client.close()

    # Close all profile clients (cache keys are "{profile_id}:{mcp_name}")
    for cache_key, client in mcp_clients.items():
        try:
            await client.close()
            print(f"Closed MCP client '{cache_key}'")
        except Exception as e:
            print(f"Error closing client '{cache_key}': {e}")


# Initialize FastAPI app
app = FastAPI(
    title="testmcpy Web UI",
    description="Web interface for testing MCP services with LLMs",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add middleware to set CSP headers for ngrok compatibility
from starlette.middleware.base import BaseHTTPMiddleware


class CSPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)

        # Set permissive CSP for development (allows ngrok)
        # In production, you'd want to tighten this up
        response.headers["Content-Security-Policy"] = (
            "default-src * 'unsafe-inline' 'unsafe-eval' data: blob:; "
            "script-src * 'unsafe-inline' 'unsafe-eval'; "
            "style-src * 'unsafe-inline'; "
            "img-src * data: blob:; "
            "font-src * data:; "
            "connect-src *; "
        )

        return response


app.add_middleware(CSPMiddleware)


# Global Exception Handlers - Never let the server crash

from testmcpy.error_handlers import global_exception_handler

app.exception_handler(Exception)(global_exception_handler)

# Register routers
app.include_router(auth_router.router)
app.include_router(llm_router.router)
app.include_router(mcp_profiles_router.router)
app.include_router(test_profiles_router.router)
app.include_router(tests_router.router)


# API Routes


@app.get("/")
async def root():
    """Root endpoint - serves the React app."""
    ui_dir = Path(__file__).parent.parent / "ui" / "dist"
    index_file = ui_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "testmcpy Web UI - Build the React app first"}


@app.get("/api/health")
async def health_check():
    """Health check endpoint with detailed status."""
    from testmcpy.mcp_profiles import get_profile_config

    # Check if MCP config exists
    has_config = False
    profile_count = 0
    mcp_server_count = 0

    try:
        profile_config = get_profile_config()
        if profile_config.has_profiles():
            has_config = True
            profile_ids = profile_config.list_profiles()
            profile_count = len(profile_ids)
            for profile_id in profile_ids:
                profile = profile_config.get_profile(profile_id)
                if profile:
                    mcp_server_count += len(profile.mcps)
    except Exception:
        pass

    return {
        "status": "healthy",
        "mcp_connected": mcp_client is not None,
        "mcp_clients_cached": len(mcp_clients),
        "has_config": has_config,
        "profile_count": profile_count,
        "mcp_server_count": mcp_server_count,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/config")
async def get_configuration():
    """Get current configuration."""
    all_config = config.get_all_with_sources()

    # Mask sensitive values
    masked_config = {}
    for key, (value, source) in all_config.items():
        if "API_KEY" in key or "TOKEN" in key or "SECRET" in key:
            if value:
                masked_value = f"{value[:8]}...{value[-4:]}" if len(value) > 12 else "***"
            else:
                masked_value = None
        else:
            masked_value = value

        masked_config[key] = {"value": masked_value, "source": source}

    return masked_config


@app.get("/api/models")
async def list_models():
    """List available models for each provider."""
    return {
        "anthropic": [
            {
                "id": "claude-sonnet-4-5",
                "name": "Claude Sonnet 4.5",
                "description": "Latest Sonnet 4.5 (most capable)",
            },
            {
                "id": "claude-haiku-4-5",
                "name": "Claude Haiku 4.5",
                "description": "Latest Haiku 4.5 (fast & efficient)",
            },
            {
                "id": "claude-opus-4-1",
                "name": "Claude Opus 4.1",
                "description": "Latest Opus 4.1 (most powerful)",
            },
            {
                "id": "claude-haiku-4-5",
                "name": "Claude 3.5 Haiku",
                "description": "Legacy Haiku 3.5",
            },
        ],
        "ollama": [
            {
                "id": "llama3.1:8b",
                "name": "Llama 3.1 8B",
                "description": "Meta's Llama 3.1 8B (good balance)",
            },
            {
                "id": "llama3.1:70b",
                "name": "Llama 3.1 70B",
                "description": "Meta's Llama 3.1 70B (more capable)",
            },
            {
                "id": "qwen2.5:14b",
                "name": "Qwen 2.5 14B",
                "description": "Alibaba's Qwen 2.5 14B (strong coding)",
            },
            {"id": "mistral:7b", "name": "Mistral 7B", "description": "Mistral 7B (efficient)"},
        ],
        "openai": [
            {
                "id": "gpt-4o",
                "name": "GPT-4 Optimized",
                "description": "GPT-4 Optimized (recommended)",
            },
            {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "description": "GPT-4 Turbo"},
            {"id": "gpt-4", "name": "GPT-4", "description": "GPT-4 (original)"},
            {
                "id": "gpt-3.5-turbo",
                "name": "GPT-3.5 Turbo",
                "description": "GPT-3.5 Turbo (faster, cheaper)",
            },
        ],
    }


# MCP Tools, Resources, Prompts


@app.get("/api/mcp/tools")
async def list_mcp_tools(profiles: list[str] = Query(default=None)):
    """List all MCP tools with their schemas. Supports optional ?profiles=xxx&profiles=yyy parameters."""
    try:
        all_tools = []

        if profiles:
            # Parse server IDs in format "profileId:mcpName"
            for server_id in profiles:
                if ":" in server_id:
                    # New format: specific server selection
                    profile_id, mcp_name = server_id.split(":", 1)
                    client = await get_mcp_client_for_server(profile_id, mcp_name)
                    if client:
                        tools = await client.list_tools()
                        for tool in tools:
                            all_tools.append(
                                {
                                    "name": tool.name,
                                    "description": tool.description,
                                    "input_schema": tool.input_schema,
                                    "mcp_source": mcp_name,
                                }
                            )
                else:
                    # Legacy format: entire profile (load all servers from profile)
                    clients = await get_mcp_clients_for_profile(server_id)
                    for mcp_name, client in clients:
                        tools = await client.list_tools()
                        for tool in tools:
                            all_tools.append(
                                {
                                    "name": tool.name,
                                    "description": tool.description,
                                    "input_schema": tool.input_schema,
                                    "mcp_source": mcp_name,
                                }
                            )

        return all_tools
    except HTTPException:
        raise
    except Exception as e:
        # Check if it's a connection error
        error_msg = str(e).lower()
        if (
            "401" in error_msg
            or "403" in error_msg
            or "unauthorized" in error_msg
            or "forbidden" in error_msg
            or "not connect" in error_msg
        ):
            raise HTTPException(
                status_code=503,
                detail=f"Service unavailable: Unable to connect to MCP server. {str(e)}",
            )
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/mcp/resources")
async def list_mcp_resources(profiles: list[str] = Query(default=None)):
    """List all MCP resources. Supports optional ?profiles=xxx&profiles=yyy parameters."""
    try:
        all_resources = []

        if profiles:
            # Parse server IDs in format "profileId:mcpName"
            for server_id in profiles:
                if ":" in server_id:
                    # New format: specific server selection
                    profile_id, mcp_name = server_id.split(":", 1)
                    client = await get_mcp_client_for_server(profile_id, mcp_name)
                    if client:
                        resources = await client.list_resources()
                        for resource in resources:
                            if isinstance(resource, dict):
                                resource["mcp_source"] = mcp_name
                            all_resources.append(resource)
                else:
                    # Legacy format: entire profile
                    clients = await get_mcp_clients_for_profile(server_id)
                    for mcp_name, client in clients:
                        resources = await client.list_resources()
                        for resource in resources:
                            if isinstance(resource, dict):
                                resource["mcp_source"] = mcp_name
                            all_resources.append(resource)

        return all_resources
    except HTTPException:
        raise
    except Exception as e:
        # Check if it's a connection error
        error_msg = str(e).lower()
        if (
            "401" in error_msg
            or "403" in error_msg
            or "unauthorized" in error_msg
            or "forbidden" in error_msg
            or "not connect" in error_msg
        ):
            raise HTTPException(
                status_code=503,
                detail=f"Service unavailable: Unable to connect to MCP server. {str(e)}",
            )
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/mcp/prompts")
async def list_mcp_prompts(profiles: list[str] = Query(default=None)):
    """List all MCP prompts. Supports optional ?profiles=xxx&profiles=yyy parameters."""
    try:
        all_prompts = []

        if profiles:
            # Parse server IDs in format "profileId:mcpName"
            for server_id in profiles:
                if ":" in server_id:
                    # New format: specific server selection
                    profile_id, mcp_name = server_id.split(":", 1)
                    client = await get_mcp_client_for_server(profile_id, mcp_name)
                    if client:
                        prompts = await client.list_prompts()
                        for prompt in prompts:
                            if isinstance(prompt, dict):
                                prompt["mcp_source"] = mcp_name
                            all_prompts.append(prompt)
                else:
                    # Legacy format: entire profile
                    clients = await get_mcp_clients_for_profile(server_id)
                    for mcp_name, client in clients:
                        prompts = await client.list_prompts()
                        for prompt in prompts:
                            if isinstance(prompt, dict):
                                prompt["mcp_source"] = mcp_name
                            all_prompts.append(prompt)

        return all_prompts
    except HTTPException:
        raise
    except Exception as e:
        # Check if it's a connection error
        error_msg = str(e).lower()
        if (
            "401" in error_msg
            or "403" in error_msg
            or "unauthorized" in error_msg
            or "forbidden" in error_msg
            or "not connect" in error_msg
        ):
            raise HTTPException(
                status_code=503,
                detail=f"Service unavailable: Unable to connect to MCP server. {str(e)}",
            )
        raise HTTPException(status_code=500, detail=str(e))


# Chat endpoint


@app.post("/api/chat")
async def chat(request: ChatRequest) -> ChatResponse:
    """Send a message to the LLM with MCP tools."""
    # Get model and provider from LLM profile if specified
    if request.llm_profile:
        from testmcpy.llm_profiles import load_llm_profile

        llm_profile = load_llm_profile(request.llm_profile)
        if llm_profile:
            default_provider_config = llm_profile.get_default_provider()
            if default_provider_config:
                model = request.model or default_provider_config.model
                provider = request.provider or default_provider_config.provider
            else:
                model = request.model or config.default_model
                provider = request.provider or config.default_provider
        else:
            model = request.model or config.default_model
            provider = request.provider or config.default_provider
    else:
        model = request.model or config.default_model
        provider = request.provider or config.default_provider

    if not model or not provider:
        raise HTTPException(
            status_code=400,
            detail="Model and provider must be specified or configured in LLM profile",
        )

    try:
        # Determine which MCP clients to use
        clients_to_use = []  # List of (profile_id, mcp_name, client) tuples
        if request.profiles:
            # Parse server IDs in format "profileId:mcpName"
            for server_id in request.profiles:
                if ":" in server_id:
                    # New format: specific server selection
                    profile_id, mcp_name = server_id.split(":", 1)
                    client = await get_mcp_client_for_server(profile_id, mcp_name)
                    if client:
                        clients_to_use.append((profile_id, mcp_name, client))
                else:
                    # Legacy format: entire profile (load all servers from profile)
                    profile_clients = await get_mcp_clients_for_profile(server_id)
                    for mcp_name, client in profile_clients:
                        clients_to_use.append((server_id, mcp_name, client))

        # Gather tools from all clients
        all_tools = []
        tool_to_client = {}  # Map tool name to (client, profile_id, mcp_name) for execution

        for profile_id, mcp_name, client in clients_to_use:
            tools = await client.list_tools()
            for tool in tools:
                # Track which client provides this tool (last wins if duplicate names)
                tool_to_client[tool.name] = (client, profile_id, mcp_name)

                # Add tool to list
                all_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.input_schema,
                        },
                    }
                )

        # Initialize LLM provider
        llm_provider = create_llm_provider(provider, model)
        await llm_provider.initialize()

        # Generate response with optional history
        result = await llm_provider.generate_with_tools(
            prompt=request.message, tools=all_tools, timeout=30.0, messages=request.history
        )

        # Execute tool calls if any
        tool_calls_with_results = []
        if result.tool_calls:
            for tool_call in result.tool_calls:
                mcp_tool_call = MCPToolCall(
                    name=tool_call["name"],
                    arguments=tool_call.get("arguments", {}),
                    id=tool_call.get("id", "unknown"),
                )

                # Find the appropriate client for this tool
                tool_info = tool_to_client.get(tool_call["name"])
                if not tool_info:
                    # Tool not found in any client
                    tool_call_with_result = {
                        "name": tool_call["name"],
                        "arguments": tool_call.get("arguments", {}),
                        "id": tool_call.get("id", "unknown"),
                        "result": None,
                        "error": f"Tool '{tool_call['name']}' not found in any MCP profile",
                        "is_error": True,
                    }
                    tool_calls_with_results.append(tool_call_with_result)
                    continue

                # Extract client info
                client_for_tool, profile_id, mcp_name = tool_info

                # Execute tool call
                tool_result = await client_for_tool.call_tool(mcp_tool_call)

                # Add result to tool call
                tool_call_with_result = {
                    "name": tool_call["name"],
                    "arguments": tool_call.get("arguments", {}),
                    "id": tool_call.get("id", "unknown"),
                    "result": tool_result.content if not tool_result.is_error else None,
                    "error": tool_result.error_message if tool_result.is_error else None,
                    "is_error": tool_result.is_error,
                }
                tool_calls_with_results.append(tool_call_with_result)

        await llm_provider.close()

        # Clean up response - remove tool execution messages since we show them separately
        clean_response = result.response
        if tool_calls_with_results:
            # Remove lines that start with "Tool <name> executed" or "Tool <name> failed"
            lines = clean_response.split("\n")
            filtered_lines = []
            skip_next = False
            for line in lines:
                # Skip tool execution status lines
                if line.strip().startswith("Tool ") and (
                    " executed successfully" in line or " failed" in line
                ):
                    skip_next = True
                    continue
                # Skip the raw content line after tool execution
                if skip_next and (line.strip().startswith("[") or line.strip().startswith("{")):
                    skip_next = False
                    continue
                skip_next = False
                filtered_lines.append(line)

            clean_response = "\n".join(filtered_lines).strip()

        return ChatResponse(
            response=clean_response,
            tool_calls=tool_calls_with_results,
            thinking=result.thinking,
            token_usage=result.token_usage,
            cost=result.cost,
            duration=result.duration,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/format")
async def format_schema(request: FormatSchemaRequest):
    """Convert a JSON schema to various formats including client code examples."""
    try:
        from testmcpy.formatters import FORMATS

        format_config = FORMATS.get(request.format)
        if not format_config:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported format: {request.format}. Available formats: {list(FORMATS.keys())}",
            )

        converter = format_config["convert"]

        # For curl and client formats, pass mcp_url and auth_token
        client_formats = ["curl", "python_client", "javascript_client", "typescript_client"]
        if request.format in client_formats:
            mcp_url = request.mcp_url
            auth_token = request.auth_token

            # If profile is provided, get the auth token from the cached MCP client
            if request.profile and not auth_token:
                # Profile format is "profileId:mcpName"
                if ":" in request.profile:
                    profile_id, mcp_name = request.profile.split(":", 1)
                    # Get the cached client
                    cache_key = request.profile
                    if cache_key in mcp_clients:
                        client = mcp_clients[cache_key]
                        # Get auth token from the client's BearerAuth
                        if client.auth and hasattr(client.auth, "token"):
                            auth_token = client.auth.token
                        # Also get MCP URL from client if not provided
                        if not mcp_url and client.base_url:
                            mcp_url = client.base_url

            # Fall back to config if no profile provided
            if not mcp_url:
                mcp_url = config.get_mcp_url()

            formatted = converter(
                request.tool_schema, request.tool_name, mcp_url=mcp_url, auth_token=auth_token
            )
        else:
            formatted = converter(request.tool_schema, request.tool_name)

        return {
            "success": True,
            "format": request.format,
            "code": formatted,
            "language": format_config["language"],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/mcp/optimize-docs")
async def optimize_tool_docs(request: OptimizeDocsRequest) -> OptimizeDocsResponse:
    """
    Analyze tool documentation and suggest improvements.

    Uses an LLM to evaluate tool documentation against best practices
    for LLM tool calling and provides actionable suggestions.
    """
    model = request.model or config.default_model
    provider = request.provider or config.default_provider

    if not model or not provider:
        raise HTTPException(
            status_code=400,
            detail="Model and provider must be configured. Set DEFAULT_MODEL and DEFAULT_PROVIDER in config.",
        )

    try:
        # Initialize LLM provider (use Haiku for cost efficiency)
        llm_model = model
        if provider == "anthropic" and "haiku" not in model.lower():
            # Use Haiku for analysis to save costs
            llm_model = "claude-haiku-4-5"

        llm_provider = create_llm_provider(provider, llm_model)
        await llm_provider.initialize()

        # Format the input schema for better readability
        schema_str = json.dumps(request.input_schema, indent=2)

        # Build the analysis prompt with structured output
        analysis_prompt = f"""You are an expert at writing tool documentation for LLMs (Large Language Models) that use function/tool calling.

Your task: Analyze this MCP (Model Context Protocol) tool and suggest improvements to help LLMs call it correctly.

TOOL INFORMATION:
==================
Tool Name: {request.tool_name}

Current Description:
{request.description}

Input Schema:
{schema_str}

ANALYSIS FRAMEWORK:
===================
Evaluate the documentation against these criteria:

1. CLARITY (0-100): Is it immediately obvious what this tool does?
   - Does the first sentence clearly state the tool's purpose?
   - Would an LLM understand the exact action this tool performs?
   - Are technical terms explained or self-evident?

2. COMPLETENESS (0-100): Are all parameters well-documented?
   - Is each parameter's purpose clear from the schema?
   - Are types, constraints, and valid values specified?
   - Are required vs optional parameters obvious?

3. ACTIONABILITY (0-100): Would an LLM know when to use this?
   - Is it clear what scenarios this tool is appropriate for?
   - Are there indicators of when NOT to use this tool?
   - Are related/alternative tools mentioned?

4. EXAMPLES (0-100): Are there concrete usage examples?
   - Are there example parameter values?
   - Are there example use cases or scenarios?
   - Would an LLM be able to construct a valid call from the docs?

5. CONSTRAINTS (0-100): Are limitations clearly stated?
   - Are there any prerequisites mentioned?
   - Are error conditions described?
   - Are rate limits, size limits, or other constraints noted?

COMMON ISSUES TO DETECT:
========================
- Vague verbs: "manages", "handles", "processes" → be specific: "creates", "updates", "deletes"
- Missing context: no explanation of when to use vs alternatives
- Parameter confusion: unclear names without descriptions
- Type ambiguity: parameters without clear type/format info
- No examples: abstract descriptions without concrete usage
- Jargon overload: technical terms without explanation
- Ambiguous language: multiple possible interpretations
- Hidden constraints: undocumented limitations or requirements

YOUR TASK:
==========
Provide a detailed analysis in valid JSON format. Return ONLY the JSON object, no markdown formatting, no code blocks.

{{
  "clarity_score": <number 0-100 representing overall quality>,
  "issues": [
    {{
      "category": "<one of: clarity, completeness, actionability, examples, constraints>",
      "severity": "<one of: high, medium, low>",
      "issue": "<specific description of what's wrong>",
      "current": "<the problematic text from current docs>",
      "suggestion": "<actionable advice on how to fix>"
    }}
  ],
  "improved_description": "<Complete rewritten description that includes: (1) Clear statement of what tool does, (2) When to use it, (3) Brief parameter overview, (4) Key constraints. Should be 3-5 sentences, written specifically for LLM consumption.>",
  "improvements": [
    {{
      "issue": "<brief issue name>",
      "before": "<current problematic text>",
      "after": "<improved replacement text>",
      "explanation": "<why this improvement helps LLMs>"
    }}
  ]
}}

IMPORTANT: Return ONLY valid JSON. Do not wrap in markdown code blocks. Start with {{ and end with }}."""

        # Generate analysis - use a mock "tool" to get structured JSON output
        # This works better than asking for raw JSON in many LLMs
        analysis_tool = {
            "name": "submit_analysis",
            "description": "Submit the documentation analysis results",
            "input_schema": {
                "type": "object",
                "properties": {
                    "clarity_score": {
                        "type": "number",
                        "description": "Overall documentation quality score from 0-100",
                    },
                    "issues": {
                        "type": "array",
                        "description": "List of issues found in the documentation",
                        "items": {
                            "type": "object",
                            "properties": {
                                "category": {
                                    "type": "string",
                                    "enum": [
                                        "clarity",
                                        "completeness",
                                        "actionability",
                                        "examples",
                                        "constraints",
                                    ],
                                    "description": "Issue category",
                                },
                                "severity": {
                                    "type": "string",
                                    "enum": ["high", "medium", "low"],
                                    "description": "Issue severity",
                                },
                                "issue": {
                                    "type": "string",
                                    "description": "Description of the issue",
                                },
                                "current": {
                                    "type": "string",
                                    "description": "The problematic text from current docs",
                                },
                                "suggestion": {
                                    "type": "string",
                                    "description": "How to fix this issue",
                                },
                            },
                            "required": ["category", "severity", "issue", "suggestion"],
                        },
                    },
                    "improved_description": {
                        "type": "string",
                        "description": "Complete rewritten description that addresses all issues",
                    },
                    "improvements": {
                        "type": "array",
                        "description": "Specific before/after improvements",
                        "items": {
                            "type": "object",
                            "properties": {
                                "issue": {"type": "string", "description": "Brief issue name"},
                                "before": {
                                    "type": "string",
                                    "description": "Current problematic text",
                                },
                                "after": {
                                    "type": "string",
                                    "description": "Improved replacement text",
                                },
                                "explanation": {
                                    "type": "string",
                                    "description": "Why this improvement helps LLMs",
                                },
                            },
                            "required": ["issue", "before", "after", "explanation"],
                        },
                    },
                },
                "required": ["clarity_score", "issues", "improved_description", "improvements"],
            },
        }

        # Update prompt to request tool use
        analysis_prompt = f"""You are an expert at writing tool documentation for LLMs (Large Language Models) that use function/tool calling.

Your task: Analyze this MCP (Model Context Protocol) tool and suggest improvements to help LLMs call it correctly.

TOOL INFORMATION:
==================
Tool Name: {request.tool_name}

Current Description:
{request.description}

Input Schema:
{schema_str}

ANALYSIS FRAMEWORK:
===================
Evaluate the documentation against these criteria:

1. CLARITY (0-100): Is it immediately obvious what this tool does?
   - Does the first sentence clearly state the tool's purpose?
   - Would an LLM understand the exact action this tool performs?
   - Are technical terms explained or self-evident?

2. COMPLETENESS (0-100): Are all parameters well-documented?
   - Is each parameter's purpose clear from the schema?
   - Are types, constraints, and valid values specified?
   - Are required vs optional parameters obvious?

3. ACTIONABILITY (0-100): Would an LLM know when to use this?
   - Is it clear what scenarios this tool is appropriate for?
   - Are there indicators of when NOT to use this tool?
   - Are related/alternative tools mentioned?

4. EXAMPLES (0-100): Are there concrete usage examples?
   - Are there example parameter values?
   - Are there example use cases or scenarios?
   - Would an LLM be able to construct a valid call from the docs?

5. CONSTRAINTS (0-100): Are limitations clearly stated?
   - Are there any prerequisites mentioned?
   - Are error conditions described?
   - Are rate limits, size limits, or other constraints noted?

COMMON ISSUES TO DETECT:
========================
- Vague verbs: "manages", "handles", "processes" → be specific: "creates", "updates", "deletes"
- Missing context: no explanation of when to use vs alternatives
- Parameter confusion: unclear names without descriptions
- Type ambiguity: parameters without clear type/format info
- No examples: abstract descriptions without concrete usage
- Jargon overload: technical terms without explanation
- Ambiguous language: multiple possible interpretations
- Hidden constraints: undocumented limitations or requirements

YOUR TASK:
==========
You MUST call the 'submit_analysis' tool with ALL required fields. Do not omit any fields.

REQUIRED FIELDS (all must be provided):

1. clarity_score (number): Overall quality score 0-100

2. issues (array): List of specific problems - MUST include at least 2-3 issues even if docs seem good
   Each issue MUST have: category, severity, issue, current, suggestion
   Example issues to always look for:
   - Missing concrete parameter examples
   - Unclear when to use this vs alternatives
   - Technical jargon without explanation
   - Missing error conditions or constraints
   - Vague verbs like "manages", "handles", "processes"

3. improved_description (string): Complete 3-5 sentence rewrite that includes:
   - Clear statement of what tool does (1 sentence, use specific verbs not "manages/handles")
   - When to use it and key scenarios (1-2 sentences)
   - Brief parameter overview mentioning key parameters by name (1 sentence)
   - Key constraints or limitations (1 sentence)

4. improvements (array): At least 2-3 specific before/after examples
   Each improvement MUST have: issue, before, after, explanation

CRITICAL INSTRUCTIONS:
- You MUST provide ALL four fields with complete data
- Do NOT provide only clarity_score - this will fail validation
- Even if documentation seems good, find at least 2-3 ways to improve it for LLM consumption
- Be critical and thorough - no documentation is perfect

Call the submit_analysis tool NOW with complete data."""

        result = await llm_provider.generate_with_tools(
            prompt=analysis_prompt, tools=[analysis_tool], timeout=60.0
        )

        # Parse the response - check if LLM used the tool
        try:
            analysis_data = None

            # Debug logging
            print("\n=== LLM Response Debug ===")
            print(f"Tool calls count: {len(result.tool_calls) if result.tool_calls else 0}")
            print(f"Response text length: {len(result.response)}")
            print(f"Response preview: {result.response[:200]}")

            # First, check if the LLM made a tool call
            if result.tool_calls and len(result.tool_calls) > 0:
                # LLM used the submit_analysis tool - perfect!
                print(f"Tool calls: {result.tool_calls}")
                tool_call = result.tool_calls[0]
                print(f"Tool call name: {tool_call.get('name')}")
                print(f"Tool call keys: {list(tool_call.keys())}")

                if tool_call.get("name") == "submit_analysis":
                    # Anthropic uses "arguments" key, some providers use "input"
                    analysis_data = tool_call.get("arguments") or tool_call.get("input", {})
                    print("✓ LLM used tool call for structured output")
                    print(f"  Arguments keys: {list(analysis_data.keys())}")
                    print(f"  Score: {analysis_data.get('clarity_score')}")
                    print(f"  Issues found: {len(analysis_data.get('issues', []))}")

                    # Validate that LLM provided all required fields
                    missing_fields = []
                    if not analysis_data.get("clarity_score"):
                        missing_fields.append("clarity_score")
                    if not analysis_data.get("issues") or len(analysis_data.get("issues", [])) == 0:
                        missing_fields.append("issues (must have at least 1 issue)")
                    if not analysis_data.get("improved_description"):
                        missing_fields.append("improved_description")
                    if (
                        not analysis_data.get("improvements")
                        or len(analysis_data.get("improvements", [])) == 0
                    ):
                        missing_fields.append("improvements (must have at least 1 improvement)")

                    if missing_fields:
                        error_msg = f"LLM provided incomplete data. Missing required fields: {', '.join(missing_fields)}"
                        print(f"✗ {error_msg}")
                        raise ValueError(error_msg)
                else:
                    print(f"✗ Unexpected tool call: {tool_call.get('name')}")

            # If no tool call, try to parse JSON from response text
            if not analysis_data:
                print("No tool call found, attempting to parse JSON from response text")
                response_text = result.response.strip()

                # Remove any markdown code blocks
                response_text = re.sub(r"```(?:json)?\s*", "", response_text)
                response_text = re.sub(r"```\s*$", "", response_text)

                # Try to find JSON object (handle nested braces properly)
                start_idx = response_text.find("{")
                if start_idx == -1:
                    raise ValueError("No JSON object found in response")

                # Count braces to find matching closing brace
                brace_count = 0
                end_idx = -1
                for i in range(start_idx, len(response_text)):
                    if response_text[i] == "{":
                        brace_count += 1
                    elif response_text[i] == "}":
                        brace_count -= 1
                        if brace_count == 0:
                            end_idx = i + 1
                            break

                if end_idx == -1:
                    raise ValueError("Unmatched braces in JSON response")

                json_str = response_text[start_idx:end_idx]
                analysis_data = json.loads(json_str)

            # Validate and fix required fields
            if "clarity_score" not in analysis_data or not isinstance(
                analysis_data["clarity_score"], (int, float)
            ):
                print("Warning: Missing or invalid clarity_score, using default 50")
                analysis_data["clarity_score"] = 50
            if "issues" not in analysis_data or not isinstance(analysis_data["issues"], list):
                print("Warning: Missing or invalid issues array")
                analysis_data["issues"] = []
            if (
                "improved_description" not in analysis_data
                or not analysis_data["improved_description"]
            ):
                print("Warning: Missing improved_description, using original")
                analysis_data["improved_description"] = request.description
            if "improvements" not in analysis_data or not isinstance(
                analysis_data["improvements"], list
            ):
                print("Warning: Missing improvements array")
                analysis_data["improvements"] = []

            # Ensure each issue has required fields
            for issue in analysis_data["issues"]:
                if "category" not in issue:
                    issue["category"] = "clarity"
                if "severity" not in issue:
                    issue["severity"] = "medium"
                if "issue" not in issue:
                    issue["issue"] = "Documentation issue"
                if "current" not in issue:
                    issue["current"] = ""
                if "suggestion" not in issue:
                    issue["suggestion"] = ""

        except Exception as e:
            # Fallback to basic response if parsing fails
            print(f"✗ Failed to parse LLM response: {e}")
            print(f"Response text (first 500 chars): {result.response[:500]}")
            print(f"Tool calls: {result.tool_calls}")
            analysis_data = {
                "clarity_score": 50,
                "issues": [
                    {
                        "category": "clarity",
                        "severity": "high",
                        "issue": "LLM response parsing failed - check server logs for details",
                        "current": request.description,
                        "suggestion": f"Error: {str(e)}",
                    }
                ],
                "improved_description": request.description,
                "improvements": [],
            }

        await llm_provider.close()

        # Build response
        return OptimizeDocsResponse(
            analysis={
                "score": analysis_data.get("clarity_score", 50),
                "clarity": "good"
                if analysis_data.get("clarity_score", 50) >= 75
                else ("fair" if analysis_data.get("clarity_score", 50) >= 50 else "poor"),
                "issues": analysis_data.get("issues", []),
            },
            suggestions={
                "improved_description": analysis_data.get(
                    "improved_description", request.description
                ),
                "improvements": analysis_data.get("improvements", []),
            },
            original={
                "tool_name": request.tool_name,
                "description": request.description,
                "input_schema": request.input_schema,
            },
            cost=result.cost,
            duration=result.duration,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to optimize documentation: {str(e)}")


@app.post("/api/tools/compare")
async def compare_tools(request: ToolCompareRequest):
    """
    Compare the same tool across two different MCP profiles/servers.

    This endpoint runs the specified tool multiple times on two different
    MCP servers and returns performance metrics and results for comparison.
    """
    import time

    # Parse profile IDs
    profile1_parts = request.profile1.split(":", 1)
    profile2_parts = request.profile2.split(":", 1)

    if len(profile1_parts) != 2 or len(profile2_parts) != 2:
        raise HTTPException(status_code=400, detail="Profile format must be 'profile_id:mcp_name'")

    profile1_id, mcp1_name = profile1_parts
    profile2_id, mcp2_name = profile2_parts

    # Load profiles
    try:
        profile1_data = load_profile(profile1_id)
        profile2_data = load_profile(profile2_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Profile not found: {str(e)}")

    if not profile1_data or not profile2_data:
        raise HTTPException(status_code=404, detail="One or both profiles not found")

    # Find MCP configs
    mcp1 = next((m for m in profile1_data.mcps if m.name == mcp1_name), None)
    mcp2 = next((m for m in profile2_data.mcps if m.name == mcp2_name), None)

    if not mcp1 or not mcp2:
        raise HTTPException(status_code=404, detail="MCP server not found in profile")

    # Helper function to run a single iteration
    async def run_iteration(mcp_config, iteration_num):
        result = {
            "iteration": iteration_num,
            "success": False,
            "result": None,
            "error": None,
            "duration_ms": 0,
        }

        client = None
        try:
            start_time = time.time()

            # Initialize client
            client = MCPClient(mcp_url=mcp_config.get_mcp_url(), auth=mcp_config.auth)
            await client.initialize()

            # Call the tool
            tool_result = await client.call_tool(
                name=request.tool_name, arguments=request.parameters
            )

            result["success"] = True
            result["result"] = tool_result
            result["duration_ms"] = (time.time() - start_time) * 1000

        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
            result["duration_ms"] = (time.time() - start_time) * 1000
        finally:
            if client:
                try:
                    await client.cleanup()
                except Exception:
                    pass

        return result

    # Run iterations for both profiles
    results1 = []
    results2 = []

    try:
        for i in range(request.iterations):
            # Run on profile 1
            result1 = await run_iteration(mcp1, i + 1)
            results1.append(result1)

            # Run on profile 2
            result2 = await run_iteration(mcp2, i + 1)
            results2.append(result2)

        # Calculate metrics
        avg_time1 = sum(r["duration_ms"] for r in results1) / len(results1)
        avg_time2 = sum(r["duration_ms"] for r in results2) / len(results2)
        success_rate1 = (sum(1 for r in results1 if r["success"]) / len(results1)) * 100
        success_rate2 = (sum(1 for r in results2 if r["success"]) / len(results2)) * 100

        return {
            "tool_name": request.tool_name,
            "profile1": f"{profile1_data.name} ({mcp1_name})",
            "profile2": f"{profile2_data.name} ({mcp2_name})",
            "parameters": request.parameters,
            "iterations": request.iterations,
            "results1": results1,
            "results2": results2,
            "metrics": {
                "avg_time1_ms": avg_time1,
                "avg_time2_ms": avg_time2,
                "success_rate1_pct": success_rate1,
                "success_rate2_pct": success_rate2,
                "faster_profile": 1 if avg_time1 < avg_time2 else 2,
                "time_difference_ms": abs(avg_time1 - avg_time2),
                "time_difference_pct": (abs(avg_time1 - avg_time2) / max(avg_time1, avg_time2))
                * 100,
            },
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Comparison failed: {str(e)}")


@app.post("/api/tools/{tool_name}/debug", response_model=ToolDebugResponse)
async def debug_tool(tool_name: str, request: ToolDebugRequest):
    """
    Debug a tool by calling it with parameters and returning detailed trace.

    This endpoint calls the specified tool with the provided parameters
    and returns the response along with execution timing information.
    """
    import time

    start_time = time.time()
    steps = []

    try:
        # Step 1: Prepare request
        step_start = time.time()
        steps.append(
            {
                "step": "Request Prepared",
                "timestamp": (time.time() - start_time) * 1000,
                "data": {
                    "tool_name": tool_name,
                    "parameters": request.parameters,
                    "profile": request.profile,
                },
            }
        )

        # Get MCP client for the specified profile
        client_key = request.profile or "default"
        client = mcp_clients.get(client_key)

        if not client:
            # Try to initialize client from profile
            if request.profile:
                try:
                    profile_data = load_profile(request.profile)
                    if profile_data and profile_data.mcps:
                        mcp_config = profile_data.mcps[0]
                        client = MCPClient(mcp_url=mcp_config.get_mcp_url(), auth=mcp_config.auth)
                        await client.initialize()
                        mcp_clients[client_key] = client
                except Exception as e:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to load profile '{request.profile}': {str(e)}",
                    )

        if not client:
            # Fall back to global default client
            global mcp_client
            if not mcp_client:
                raise HTTPException(
                    status_code=400,
                    detail="No MCP client configured. Please select a profile or configure a default MCP server.",
                )
            client = mcp_client

        # Step 2: Call tool
        step_start = time.time()

        try:
            response = await client.call_tool(tool_name, request.parameters)

            steps.append(
                {
                    "step": "MCP Processing Complete",
                    "timestamp": (time.time() - start_time) * 1000,
                    "data": {
                        "success": True,
                    },
                }
            )

            # Step 3: Response received
            steps.append(
                {
                    "step": "Response Received",
                    "timestamp": (time.time() - start_time) * 1000,
                    "data": {
                        "response_type": type(response).__name__,
                    },
                }
            )

            total_time = (time.time() - start_time) * 1000

            return ToolDebugResponse(
                success=True,
                response=response,
                steps=steps,
                total_time=total_time,
            )

        except Exception as tool_error:
            steps.append(
                {
                    "step": "Tool Call Failed",
                    "timestamp": (time.time() - start_time) * 1000,
                    "data": {
                        "error": str(tool_error),
                    },
                }
            )

            total_time = (time.time() - start_time) * 1000

            return ToolDebugResponse(
                success=False,
                response=None,
                steps=steps,
                total_time=total_time,
                error=str(tool_error),
            )

    except HTTPException:
        raise
    except Exception as e:
        total_time = (time.time() - start_time) * 1000

        return ToolDebugResponse(
            success=False,
            response=None,
            steps=steps,
            total_time=total_time,
            error=str(e),
        )


class SmokeTestRequest(BaseModel):
    """Request to run smoke tests."""

    profile_id: str | None = None
    mcp_url: str | None = None
    test_all_tools: bool = True
    max_tools_to_test: int = 10


@app.post("/api/smoke-test")
async def run_smoke_test_endpoint(request: SmokeTestRequest):
    """Run smoke tests on an MCP server."""
    from testmcpy.mcp_profiles import load_profile
    from testmcpy.smoke_test import run_smoke_test

    # Determine MCP URL and auth config
    if request.profile_id:
        profile = load_profile(request.profile_id)
        if not profile or not profile.mcps:
            raise HTTPException(
                status_code=404,
                detail=f"Profile '{request.profile_id}' not found or has no MCP servers",
            )

        mcp_server = profile.mcps[0]
        mcp_url = mcp_server.mcp_url
        auth_config = mcp_server.auth.to_dict() if mcp_server.auth else None
    elif request.mcp_url:
        mcp_url = request.mcp_url
        auth_config = None
    else:
        raise HTTPException(status_code=400, detail="Either profile_id or mcp_url must be provided")

    # Run smoke tests
    report = await run_smoke_test(
        mcp_url=mcp_url,
        auth_config=auth_config,
        test_all_tools=request.test_all_tools,
        max_tools_to_test=request.max_tools_to_test,
    )

    return report.to_dict()


# Catch-all route for React Router (must be before static files)
@app.get("/{full_path:path}")
async def serve_react_app(full_path: str):
    """Serve React app for all non-API routes (SPA support)."""
    # Don't intercept API routes
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")

    # Serve index.html for all other routes (client-side routing)
    ui_dir = Path(__file__).parent.parent / "ui" / "dist"
    index_file = ui_dir / "index.html"

    # Check if it's a static file request
    static_file = ui_dir / full_path
    if static_file.exists() and static_file.is_file():
        return FileResponse(static_file)

    # Otherwise serve index.html for React Router
    if index_file.exists():
        return FileResponse(index_file)

    return {"message": "testmcpy Web UI - Build the React app first"}
