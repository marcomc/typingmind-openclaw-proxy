#!/bin/zsh
set -euo pipefail
exec cloudflared tunnel run --token "$(cat __TUNNEL_TOKEN_FILE__)"
