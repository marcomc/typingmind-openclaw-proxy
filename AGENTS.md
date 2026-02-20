# AGENTS.md

## Mission

Maintain `typingmind-openclaw-proxy` as a minimal, public-safe compatibility layer between TypingMind and native OpenClaw.

## Non-Negotiable Rules

- Never commit secrets, tokens, or personal identifiers.
- Never include personal environment details in project content (for example: home paths, usernames, machine-specific absolute paths, or real credential values). Redact or replace with placeholders.
- Keep behavior OpenAI-compatible for TypingMind test/save flows.
- Keep operational commands deterministic and copy/paste ready.
- Prefer small, reviewable changes.

## Required Workflow For Every Change

1. Update implementation.
2. Validate locally:
   - `make status`
   - `curl http://127.0.0.1:17890/v1`
   - `curl http://127.0.0.1:17890/v1/models`
3. Update docs:
   - `CHANGELOG.md`
   - `TODO.md`
4. Run markdown lint for all changed markdown files:
   - `markdownlint --fix *.md`
   - `markdownlint *.md`

## Scope

- In scope:
  - Proxy compatibility endpoints and forwarding logic.
  - LaunchAgent install/run lifecycle.
  - Public-safe operational documentation.
- Out of scope:
  - OpenClaw channel configuration.
  - Storing or documenting live credentials.
