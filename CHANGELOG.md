# Changelog

All notable changes to testmcpy will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.0] - 2026-05-05

### Changed
- `AssistantProvider` is now a vendor-neutral chatbot client. The class
  docstring documents the protocol contract it expects (JWT auth →
  conversation create → SSE completions stream with `token` /
  `tool_call` / `tool_result` / `usage` / `final` / `error` events).
  No vendor-specific class names, paths, or branding live in the
  source. To target a vendor that diverges from the contract, subclass
  and override one of the hooks: `_authenticate`, `_open_conversation`,
  `_build_headers`, `_build_completions_payload`, `_handle_sse_event`.
- The SSE-loop's mutable state is factored into a `_SSEStreamState`
  dataclass so subclasses can replace event handling without
  re-implementing the loop.

### Added
- CLI flags `--assistant-conversations-path` and
  `--assistant-completions-path` so users can override the endpoint
  paths without subclassing (e.g., to target a different chatbot
  backend). Both are optional; if omitted, the provider's
  `_DEFAULT_CONVERSATIONS_PATH` / `_DEFAULT_COMPLETIONS_PATH` are
  used.
- `TestRunner.initialize()` and per-test loops skip MCP client init
  + `list_tools()` for the `assistant` / `chatbot` providers — the
  chatbot endpoint owns its tool registry server-side. (Folds in the
  fix from PR #51.)

### Fixed
- Internal session-token attribute renamed `_jwt_token` → `_session_token`
  for consistency with the vendor-neutral framing. Callers that poked
  at the old name need to be updated (caught one in
  `unit_tests/test_assistant_provider.py`).

## [0.6.2] - 2026-05-05

### Fixed
- `testmcpy run --provider assistant` (or `chatbot`) no longer
  initializes a local MCP client. The assistant endpoint talks to
  MCP server-side, so the local runner shouldn't be opening an MCP
  connection — doing so was triggering an unwanted OAuth flow against
  the workspace's MCP URL and loading auth from `.mcp_services.yaml`
  that the user hadn't asked for. Patched in three places:
  the CLI (`run.py`), `TestRunner.initialize()`, and the inner
  per-test loops that previously called `mcp_client.list_tools()`.
  For the assistant/chatbot providers, no local tool discovery is
  performed — the chatbot endpoint owns the tool registry server-side.
- `AssistantProvider` now returns `tool_results` as a list of
  `MCPToolResult` objects (matching `ClaudeSDKProvider`), instead of
  raw dicts. The previous shape caused evaluators to fail with
  `'dict' object has no attribute 'is_error'` on every test.

## [0.6.1] - 2026-05-05

### Added
- Dedicated `--assistant-api-url` / `--assistant-api-token` /
  `--assistant-api-secret` CLI flags so MCP and the assistant
  endpoint can use different JWT credentials in the same command.
  The MCP `--jwt-*` flags are still accepted as a fallback for
  shared-cred setups.
- `assistant` and `chatbot` are now valid values for `--provider`
  (added to the `ModelProvider` enum so typer accepts them).
- `OPENROUTER_API_KEY`, `XAI_API_KEY`, `GOOGLE_API_KEY`, and
  `GEMINI_API_KEY` are now recognized in `~/.testmcpy` and `./.env`
  (added to `Config.GENERIC_KEYS`).

### Fixed
- `AssistantProvider.initialize()` validation error messages now
  point users at the new CLI flags / config files instead of the
  removed `ASSISTANT_*` env vars.

## [0.6.0] - 2026-05-05

### Changed (BREAKING)
- testmcpy code no longer reads environment variables directly. Credentials
  and provider configuration must come from CLI flags, the YAML config
  files (`.mcp_services.yaml` / `.llm_providers.yaml`, which support
  `${VAR}` substitution at load time), or the env-format config files
  (`~/.testmcpy` / `./.env`). Specifically:
  - `AssistantProvider` no longer reads `ASSISTANT_WORKSPACE_HASH`,
    `ASSISTANT_DOMAIN`, `ASSISTANT_ENVIRONMENT`, `ASSISTANT_API_TOKEN`,
    `ASSISTANT_API_SECRET`, `ASSISTANT_API_URL` from the environment.
    Pass them via CLI flags (`--workspace-hash`, `--domain`,
    `--environment`, `--jwt-url`, `--jwt-token`, `--jwt-secret`) or
    via `provider_config` on the Python API.
  - `OpenRouterProvider` and `XAIProvider` no longer fall back to
    `OPENROUTER_API_KEY` / `XAI_API_KEY` env vars. Configure via
    `.llm_providers.yaml` `${VAR}` substitution.
  - `AnthropicRunnerTool` no longer falls back to `ANTHROPIC_API_KEY`.
  - `LLMAsJudgeEvaluator` no longer reads `ANTHROPIC_API_KEY`,
    `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `GEMINI_API_KEY` directly.
  - `Config._load_config` no longer reads `GENERIC_KEYS` /
    `TESTMCPY_KEYS` from the environment. The `~/.testmcpy` and `./.env`
    file paths are still loaded as before.
  - The `envvar=` kwargs were removed from CLI flags `--auth-token`,
    `--jwt-url`, `--jwt-token`, `--jwt-secret` so they no longer pick up
    `MCP_AUTH_TOKEN` / `MCP_JWT_*` from the environment.

### Added
- CLI flags `--workspace-hash`, `--domain`, `--environment`,
  `--assistant-api-url`, `--assistant-api-token`,
  `--assistant-api-secret` on `testmcpy run` to configure the
  assistant/chatbot provider without env vars. The MCP `--jwt-*`
  flags are also accepted as a fallback when MCP and assistant share
  the same JWT credentials.
- `assistant` and `chatbot` are now valid values for `--provider`
  (added to the `ModelProvider` enum).
- `OPENROUTER_API_KEY`, `XAI_API_KEY`, `GOOGLE_API_KEY`, and
  `GEMINI_API_KEY` are now recognized in the `~/.testmcpy` and
  `./.env` env-format config files (added to `Config.GENERIC_KEYS`).
- CLI flag values for `assistant` / `chatbot` providers are folded into
  `provider_config` and reach `AssistantProvider.__init__` via
  `create_llm_provider`'s kwarg filtering.

## [0.5.1] - 2026-05-04

### Changed
- `ExecutionSuccessful` evaluator now ignores SDK-internal recovery errors that
  the model triggers when a tool result exceeds the SDK token limit and is
  saved to a file. Specifically: errors matching `Server "file-system" not
  found` / `Server "file" not found` are skipped, and `ReadMcpResourceTool`
  is treated as a blocked tool (its failures don't count against the test).
- `MCPToolResult` now carries the `tool_name` so evaluators can match against
  the tool name directly instead of inferring from the `tool_call_id`.

## [0.5.0]

### Added
- Docker Compose configuration for containerized deployment
- MCP service profiles (`mcp_services.yaml`) with local profile
- LLM provider profiles (`llm_providers.yaml`) with Claude and GPT-4o defaults
- Pre-commit hook to prevent Preset infrastructure URLs from leaking into the repo

### Changed
- Renamed `PresetOAuth` to `MCPOAuth` (back-compat alias preserved)
- Genericized `.mcp_services.yaml.example` with `example.com` placeholder URLs
- `AssistantProvider` domain mappings are now empty by default (set via env vars)

### Removed
- Preset infrastructure URLs from code and config (`preset.io`, `preset.zone`)
- `PRESET_*` environment variable fallbacks from `AssistantProvider`
- Preset sandbox/staging profiles from committed `mcp_services.yaml`
- `SANDBOX_API_*`/`STAGING_API_*` env vars from `docker-compose.yml`

---

## [0.2.17] - 2025-12-19

### Added
- Verbose progress output for `testmcpy run` CLI command showing test-by-test progress
- Real-time PASS/FAIL status, score, and duration for each test as it completes
- Spinner animation while tests are executing

---

## [0.2.16] - 2025-12-19

### Fixed
- Skip hidden directories (`.results/`, `.smoke_reports/`) when recursively discovering test files
- Only load files with valid test structure (`prompt` or `tests` key) to avoid loading result files

---

## [0.2.15] - 2025-12-18

### Fixed
- Fixed `testmcpy run <directory>` to recursively find test files in subdirectories using `rglob`
- Added support for `.yml` extension and `.json` files in directory test discovery
- Handle single test case files (without `tests` key) when loading from directories

---

## [0.2.14] - 2025-12-18

### Fixed
- Fixed `create_llm_provider` passing unsupported kwargs (like `auth`) to providers that don't accept them

---

## [0.2.13] - 2025-12-18

### Added
- Environment variable substitution in `.llm_providers.yaml` using `${VAR}` and `${VAR:-default}` syntax
- Comprehensive unit test suite (428 tests) covering config, evaluators, formatters, profiles, smoke tests, and YAML parsing

### Fixed
- Python 3.10 compatibility with Typer by using `Optional[X]` instead of `X | None` syntax
- CI workflow now correctly runs tests from `unit_tests/` directory

### Changed
- Removed MCP Tests workflow (tests folder is gitignored for runtime-generated tests)

---

## [0.1.1] - 2025-01-16

### Added
- **Multi-layer configuration system** with clear priority ordering:
  1. Command-line options (highest)
  2. `.env` in current directory
  3. `~/.testmcpy` user config file
  4. Environment variables
  5. Built-in defaults (lowest)

- **Dynamic JWT token generation** for MCP services:
  - Configure `MCP_AUTH_API_URL`, `MCP_AUTH_API_TOKEN`, `MCP_AUTH_API_SECRET`
  - Automatically fetches and caches JWT tokens for 50 minutes
  - Eliminates need to manually manage short-lived JWT tokens

- **`testmcpy config-cmd` command** to view current configuration:
  - Shows all config values with their sources
  - Masks sensitive values (API keys, tokens)
  - Displays config file locations and existence

- **`.testmcpy.example`** - Comprehensive example configuration file with detailed comments

### Changed
- **Removed default provider/model** assumptions:
  - No longer defaults to Ollama (which requires local setup)
  - CLI now defaults to Anthropic if not configured
  - Users must explicitly configure their preferred provider in `~/.testmcpy`

- **Updated README** with:
  - Detailed configuration documentation
  - Provider setup instructions (Anthropic, Ollama, OpenAI)
  - Authentication options (static token vs dynamic JWT)
  - Clear recommendations for each provider

- **Integrated config system** into:
  - `testmcpy.cli` - All commands now use Config class
  - `testmcpy.src.mcp_client` - MCPClient uses config for URL and auth

### Fixed
- Config priority now correctly handles generic keys (ANTHROPIC_API_KEY) vs testmcpy-specific keys
- Environment variables properly fall back for generic keys while being overridden for testmcpy keys

## [0.1.0] - 2025-01-15

### Added
- Initial release of testmcpy as installable Python package
- CLI with 6 commands: `research`, `run`, `tools`, `report`, `chat`, `init`
- Support for multiple LLM providers: Anthropic, Ollama, OpenAI, Claude SDK
- MCP client with FastMCP integration
- Test runner with YAML/JSON test definitions
- Rich terminal output with beautiful formatting
- PyPI and Homebrew distribution support
