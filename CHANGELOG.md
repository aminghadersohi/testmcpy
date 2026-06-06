# Changelog

All notable changes to testmcpy will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.13] - 2026-06-06

### Added
- **Run All directory button** in the Tests tab sidebar: each folder header now
  shows a hover-reveal play button that sequentially runs every test file in
  that folder using the same LLM/MCP profile as the single-file run. A
  spinner badge shows `N/M` progress while running; a summary alert reports
  pass/fail when complete.
- **Multi-select delete for history runs** in the Tests tab history panel:
  a "Select" toggle enters multi-select mode with per-row checkboxes, a
  "Select All" header checkbox, and a "Delete N" button that calls
  `POST /api/results/runs/bulk-delete` and removes the deleted entries from
  the history list.

### Fixed
- **Bottom panel tab bar coverage**: the Logs/Results tab bar is now
  `sticky top-0 z-10` so it cannot be scrolled out of view when the panel
  is small.
- **Minimum panel height** reduced from 120px to 80px so the tab bar is
  always fully visible with content below it.

## [0.7.12] - 2026-06-06

### Fixed
- **`OperationalError: table question_results has no column named tool_call_counts`**:
  `TestStorage.__init__()` now calls `_apply_column_migrations()` after
  `create_all()`. This method inspects `PRAGMA table_info` for each table and
  issues `ALTER TABLE … ADD COLUMN` for any column that is missing, making the
  migration automatic and idempotent. Covers `tool_call_counts`, `false_positive_rate`
  (added in v0.7.10), and `total_cost` (added in v0.7.7) for existing DB files
  that predate those releases.

## [0.7.11] - 2026-06-06

### Added
- **Mass delete for test results**: the `/reports` left panel now has a
  "Select" button that enters multi-select mode. Each run gets a checkbox;
  a sticky toolbar shows a "Select all" checkbox, the count of selected items,
  and a red "Delete N" button. Confirming sends a single
  `POST /api/results/runs/bulk-delete` request. Cancelling exits select mode
  without touching data. The single per-row trash icon is hidden while in
  select mode to avoid accidental single deletes.

## [0.7.10] - 2026-06-06

### Added
- **Tool call breakdown + false positive rate** per question result: `tool_call_counts`
  (`{tool_name: count}`) and `false_positive_rate` (0–1) are now computed in
  `save_question_result()`, stored in two new `question_results` columns
  (Alembic migration included), returned by the API, and displayed in the
  `TestResultPanel` UI after the tool-calls list.
- **Score penalty** for unnecessary extra calls: score is multiplied by
  `max(0.5, 1 - false_positive_rate)` unless the `unnecessary_tool_calls`
  evaluator already penalised the result.

### Fixed
- **`MarkupError` crash** when LLM response contains URL-like brackets (e.g.
  `/superset/dashboard/preset-prod/`): `run.py` now imports `escape` from
  `rich.markup` and wraps `result.reason`, `result.error`, and
  `result.error_message` before passing them to `console.print` /
  `table.add_row`.

## [0.7.9] - 2026-06-06

### Fixed
- **`/reports` page shows `$0.00` for all runs**: `GET /api/results/run/{run_id}`
  in `results.py` had two hardcoded `0.0` literals — one for `metadata.total_cost`
  and one for each per-result `cost`. Both now read from the DB values:
  `run["summary"]["total_cost_usd"]` and `qr["cost_usd"]` respectively.

## [0.7.8] - 2026-06-06

### Added
- **Exponential back-off for unavailable MCP servers**: when a connection or
  `list_tools()` call fails, the server now waits before retrying — 5 s, 10 s,
  20 s, 40 s … capped at 5 minutes. Previously the UI's polling caused a fresh
  (expensive) connection attempt on every request, flooding the logs and
  hammering a dead server. Back-off state is tracked per
  `{profile_id}:{mcp_name}` key; a successful connection resets it. Client
  evictions (after use-time errors) also trigger back-off so reconnects are
  throttled in that path too.

## [0.7.7] - 2026-06-06

### Fixed
- **OAuth generator lock crash** (`RuntimeError: The current task is not holding
  this lock`): `MCPClient.list_tools()` now uses `asyncio.timeout` on Python
  3.11+ instead of `asyncio.wait_for`. The new form runs the coroutine in the
  current task so `CancelledError` unwinds the FastMCP auth generator's
  `async with lock:` block in the correct task context, preventing the anyio
  lock from being released by a GC finaliser task that doesn't own it. A custom
  event-loop exception handler suppresses the residual noise on Python 3.10.
- **Broken cached client not evicted**: `list_mcp_tools()` now evicts the cached
  `MCPClient` on *any* error, not only connection errors. Previously a failed
  `list_tools()` call left the broken client in the in-memory cache, causing
  every subsequent request to the same profile to 500.
- **`is_connection_error` too narrow**: extended to match
  `"failed to connect"`, `"failed to initialize"`, and `"timed out"` substrings
  so MCPConnectionError and MCPTimeoutError messages correctly surface as 503.
- **Cost always `$0.00` in UI**: `storage.complete_run()` now sums
  `question_results.cost_usd` into `test_runs.total_cost` alongside the
  existing `total_tokens` rollup. Per-question costs were already stored
  correctly; they just were never aggregated to the run level.

## [0.7.6] - 2026-06-06

### Added
- **Sidecar JSON after every `testmcpy run`**: results are now also written to
  `tests/.results/<run_id>.json` in addition to the SQLite DB. The file is
  created atomically (write to `.tmp` then rename) and the directory is
  created if it doesn't exist. Structure: `run_id`, `test_file`, `provider`,
  `model`, `mcp_profile`, `summary` (total/passed/failed/score), `results`.

## [0.7.5] - 2026-05-28

### Fixed
- **`ClaudeSDKProvider` system prompt**: removed "search/discover tools if
  needed" guidance that caused `claude-sonnet-4-6` to call `search_tools`
  before every tool execution. On PROD the gateway returns a 107k-char
  response that exhausts the session context. System prompt now explicitly
  bans `search_tools` and any `authenticate` tool call. Fixes the chronic
  file-14 NOT COMPLETED, ghost-authenticate on file-07 (sc-106500), and
  widespread `was_tool_called` failures seen in eval cycles c39/c40.
- **Default model** updated from retired `claude-sonnet-4-20250514` to
  `claude-sonnet-4-6` in `MCPClientRunner`, `AnthropicDirectRunner`, and
  `LLMJudge`. The old model ID is retained in the registry but marked
  `is_deprecated=True`.

## [0.7.4] - 2026-05-21

### Added
- **Progressive checkpoint saves** in `testmcpy run`. After every
  test completes, partial results are written to
  `tests/.results/.checkpoints/<session_id>.json` (atomic
  write-then-replace). If the run is killed mid-stream (OOM, ctrl-C,
  parent harness timeout), the harness can still recover what
  finished without rerunning the suite. Surfaced in eval cycle c33
  (SC-107284) where long suites died mid-run with no recoverable
  state.
- **`.done` sentinel file** written immediately after the run summary
  prints, before optional post-processing (DB save, report
  generation). The sentinel lets a parent harness treat the run as
  finished even if a later step hangs or fails. Sentinel path:
  `tests/.results/.checkpoints/<session_id>.done`.

### Changed
- `MCPClient._expand_gateway_tools()` now caps total chars collected
  across all `search_tools` discovery queries at 200k. Prevents
  memory / context blowup against MCP servers that inline very large
  tool schemas in their gateway responses. Truncation is
  per-response and the loop short-circuits once the cap is reached.

## [0.7.3] - 2026-05-08

### Added
- **Per-call wall-clock guard** in `AssistantProvider.generate_with_tools()`.
  `PER_CALL_WALL_CLOCK_SECONDS` (default 180s) is a hard ceiling on
  the SSE consumption — it fires even when bytes ARE flowing, just
  slowly. Distinct from the existing idle-abort: idle = "no progress
  at all", wall-clock = "any progress, but too slow overall". Time
  spent waiting for the concurrency-limit semaphore (see below) is
  NOT counted against this budget. The agor parallel-cycle harness
  was hitting this case across c28-c32 (SC-106138) where bytes kept
  flowing but the call took 5+ minutes. Wall-clock-aborted calls
  surface a clean error string in `LLMResult.response` and tag the
  Done log with `[SSE wall-clock aborted]`.
- **SSE heartbeat log lines** every `HEARTBEAT_SECONDS` (default 10s)
  while the stream is open: `[Assistant] still streaming … 30s
  elapsed, 12 events, 5s since last event`. Lets a parent harness
  distinguish a slow-but-progressing child from a wedged one without
  parsing every SSE event.
- **`--max-concurrent-streams` CLI flag** on `testmcpy run` for the
  assistant/chatbot provider. Class-level `asyncio.Semaphore` capped
  at the configured limit; held for the entire SSE consumption so
  the cap really does limit parallel streams. Lazy-allocated inside
  the running event loop on first use (so the semaphore binds
  correctly under pytest-asyncio and other multi-loop setups). Use
  this when a parent harness fans out many testmcpy children at
  once and the chatbot endpoint stalls under load.
- Unit tests in `unit_tests/test_assistant_sse_concurrency_and_walls.py`:
  per-call wall-clock fires against a chatty stream, heartbeats appear,
  semaphore serialises concurrent streams, semaphore is unbounded
  when unset, configure idempotency.

### Changed
- `AssistantProvider.generate_with_tools()` now distinguishes
  "request start" (`start_time`, used for `LLMResult.duration`) from
  "stream consumption start" (`stream_start_time`, used for the
  per-call wall-clock budget). When a semaphore wait happens, only
  the request start moves earlier — the stream budget is preserved.

## [0.7.2] - 2026-05-06

### Added
- **SSE idle-abort defense** in `AssistantProvider.generate_with_tools()`.
  If the chatbot SSE stream emits no recognized event for
  `SSE_IDLE_ABORT_SECONDS` (default 90s) the provider closes the
  connection and returns an explanatory error in `LLMResult.response`.
  This complements the v0.7.1 per-test wall-clock timeout: the
  wall-clock fires *between* tests, but a stalled SSE stream that
  keeps the TCP connection open (httpx's per-event read timeout never
  fires because no event has been received *yet*) could hang inside a
  single test indefinitely. Observed in eval cycle c29 (SC-105915)
  where C00_9, C01_9, and C02_7 hung against the chatbot backend
  despite v0.7.1 being deployed. The threshold is a class attribute
  so subclasses / tests can override it.
- Unit test in `unit_tests/test_assistant_sse_idle_abort.py` exercising
  the idle-abort path with a fake SSE stream that opens, sends one
  event, then goes silent.

## [0.7.1] - 2026-05-06

### Added
- **Per-test wall-clock timeout** in `TestRunner._run_test_with_retry`.
  Each test is now wrapped in `asyncio.wait_for(...)` with a budget of
  `test_case.timeout + WALL_CLOCK_SLACK_SECONDS` (60s default; CLI
  providers also get the existing 120s floor on the per-call timeout).
  Without this, providers that stream events — notably the
  `AssistantProvider` chatbot endpoint — could keep a test alive
  indefinitely because the per-event httpx timeout resets on every
  received chunk. Observed in eval cycle c28 (SC-105726): the chatbot
  hung 15+ minutes on `add_chart_to_existing_dashboard` against a
  nonexistent chart, never closing the SSE stream. The wall-clock
  guard breaks out of these.
- **Per-tool-call retry budget** in `ClaudeSDKProvider`. Tracks each
  `(tool_name, args, error_text_prefix)` signature; if the same call
  produces the same error 3× in a row the query aborts with a clear
  diagnostic in the response (and a `[retry budget aborted]` marker in
  the logs). Observed in c28: the model kept calling `execute_sql` with
  `query=...` instead of `sql=...`, hitting the same 3 validation
  errors each turn until the runner was killed externally.
- 3 new unit tests in `unit_tests/test_runner_wall_clock_timeout.py`:
  hung-test abort, happy-path passthrough, CLI 120s floor.

### Changed
- `WALL_CLOCK_SLACK_SECONDS` is a class-level attribute on `TestRunner`
  (default 60.0s) so it can be overridden in tests or via subclassing.

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
