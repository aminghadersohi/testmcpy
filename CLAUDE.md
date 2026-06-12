# testmcpy Project Instructions

## Critical Rules

### Git Commits
**IMPORTANT: Every code change MUST be followed by a git commit immediately.**
- Do not batch multiple features into one commit
- Commit after each logical change
- Use descriptive commit messages with prefixes: `fix:`, `feat:`, `chore:`
- This prevents losing work and makes it easy to revert if needed

### Do Not Delete Features
- Never remove existing functionality without explicit permission
- When adding new features, keep existing ones intact
- If refactoring, ensure all existing features still work

## Project Structure

- `testmcpy/ui/src/` - React frontend
- `testmcpy/server/` - FastAPI backend
- `testmcpy/src/` - Core test runner logic
- `tests/` - Test files and results storage
  - `.results/` - Test run history
  - `.smoke_reports/` - Smoke test reports
  - `.generation_logs/` - AI test generation logs

## UI Pages

- `/` - MCP Explorer (smoke tests, tool exploration)
- `/tests` - Test Manager (run YAML tests, view history)
- `/reports` - Combined Reports (all test results in one place)
- `/generation-history` - AI test generation history
- `/chat` - Interactive chat with MCP tools
- `/auth-debugger` - Authentication debugging
- `/config` - Configuration settings
- `/mcp-profiles` - MCP server profiles
- `/llm-profiles` - LLM provider profiles

## Development

Always run `npm run build` in `testmcpy/ui/` after frontend changes.

## Documentation Site

- `docs-site/` is a Nextra 3 (Next.js 14, npm) static site published to
  https://preset-io.github.io/testmcpy by `.github/workflows/deploy-docs.yml`
  on pushes to main; PRs touching it are build-checked by `docs-pr-check.yml`.
- Local dev: `cd docs-site && npm install && npm run dev` (port 3001).
- Production builds need `NEXT_PUBLIC_BASE_PATH=/testmcpy` (project pages
  basePath) — the workflows set it.
- Screenshots/logo are NOT duplicated: `scripts/sync-assets.mjs` copies them
  from `docs/screenshots/` and `docs/logos/` into `public/` at build time.
- `context/` stays the agent-facing source of truth. Docs pages adapted from
  it carry a `{/* Source: context/... — keep in sync */}` comment — when you
  edit one side, mirror the change on the other.

## No Preset Infrastructure URLs in Code

This is an open-source repo. Never add Preset-specific infrastructure URLs
(`*.preset.io`, `*.preset.zone`, `manage.app.*`, `testmcpy.sandbox.*`) to
committed code, configs, or examples. Use generic placeholders like
`example.com` instead. The pre-commit hook `no-preset-infra-urls` enforces
this — if it blocks your commit, replace the URL with a generic one.

Exceptions (OK to keep):
- GitHub repo URLs (`github.com/preset-io/testmcpy`)
- NOTICE/LICENSE copyright ("Preset, Inc.")
- docs/presentation.html and docs/talking_points.md (internal presentation materials)
