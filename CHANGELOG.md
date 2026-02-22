# Changelog

## [Unreleased]

### Changed

- Added optional proxy-side generation guardrails that cap oversized `max_tokens` / `max_completion_tokens` requests with `OPENCLAW_PROXY_MAX_UPSTREAM_TOKENS` (default `0` = disabled).
- Added TypingMind-safe model ID aliasing for `/v1/models` (default on), plus reverse alias resolution on `/v1/chat/completions`, including friendly IDs like `openclaw:gpt-5-1` for known OpenClaw models.
- Added optional model-routing debug logs (`OPENCLAW_PROXY_DEBUG_MODEL_ROUTING`, default `1`) to print requested/decoded/forwarded model IDs for each chat request.
- Normalized incoming request paths (including URL-encoded newline variants) before endpoint matching for better client compatibility.
- Hardened streaming/non-stream response writes to tolerate client disconnects without broken-pipe error cascades and retry noise.
- Added streaming compatibility fallback: when upstream sends `data: [DONE]` without a terminal `finish_reason: "stop"` chunk, proxy now injects a synthetic stop chunk before `[DONE]`.
- Fixed SSE stream framing for synthetic stop injection by parsing complete SSE events before inspection/emission, preventing malformed interleaving that could trigger JSON parse errors in OpenCode clients.
- Updated `GET /v1/models` discovery flow to use OpenClaw upstream `/v1/models` when available, then fallback to `openclaw models list --json`, then fallback to default local model metadata.
- Added `make smoke-models-parity` to verify model ID parity between proxy `/v1/models` and `openclaw models list --json`.
- Standardized backlog workflow: completed TODO items are logged in `Unreleased` and removed from `TODO.md` unless they must remain as completed child tasks under a still-open parent.
- Moved completed TODO item `Add automated make smoke-keywords coverage for all escalation keyword aliases.` out of `TODO.md` and tracked completion here.
- Simplified proxy escalation keywords by removing `!spark` compatibility and keeping `!fast` mapped to `openai-codex/gpt-5.1`.
- Updated keyword smoke tests and README keyword mapping docs to match the new routing.
- Added `make list-keywords` to print supported escalation keyword aliases and their mapped upstream models without running network smoke requests.
- Added chat-level keyword help interception: `!keywords` (and aliases `!keyword`, `!switches`, `!models`) now returns the live keyword map directly from the proxy without upstream forwarding.
- Fixed keyword-help interception to honor `OPENCLAW_PROXY_ESCALATION_KEYWORDS_ENABLED=0` so disable mode is a true upstream pass-through.
- Removed tracked Python bytecode artifact from `__pycache__/` and added repository ignore rules for Python cache files.

### Implemented Features

- Added `make smoke-keywords` to validate all supported escalation keyword aliases against expected upstream model IDs.
- Added `smoke-keywords` to `make help` output for discoverability.

## [0.1.0] - 2026-02-20

### Implemented Features

- OpenAI-compatible proxy endpoints for TypingMind interoperability:
  - `GET /v1`
  - `GET /v1/models`
  - `POST /v1`
  - `POST /v1/chat/completions`
- Operational endpoint for local readiness checks: `GET /health`.
- Streaming chat-completions passthrough with incremental SSE relay and clean completion handling.
- TypingMind save/test compatibility behavior: proxy returns a valid success envelope for minimal/invalid test payloads so model save flows succeed.
- LaunchAgent-based local service lifecycle via `Makefile` (`install`, `start`, `stop`, `restart`, `status`, `logs`, `uninstall`).
- Additional operational `Makefile` tooling: `help`, `smoke`, `launchctl-diagnostics`, and Cloudflare tunnel lifecycle commands.
- Token-authenticated upstream forwarding to local OpenClaw gateway.
- Optional static proxy API key guard for client-side bearer validation, with key management helpers (`print-static-api-key`, `rotate-static-api-key`, guard enable/disable targets).
- CORS headers for browser/app compatibility on API and preflight responses.
- Smoke and health validation commands, including endpoint checks for `/v1`, `/v1/models`, and `/v1/chat/completions`.
- Cloudflare tunnel support for public HTTPS access:
  - ad-hoc quick tunnel mode,
  - persistent token-managed tunnel mode,
  - optional system-wide cloudflared service install path.
- Template-driven service/tunnel launch scripts and plist generation for deterministic local installs.
- Public-safe operational documentation covering setup, verification, tunnel lifecycle, diagnostics, and command reference.
- Governance and release-readiness assets: `AGENTS.md`, `TODO.md`, and MIT `LICENSE`.
- CI markdown lint workflow for repository Markdown files.
- Initial public release administrative step tracked as complete: release tag and public repository metadata.
