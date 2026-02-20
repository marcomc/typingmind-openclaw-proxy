#!/bin/zsh
set -euo pipefail
cd __PROJECT_DIR__
TOKEN=$(openclaw config get gateway.auth.token | tr -d '"')
STATIC_KEY=""
if [ -f "__STATIC_KEY_FILE__" ]; then
  STATIC_KEY=$(tr -d '\r\n' < "__STATIC_KEY_FILE__")
fi
exec env PYTHONUNBUFFERED=1 OPENCLAW_GATEWAY_TOKEN="$TOKEN" OPENCLAW_PROXY_STATIC_API_KEY="$STATIC_KEY" OPENCLAW_PROXY_PORT=__PORT__ \
  python3 __PROXY_SCRIPT__
