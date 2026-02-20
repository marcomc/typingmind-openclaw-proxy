# Changelog

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
