# typingmind-openclaw-proxy

Temporary OpenAI-compatible proxy that helps TypingMind interoperate with a native OpenClaw gateway.

## What it solves

- TypingMind test/save flows can call `GET /v1` and `POST /v1`.
- OpenClaw compatibility is strongest on `POST /v1/chat/completions`.
- This proxy serves compatibility endpoints and forwards valid chat requests to OpenClaw.

## Version compatibility matrix

The matrix below tracks known behavior by TypingMind client variant.

| TypingMind client/version | Status | Behavior summary | Required proxy mode |
| --- | --- | --- | --- |
| TypingMindMac desktop app (observed UA on 2026-02-19, macOS 26.3 build `25D125`) | Supported | Save/test flow works via `POST /v1`; chat works via `POST /v1/chat/completions`; streaming works with incremental chunks and clean `[DONE]`; image payloads are accepted but not processed as true vision in current ChatGPT Plus OAuth path. Use HTTPS endpoint in practice. | Default static guard (`STATIC_KEY_GUARD=1`) recommended. |
| TypingMind hosted web app (`setapp.typingcloud.com`) | Supported | Requires HTTPS endpoint; same chat/stream behavior as desktop path when routed through tunnel URL. | Default static guard (`STATIC_KEY_GUARD=1`) recommended. |
| Other TypingMind versions/builds | Untested | Treat as unknown until `make smoke` and an interactive save/test/chat check pass. | Start with default static guard, then adjust only if required. |

Validation baseline for each new TypingMind build:

```bash
make smoke BASE_URL=http://127.0.0.1:17890
make smoke BASE_URL=https://<TUNNEL_HOSTNAME>
```

## Prerequisites

- macOS
- OpenClaw gateway running locally on `127.0.0.1:18789`
- `python3`
- `openclaw` CLI in `PATH`

## Configure OpenClaw endpoint (required)

Apply the same native gateway baseline used in `openclaw-config` so TypingMind can reach OpenClaw through this proxy.

```bash
# enable OpenAI-compatible chat-completions endpoint
openclaw config set gateway.http.endpoints.chatCompletions.enabled true

# enforce token auth on gateway
openclaw config set gateway.auth.mode token

# if token is empty, generate one
openclaw doctor --generate-gateway-token

# restart gateway
openclaw gateway restart
```

## Quick install (LaunchAgent)

```bash
cd "$(git rev-parse --show-toplevel)"
make install
make status
```

Default listen port is `17890`.

## Verify after install

Run these checks only after `make install`.

Verify default proxy-auth flow (recommended):

```bash
cd "$(git rev-parse --show-toplevel)"
PROXY_KEY=$(make -s print-static-api-key | tail -n 1)

curl -sS -X POST http://127.0.0.1:17890/v1/chat/completions \
  -H "Authorization: Bearer $PROXY_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"openclaw:main","messages":[{"role":"user","content":"Reply OK"}],"stream":false}' \
  | jq -r '.object, .choices[0].message.content'
```

Expected:

- `chat.completion`
- `OK`

Optional legacy verification (only if static guard is disabled):

```bash
make disable-static-api-key-guard
GATEWAY_TOKEN=$(openclaw config get gateway.auth.token | tr -d '"')

curl -sS -X POST http://127.0.0.1:17890/v1/chat/completions \
  -H "Authorization: Bearer $GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"openclaw:main","messages":[{"role":"user","content":"Reply OK"}],"stream":false}' \
  | jq -r '.object, .choices[0].message.content'
```

Native gateway verification (diagnostic):

```bash
GATEWAY_TOKEN=$(openclaw config get gateway.auth.token | tr -d '"')
curl -sS -X POST http://127.0.0.1:18789/v1/chat/completions \
  -H "Authorization: Bearer $GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"openclaw:main","messages":[{"role":"user","content":"Reply OK"}],"stream":false}' \
  | jq -r '.model, .choices[0].message.content'
```

## Quick tunnel (non-persistent, no LaunchAgent)

Use this when you want a temporary external HTTPS URL without installing the named tunnel service.

```bash
cloudflared tunnel --url http://127.0.0.1:17890
```

Use the printed URL in TypingMind as:

- Endpoint URL: `https://<TRYCLOUDFLARE_URL>/v1`
- Model ID: `openclaw:main`

This URL changes every time you restart the command.

## Make command reference

### Proxy lifecycle

```bash
make help           # show all available commands with usage notes
make install        # render templates, install LaunchAgent, start proxy
make uninstall      # remove proxy LaunchAgent + launcher script (and tunnel agent if present)
make start          # start proxy LaunchAgent
make stop           # stop proxy LaunchAgent
make restart        # stop + reinstall proxy LaunchAgent
make status         # show launchctl status and listening port
make logs           # tail proxy log file
make health         # GET /health on local proxy
make smoke          # run /v1, /v1/models, /v1/chat/completions smoke checks
make launchctl-diagnostics  # print LaunchAgent diagnostics for proxy + tunnel
make print-static-api-key   # print proxy static API key for TypingMind bearer value
make rotate-static-api-key  # rotate proxy static API key and restart proxy LaunchAgent
make enable-static-api-key-guard   # enforce static bearer at proxy edge
make disable-static-api-key-guard  # legacy mode without proxy edge bearer check
make lint           # markdownlint --fix then markdownlint
```

### Tunnel lifecycle (user LaunchAgent, token-managed)

```bash
make install-cloudflare-tunnel \
  TUNNEL_TOKEN_FILE=~/.cloudflared/typingmind-openclaw-proxy.token \
  TUNNEL_HOSTNAME=<TUNNEL_HOSTNAME>
make uninstall-cloudflare-tunnel
make start-cloudflare-tunnel
make stop-cloudflare-tunnel
make restart-cloudflare-tunnel \
  TUNNEL_TOKEN_FILE=~/.cloudflared/typingmind-openclaw-proxy.token \
  TUNNEL_HOSTNAME=<TUNNEL_HOSTNAME>
make status-cloudflare-tunnel
make logs-cloudflare-tunnel
```

### Tunnel lifecycle (system service, optional)

```bash
make install-cloudflare-tunnel-system \
  TUNNEL_TOKEN_FILE=~/.cloudflared/typingmind-openclaw-proxy.token
make uninstall-cloudflare-tunnel-system
```

### Useful overrides

```bash
make install PORT=18080
make install STATIC_KEY_GUARD=1
make install STATIC_KEY_GUARD=0
make smoke BASE_URL=http://127.0.0.1:17890
make smoke BASE_URL=https://<TUNNEL_HOSTNAME>
make smoke SMOKE_MODEL=openclaw:main
```

## Optional static API key guard for tunnel access

This project now supports (and `make install` auto-initializes) an optional static API key guard at the proxy layer.

- Key file (local only): `~/.openclaw/secrets/typingmind-openclaw-proxy-static-api-key`
- Generated automatically on `make install` if missing.
- Used as client bearer token for `POST /v1` and `POST /v1/chat/completions`.
- Proxy still uses `gateway.auth.token` separately for upstream OpenClaw calls.

### Default behavior (recommended)

- `make install` defaults to `STATIC_KEY_GUARD=1`.
- TypingMind sends the static proxy bearer key.
- Proxy injects `OPENCLAW_GATEWAY_TOKEN` (read locally from `openclaw config get gateway.auth.token`) for upstream calls to OpenClaw.
- Result: TypingMind never needs the gateway token directly.

Show the key to paste into TypingMind:

```bash
make print-static-api-key
```

Rotate the key and restart proxy:

```bash
make rotate-static-api-key
```

When static key guard is enabled, TypingMind should use:

- Header key: `Authorization`
- Header value: `Bearer <STATIC_PROXY_API_KEY>`

### Optional legacy/direct gateway-key style mode

If you want to avoid the extra proxy edge key and keep legacy behavior:

```bash
make disable-static-api-key-guard
```

or at install time:

```bash
make install STATIC_KEY_GUARD=0
```

In this mode, proxy does not enforce the static bearer key. You can still set TypingMind bearer to the gateway token, but this is not recommended for tunnel exposure because it exposes a higher-privilege secret to the client side.

## Persistent Cloudflare tunnel (token-managed only)

This project supports token-managed persistent tunnel install as the only persistent mode.
No `cloudflared tunnel login` is required on the local machine.

### 1) Create tunnel and hostname in Cloudflare

In Cloudflare Zero Trust dashboard:

1. Go to `Networks` -> `Connectors` (Cloudflare Tunnels).
2. Create a tunnel (type `Cloudflared`) named `typingmind-openclaw-proxy`.
3. In `Route tunnel` -> `Published applications`, fill the form:
   - `Subdomain`: `oc`
   - `Domain`: your zone (for example `example.com`)
   - `Path`: leave empty
   - `Type`: `HTTP`
   - `URL`: `127.0.0.1:17890` (or `http://127.0.0.1:17890`)
   - Resulting hostname: `oc.<YOUR_DOMAIN>`
4. In `Install and run connectors`, copy the generated **Tunnel Token**.

Notes:

- The `Install and run connectors` page (token page) does not show hostname mapping fields.
- Hostname mapping is configured in `Route tunnel` for remotely managed tunnels.

### 2) Store token locally (do not commit)

```bash
mkdir -p ~/.cloudflared
chmod 700 ~/.cloudflared
cat > ~/.cloudflared/typingmind-openclaw-proxy.token <<'EOF'
<CLOUDFLARE_TUNNEL_TOKEN>
EOF
chmod 600 ~/.cloudflared/typingmind-openclaw-proxy.token
```

### 3) Run token-managed tunnel manually

```bash
cloudflared tunnel run --token "$(cat ~/.cloudflared/typingmind-openclaw-proxy.token)"
```

### 4) Install token-managed tunnel service (LaunchAgent + auto-restart)

```bash
make install-cloudflare-tunnel \
  TUNNEL_TOKEN_FILE=~/.cloudflared/typingmind-openclaw-proxy.token \
  TUNNEL_HOSTNAME=<TUNNEL_HOSTNAME>
```

Alternative (system-wide service via `sudo`, as shown in Cloudflare docs):

```bash
make install-cloudflare-tunnel-system \
  TUNNEL_TOKEN_FILE=~/.cloudflared/typingmind-openclaw-proxy.token
```

Check service:

```bash
make status-cloudflare-tunnel
make logs-cloudflare-tunnel
```

Stop/remove (safe if absent):

```bash
make uninstall-cloudflare-tunnel
```

If you used the system-wide service option:

```bash
make uninstall-cloudflare-tunnel-system
```

### 5) Verification

```bash
curl -i https://<TUNNEL_HOSTNAME>/v1
curl -i -X POST https://<TUNNEL_HOSTNAME>/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"x":1}'
```

Expected: HTTP `200` from proxy compatibility endpoints.

### Follow logs (proxy + fixed tunnel)

Proxy logs:

```bash
tail -f ~/.openclaw/logs/typingmind-proxy.log
```

Tunnel logs (LaunchAgent-managed):

```bash
tail -f ~/.openclaw/logs/typingmind-proxy-tunnel.log
tail -f ~/.openclaw/logs/typingmind-proxy-tunnel.err.log
```

Or via make target:

```bash
make logs-cloudflare-tunnel
```

Note: `cloudflared` commonly writes operational logs to `typingmind-proxy-tunnel.err.log`.

## Configure TypingMind (after tunnel is running)

Use this only after you have a working HTTPS endpoint from one of the tunnel options above.

- Endpoint URL:
  - Quick tunnel: `https://<TRYCLOUDFLARE_URL>/v1`
  - Persistent token tunnel: `https://<TUNNEL_HOSTNAME>/v1`
- Model ID: `openclaw:main`

Important:

- Use HTTPS endpoint for TypingMind (all client variants).
- Do not use `http://127.0.0.1:17890/v1` in TypingMind.
- Local HTTP endpoint is for local diagnostics only (for example `curl` tests).
- `Support Image Input` in TypingMind works only when OpenClaw is backed by an API provider path that actually supports vision/image payloads. In this project's current ChatGPT Plus OAuth path, image payloads are accepted but not processed as real vision input.

## Templates used by installer

- `templates/start_typingmind_proxy.sh.tpl`
- `templates/ai.openclaw.typingmind-proxy.plist.tpl`
- `templates/start_typingmind_cloudflared_token.sh.tpl`
- `templates/ai.openclaw.typingmind-proxy-tunnel-token.plist.tpl`

`make install` renders these templates into:

- `~/.openclaw/bin/start_typingmind_proxy.sh`
- `~/Library/LaunchAgents/ai.openclaw.typingmind-proxy.plist`

## Security notes

- Do not commit tokens.
- Token is fetched at runtime from local OpenClaw config (`gateway.auth.token`).
- Keep gateway bound to loopback unless you intentionally expose via secure tunnel/reverse proxy.
