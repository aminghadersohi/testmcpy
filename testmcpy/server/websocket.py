"""
WebSocket support for streaming chat responses and test execution.
"""

import asyncio
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from fastapi import WebSocket, WebSocketDisconnect

from testmcpy.config import get_config
from testmcpy.server.state import get_or_create_mcp_client
from testmcpy.src.llm_integration import create_llm_provider
from testmcpy.src.mcp_client import MCPClient, MCPToolCall
from testmcpy.src.test_runner import TestCase, TestRunner


def strip_mcp_prefix(tool_name: str) -> str:
    """Strip MCP namespace prefix from tool name.

    LLM providers may return tool names like 'mcp__testmcpy__list_charts'
    but the MCP server expects just 'list_charts'.
    """
    if "__" in tool_name:
        # Get the last part after the final __
        return tool_name.rsplit("__", 1)[-1]
    return tool_name


def _derive_workspace_and_domain_from_mcp_url(mcp_url: str) -> tuple[str | None, str | None]:
    """Split a Preset MCP URL into (workspace_hash, domain).

    Preset workspaces always live at `https://<workspace_hash>.<domain>/mcp`
    — the workspace hash is the leftmost subdomain. We use this when running
    a chatbot YAML from the UI: the selected MCP profile already encodes
    which workspace the chat tests should target, so we can populate the
    AssistantProvider's `workspace_hash`/`domain` automatically rather than
    forcing the user to duplicate that info in `.llm_providers.yaml`.

    Returns (None, None) if the URL is missing, lacks a host, has only one
    label, or is otherwise unparseable — the caller treats that as "no
    fallback available" and leaves the existing config untouched.
    """
    if not mcp_url:
        return None, None
    try:
        parsed = urlparse(mcp_url)
    except (ValueError, TypeError):
        return None, None
    host = parsed.hostname
    if not host or "." not in host:
        return None, None
    workspace, _, domain = host.partition(".")
    if not workspace or not domain:
        return None, None
    return workspace, domain


class ConnectionManager:
    """Manage WebSocket connections."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_message(self, message: dict, websocket: WebSocket):
        await websocket.send_json(message)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_json(message)


manager = ConnectionManager()


async def handle_chat_websocket(websocket: WebSocket, mcp_client: MCPClient):
    """
    Handle WebSocket chat connections with streaming responses.

    Message format from client:
    {
        "type": "chat",
        "message": "user message",
        "model": "claude-haiku-4-5",
        "provider": "anthropic"
    }

    Message format to client:
    {
        "type": "start" | "token" | "tool_call" | "tool_result" | "complete" | "error",
        "content": "...",
        "tool_name": "...",  # for tool_call
        "tool_args": {...},  # for tool_call
        "tool_result": {...},  # for tool_result
        "token_usage": {...},  # for complete
        "cost": 0.0,  # for complete
        "duration": 0.0  # for complete
    }
    """
    await manager.connect(websocket)
    config = get_config()

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()

            if data.get("type") == "chat":
                message = data.get("message", "")
                model = data.get("model") or config.default_model
                provider = data.get("provider") or config.default_provider

                # Send start message
                await manager.send_message(
                    {"type": "start", "content": "Processing your request..."}, websocket
                )

                try:
                    # Get available tools
                    tools = await mcp_client.list_tools()
                    formatted_tools = [
                        {
                            "type": "function",
                            "function": {
                                "name": tool.name,
                                "description": tool.description,
                                "parameters": tool.input_schema,
                            },
                        }
                        for tool in tools
                    ]

                    # Initialize LLM provider
                    llm_provider = create_llm_provider(provider, model)
                    await llm_provider.initialize()

                    # Generate response
                    result = await llm_provider.generate_with_tools(
                        prompt=message, tools=formatted_tools, timeout=30.0
                    )

                    # Stream the response text token by token for better UX
                    response_text = result.response
                    chunk_size = 50  # Characters per chunk
                    for i in range(0, len(response_text), chunk_size):
                        chunk = response_text[i : i + chunk_size]
                        await manager.send_message({"type": "token", "content": chunk}, websocket)
                        await asyncio.sleep(0.05)  # Small delay for streaming effect

                    # Execute tool calls if any
                    if result.tool_calls:
                        for tool_call in result.tool_calls:
                            # Send tool call notification
                            await manager.send_message(
                                {
                                    "type": "tool_call",
                                    "tool_name": tool_call["name"],
                                    "tool_args": tool_call.get("arguments", {}),
                                },
                                websocket,
                            )

                            # Execute tool - strip MCP prefix if present
                            actual_tool_name = strip_mcp_prefix(tool_call["name"])
                            mcp_tool_call = MCPToolCall(
                                name=actual_tool_name,
                                arguments=tool_call.get("arguments", {}),
                                id=tool_call.get("id", "unknown"),
                            )
                            tool_result = await mcp_client.call_tool(mcp_tool_call)

                            # Send tool result
                            await manager.send_message(
                                {
                                    "type": "tool_result",
                                    "tool_name": tool_call["name"],
                                    "tool_result": {
                                        "content": tool_result.content,
                                        "is_error": tool_result.is_error,
                                        "error_message": tool_result.error_message,
                                    },
                                },
                                websocket,
                            )

                    # Send completion message
                    await manager.send_message(
                        {
                            "type": "complete",
                            "token_usage": result.token_usage,
                            "cost": result.cost,
                            "duration": result.duration,
                        },
                        websocket,
                    )

                    await llm_provider.close()

                except Exception as e:
                    await manager.send_message({"type": "error", "content": str(e)}, websocket)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket)


async def _run_test_command(websocket: WebSocket, data: dict, config, send_log):
    """Execute a single 'run_test' command from the client.

    Extracted to module scope so it can be wrapped in an asyncio.Task and
    cancelled by `handle_test_websocket` when the user clicks Stop.
    Cooperative cancellation is honored at every `await` point.
    """
    test_path = Path(data.get("test_path", ""))
    test_name = data.get("test_name")
    model = data.get("model") or config.default_model
    provider = data.get("provider") or config.default_provider
    profile = data.get("profile")
    llm_profile_id = data.get("llm_profile")

    if not test_path.exists():
        await manager.send_message(
            {"type": "error", "message": f"Test file not found: {test_path}"},
            websocket,
        )
        return

    await send_log(f"📁 Loading test file: {test_path}")

    try:
        # Load test cases
        with open(test_path) as f:
            file_data = yaml.safe_load(f)

        test_cases = []
        if "tests" in file_data:
            for test_data in file_data["tests"]:
                test_cases.append(TestCase.from_dict(test_data))
        else:
            test_cases.append(TestCase.from_dict(file_data))

        # Check for suite-level provider override
        suite_provider = file_data.get("provider")
        suite_provider_config = file_data.get("provider_config", {})
        suite_model = file_data.get("model")

        effective_provider = suite_provider or provider
        effective_model = suite_model or model

        # Build the final provider_config. For assistant/chatbot we fold in
        # the assistant-specific fields (workspace_hash, domain, JWT auth,
        # path overrides) from the selected LLM profile in `.llm_providers.yaml`
        # — without these, AssistantProvider.__init__ raises ValueError. The
        # CLI accepts them as flags; the websocket has no flags so it must
        # pick them up from the profile config the user already maintains.
        # Precedence: explicit suite YAML `provider_config:` > LLM profile.
        effective_provider_config: dict[str, Any] = dict(suite_provider_config or {})
        if effective_provider in ("assistant", "chatbot") and llm_profile_id:
            from testmcpy.llm_profiles import load_llm_profile

            llm_profile = load_llm_profile(llm_profile_id)
            if llm_profile:
                # Prefer the entry in the profile whose `provider` matches the
                # one we're about to run; otherwise fall back to the profile
                # default. This handles the common pattern of an LLM profile
                # bundling several providers (e.g. claude-sdk + assistant) where
                # the suite YAML pins which one to use.
                assistant_entry = (
                    next(
                        (p for p in llm_profile.providers if p.provider == effective_provider),
                        None,
                    )
                    or llm_profile.get_default_provider()
                )
                if assistant_entry:
                    for fname in (
                        "workspace_hash",
                        "domain",
                        "api_token",
                        "api_secret",
                        "api_url",
                        "conversations_path",
                        "completions_path",
                    ):
                        val = getattr(assistant_entry, fname, None)
                        if val and not effective_provider_config.get(fname):
                            effective_provider_config[fname] = val

        # Filter to specific test if requested
        if test_name:
            test_cases = [tc for tc in test_cases if tc.name == test_name]
            if not test_cases:
                await manager.send_message(
                    {"type": "error", "message": f"Test '{test_name}' not found"},
                    websocket,
                )
                return

        await send_log(f"📋 Found {len(test_cases)} test(s) to run")
        await send_log(f"🤖 Provider: {effective_provider}, Model: {effective_model}")
        if suite_provider:
            await send_log(f"📝 Suite-level provider override: {suite_provider}")

        # Get MCP client - use profile or default
        mcp_client = None
        effective_profile = profile
        if not effective_profile:
            # Try to get default profile from config
            from testmcpy.server.helpers.mcp_config import load_mcp_yaml

            mcp_config = load_mcp_yaml()
            effective_profile = mcp_config.get("default")
            if effective_profile:
                await send_log(f"🔌 Using default MCP profile: {effective_profile}")

        if effective_profile:
            await send_log(f"🔌 Loading MCP profile: {effective_profile}")
            mcp_client = await get_or_create_mcp_client(effective_profile)
            if mcp_client is None:
                await manager.send_message(
                    {
                        "type": "error",
                        "message": (
                            f"MCP profile '{effective_profile}' not found. "
                            f"Check your MCP Profiles configuration."
                        ),
                    },
                    websocket,
                )
                return

        # Get MCP URL from the selected profile's client, not the default config
        effective_mcp_url = config.get_mcp_url()
        if mcp_client and hasattr(mcp_client, "base_url") and mcp_client.base_url:
            effective_mcp_url = mcp_client.base_url

        # MCP profile fallback for assistant/chatbot credentials.
        #
        # The CLI takes workspace_hash/domain/JWT via flags; the WebSocket
        # has no flag-equivalent. We've already tried the LLM profile —
        # if it didn't have an `assistant`/`chatbot` entry (very common —
        # most users' `.llm_providers.yaml` only lists Claude/OpenAI
        # providers), the merge above was a no-op and we'd otherwise crash
        # in AssistantProvider.__init__.
        #
        # The selected MCP profile already encodes which workspace we're
        # targeting, and Preset chatbot endpoints use the same JWT as the
        # MCP server, so deriving the missing fields from the MCP profile
        # is the correct path for the "run a chatbot eval from the UI"
        # flow. We never overwrite an explicit suite-YAML or LLM-profile
        # value — this is a last-resort fallback.
        if effective_provider in ("assistant", "chatbot") and mcp_client is not None:
            filled_from_mcp: list[str] = []
            ws_hash, domain = _derive_workspace_and_domain_from_mcp_url(effective_mcp_url)
            if ws_hash and not effective_provider_config.get("workspace_hash"):
                effective_provider_config["workspace_hash"] = ws_hash
                filled_from_mcp.append("workspace_hash")
            if domain and not effective_provider_config.get("domain"):
                effective_provider_config["domain"] = domain
                filled_from_mcp.append("domain")
            auth_cfg = getattr(mcp_client, "auth_config", None) or {}
            if isinstance(auth_cfg, dict) and auth_cfg.get("type") == "jwt":
                for src_key, dst_key in (
                    ("api_url", "api_url"),
                    ("api_token", "api_token"),
                    ("api_secret", "api_secret"),
                ):
                    val = auth_cfg.get(src_key)
                    if val and not effective_provider_config.get(dst_key):
                        effective_provider_config[dst_key] = val
                        filled_from_mcp.append(dst_key)
            if filled_from_mcp:
                await send_log(
                    f"🔑 Derived from MCP profile '{effective_profile}': "
                    f"{', '.join(filled_from_mcp)} "
                    "(add an `assistant` entry to .llm_providers.yaml to override)"
                )

        # Create runner with streaming log callback
        runner = TestRunner(
            model=effective_model,
            provider=effective_provider,
            mcp_url=effective_mcp_url,
            mcp_client=mcp_client,
            verbose=True,
            hide_tool_output=False,
            log_callback=send_log,
            provider_config=effective_provider_config,
            # We emit our own per-test "🧪 Running test … / 📝 Prompt / ⏱️ Timeout"
            # block below, so the runner must not also emit its own (would create
            # two collapsible test groups in the UI for every test).
            quiet_test_announcement=True,
        )

        await send_log("⚙️ Initializing test runner...")
        await runner.initialize()
        await send_log("✅ Test runner ready")

        # Run each test one at a time
        all_results = []
        for i, tc in enumerate(test_cases):
            await manager.send_message(
                {
                    "type": "test_start",
                    "test_name": tc.name,
                    "index": i,
                    "total": len(test_cases),
                },
                websocket,
            )

            await send_log(f"\n{'=' * 50}")
            await send_log(f"🧪 Running test {i + 1}/{len(test_cases)}: {tc.name}")
            await send_log(f"📝 Prompt: {tc.prompt}")
            await send_log(f"⏱️ Timeout: {tc.timeout}s")

            start_time = time.time()
            result = await runner.run_test(tc)
            elapsed = time.time() - start_time

            # Send logs from the result
            if hasattr(result, "logs") and result.logs:
                for log_line in result.logs:
                    await send_log(log_line)

            # Send test result
            status = "✅ PASSED" if result.passed else "❌ FAILED"
            await send_log(f"{status} in {elapsed:.2f}s")

            if result.tool_calls:
                await send_log(f"🔧 Tool calls: {len(result.tool_calls)}")
                for tc_call in result.tool_calls:
                    await send_log(f"   - {tc_call.get('name', 'unknown')}")

            if result.error:
                await send_log(f"⚠️ Error: {result.error}")

            await manager.send_message(
                {
                    "type": "test_complete",
                    "test_name": tc.name,
                    "result": result.to_dict(),
                },
                websocket,
            )

            all_results.append(result)

        # Send final summary
        passed = sum(1 for r in all_results if r.passed)
        failed = len(all_results) - passed
        total_cost = sum(r.cost for r in all_results)

        await send_log(f"\n{'=' * 50}")
        await send_log(f"📊 SUMMARY: {passed} passed, {failed} failed")
        if total_cost > 0:
            await send_log(f"💰 Total cost: ${total_cost:.4f}")

        results_list = [r.to_dict() for r in all_results]
        summary = {
            "total": len(all_results),
            "passed": passed,
            "failed": failed,
            "total_cost": total_cost,
        }

        # Save results to history
        try:
            from testmcpy.server.routers.results import save_test_run_to_file
            from testmcpy.server.routers.tests import _extra_tests_dirs

            # Derive a stable history label. Prefer the relative path
            # under <cwd>/tests (or any TESTMCPY_EXTRA_TESTS_DIRS root,
            # namespaced under that root's basename) so two external
            # suites that happen to share a YAML basename — e.g.
            # `foo/C01.yaml` and `bar/C01.yaml` — get distinct history
            # entries instead of colliding on `C01.yaml`.
            tests_dir = Path.cwd() / "tests"
            test_file_name = test_path.name
            try:
                resolved_test_path = test_path.resolve()
                if resolved_test_path.is_relative_to(tests_dir.resolve()):
                    test_file_name = str(resolved_test_path.relative_to(tests_dir.resolve()))
                else:
                    for extra_root in _extra_tests_dirs():
                        extra_real = extra_root.resolve()
                        if resolved_test_path.is_relative_to(extra_real):
                            test_file_name = (
                                f"{extra_root.name}/{resolved_test_path.relative_to(extra_real)}"
                            )
                            break
            except OSError:
                # resolve() failed (broken symlink, etc.) — fall back to
                # the basename rather than crashing the save.
                pass

            save_data = {
                "test_file": test_file_name,
                "test_file_path": str(test_path),
                "provider": provider,
                "model": model,
                "mcp_profile": effective_profile,
                "results": results_list,
                "summary": summary,
            }
            save_result = save_test_run_to_file(save_data)
            await send_log(f"💾 Results saved: {save_result.get('run_id')}")
        except Exception as save_err:
            await send_log(f"⚠️ Failed to save results: {save_err}")

        await manager.send_message(
            {
                "type": "all_complete",
                "summary": summary,
                "results": results_list,
            },
            websocket,
        )

    except asyncio.CancelledError:
        # Stopped by user — let the caller emit the user-facing message.
        raise
    except Exception as e:
        import traceback

        tb = traceback.format_exc()
        try:
            await send_log(f"❌ Error: {str(e)}")
            await send_log(f"Traceback:\n{tb}")
            await manager.send_message(
                {"type": "error", "message": str(e), "traceback": tb},
                websocket,
            )
        except Exception:
            # Socket may already be closed (client disconnected mid-run)
            pass


async def handle_test_websocket(websocket: WebSocket):
    """
    Handle WebSocket for streaming test execution with real-time logs.

    Message format from client:
    {
        "type": "run_test",
        "test_path": "/path/to/test.yaml",
        "test_name": "optional_specific_test",
        "model": "claude-sonnet-4-20250514",
        "provider": "claude-cli",
        "profile": "mcp_profile_id"
    }

    Or:
    { "type": "stop" }   # cancel the in-flight run

    Message format to client:
    {
        "type": "log" | "test_start" | "test_complete" | "all_complete" | "error",
        "message": "...",
        "test_name": "...",
        "result": {...}
    }
    """
    await manager.connect(websocket)
    config = get_config()

    async def send_log(msg: str):
        """Send a log message to the client (best-effort)."""
        try:
            await manager.send_message({"type": "log", "message": msg}, websocket)
        except Exception:
            # Socket closed underneath us — drop the message.
            pass

    async def _watch_for_stop():
        """Block until the client sends a 'stop' message.

        Raises WebSocketDisconnect if the client disconnects.
        """
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "stop":
                return

    try:
        while True:
            data = await websocket.receive_json()

            if data.get("type") != "run_test":
                continue

            run_task = asyncio.create_task(_run_test_command(websocket, data, config, send_log))
            stop_task = asyncio.create_task(_watch_for_stop())

            done, _pending = await asyncio.wait(
                {run_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if stop_task in done:
                # Either client sent {"type": "stop"} or disconnected.
                stop_exc = stop_task.exception()
                run_task.cancel()
                try:
                    await run_task
                except (asyncio.CancelledError, Exception):
                    pass
                if stop_exc is not None:
                    # Disconnect (or other recv failure) — propagate to outer handler.
                    raise stop_exc
                await send_log("🛑 Test run stopped by user")
            else:
                # Run finished naturally — cancel the stop watcher so we can
                # re-enter the outer receive loop for the next command.
                stop_task.cancel()
                try:
                    await stop_task
                except (asyncio.CancelledError, Exception):
                    pass

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"Test WebSocket error: {e}")
        manager.disconnect(websocket)
