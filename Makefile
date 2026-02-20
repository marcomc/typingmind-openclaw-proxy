PORT ?= 17890
BASE_URL ?= http://127.0.0.1:$(PORT)
SMOKE_MODEL ?= openclaw:main
STATIC_KEY_GUARD ?= 1
LABEL ?= ai.openclaw.typingmind-proxy
TUNNEL_LABEL ?= ai.openclaw.typingmind-proxy-tunnel
TUNNEL_HOSTNAME ?= <TUNNEL_HOSTNAME>
TUNNEL_TOKEN_FILE ?= $(HOME)/.cloudflared/typingmind-openclaw-proxy.token
PROJECT_DIR := $(abspath .)
PROXY_SCRIPT := $(PROJECT_DIR)/typingmind_openclaw_proxy.py
LAUNCH_SCRIPT := $(HOME)/.openclaw/bin/start_typingmind_proxy.sh
PLIST := $(HOME)/Library/LaunchAgents/$(LABEL).plist
LOG_DIR := $(HOME)/.openclaw/logs
STATIC_KEY_DIR := $(HOME)/.openclaw/secrets
STATIC_KEY_FILE ?= $(STATIC_KEY_DIR)/typingmind-openclaw-proxy-static-api-key
TEMPLATE_DIR := $(PROJECT_DIR)/templates
SCRIPT_TEMPLATE := $(TEMPLATE_DIR)/start_typingmind_proxy.sh.tpl
PLIST_TEMPLATE := $(TEMPLATE_DIR)/ai.openclaw.typingmind-proxy.plist.tpl
TUNNEL_SCRIPT := $(HOME)/.openclaw/bin/start_typingmind_cloudflared.sh
TUNNEL_PLIST := $(HOME)/Library/LaunchAgents/$(TUNNEL_LABEL).plist
TUNNEL_SCRIPT_TEMPLATE := $(TEMPLATE_DIR)/start_typingmind_cloudflared_token.sh.tpl
TUNNEL_PLIST_TEMPLATE := $(TEMPLATE_DIR)/ai.openclaw.typingmind-proxy-tunnel-token.plist.tpl

.PHONY: help install uninstall start stop restart status logs health smoke smoke-keywords launchctl-diagnostics print-static-api-key rotate-static-api-key enable-static-api-key-guard disable-static-api-key-guard lint \
	install-cloudflare-tunnel uninstall-cloudflare-tunnel \
	start-cloudflare-tunnel stop-cloudflare-tunnel restart-cloudflare-tunnel \
	status-cloudflare-tunnel logs-cloudflare-tunnel \
	install-cloudflare-tunnel-system uninstall-cloudflare-tunnel-system

help:
	@printf '%s\n' \
	'typingmind-openclaw-proxy Make targets' \
	'' \
	'Proxy lifecycle:' \
	'  make install' \
	'  make uninstall' \
	'  make start' \
	'  make stop' \
	'  make restart' \
	'  make status' \
	'  make logs' \
	'  make health' \
	'  make smoke [BASE_URL=...] [SMOKE_MODEL=...]' \
	'  make smoke-keywords [BASE_URL=...] [SMOKE_MODEL=...]' \
	'  make launchctl-diagnostics' \
	'' \
	'Auth/key helpers:' \
	'  make print-static-api-key' \
	'  make rotate-static-api-key' \
	'  make enable-static-api-key-guard' \
	'  make disable-static-api-key-guard' \
	'' \
	'Tunnel lifecycle (user LaunchAgent):' \
	'  make install-cloudflare-tunnel TUNNEL_TOKEN_FILE=... TUNNEL_HOSTNAME=...' \
	'  make uninstall-cloudflare-tunnel' \
	'  make start-cloudflare-tunnel' \
	'  make stop-cloudflare-tunnel' \
	'  make restart-cloudflare-tunnel TUNNEL_TOKEN_FILE=... TUNNEL_HOSTNAME=...' \
	'  make status-cloudflare-tunnel' \
	'  make logs-cloudflare-tunnel' \
	'' \
	'Tunnel lifecycle (system service):' \
	'  make install-cloudflare-tunnel-system TUNNEL_TOKEN_FILE=...' \
	'  make uninstall-cloudflare-tunnel-system' \
	'' \
	'Docs:' \
	'  make lint'

install:
	@mkdir -p $(HOME)/.openclaw/bin $(HOME)/Library/LaunchAgents $(LOG_DIR) $(STATIC_KEY_DIR)
	@chmod 700 $(STATIC_KEY_DIR)
	@if [ "$(STATIC_KEY_GUARD)" = "1" ]; then \
		if [ ! -f "$(STATIC_KEY_FILE)" ]; then \
			openssl rand -hex 32 > "$(STATIC_KEY_FILE)"; \
			chmod 600 "$(STATIC_KEY_FILE)"; \
			echo "Generated static API key at $(STATIC_KEY_FILE)"; \
		else \
			chmod 600 "$(STATIC_KEY_FILE)"; \
		fi; \
	else \
		rm -f "$(STATIC_KEY_FILE)"; \
		echo "Static API key guard disabled (no proxy key file)."; \
	fi
	@cp $(SCRIPT_TEMPLATE) $(LAUNCH_SCRIPT)
	@sed -i '' 's#__PROJECT_DIR__#$(PROJECT_DIR)#g' $(LAUNCH_SCRIPT)
	@sed -i '' 's#__PORT__#$(PORT)#g' $(LAUNCH_SCRIPT)
	@sed -i '' 's#__PROXY_SCRIPT__#$(PROXY_SCRIPT)#g' $(LAUNCH_SCRIPT)
	@sed -i '' 's#__STATIC_KEY_FILE__#$(STATIC_KEY_FILE)#g' $(LAUNCH_SCRIPT)
	@chmod 700 $(LAUNCH_SCRIPT)
	@cp $(PLIST_TEMPLATE) $(PLIST)
	@sed -i '' 's#__LABEL__#$(LABEL)#g' $(PLIST)
	@sed -i '' 's#__LAUNCH_SCRIPT__#$(LAUNCH_SCRIPT)#g' $(PLIST)
	@sed -i '' 's#__LOG_DIR__#$(LOG_DIR)#g' $(PLIST)
	@launchctl bootout gui/$$(id -u)/$(LABEL) 2>/dev/null || true
	@launchctl bootstrap gui/$$(id -u) $(PLIST)
	@launchctl kickstart -k gui/$$(id -u)/$(LABEL)
	@echo "Installed and started $(LABEL) on port $(PORT)"
	@if [ -f "$(STATIC_KEY_FILE)" ]; then \
		echo "Static API key guard: enabled"; \
		echo "Static API key file: $(STATIC_KEY_FILE)"; \
		echo "Show key for TypingMind: make print-static-api-key"; \
	else \
		echo "Static API key guard: disabled"; \
		echo "TypingMind can use direct gateway auth semantics (legacy mode)."; \
	fi

uninstall:
	@$(MAKE) uninstall-cloudflare-tunnel >/dev/null 2>&1 || true
	@launchctl bootout gui/$$(id -u)/$(LABEL) 2>/dev/null || true
	@rm -f $(PLIST)
	@rm -f $(LAUNCH_SCRIPT)
	@echo "Uninstalled $(LABEL), tunnel agent (if present), and launcher artifacts"

start:
	@launchctl kickstart -k gui/$$(id -u)/$(LABEL)

stop:
	@launchctl bootout gui/$$(id -u)/$(LABEL)

restart: stop install

status:
	@launchctl print gui/$$(id -u)/$(LABEL) | sed -n '1,40p'
	@lsof -nP -iTCP:$(PORT) -sTCP:LISTEN || true

logs:
	@tail -n 80 $(LOG_DIR)/typingmind-proxy.log

health:
	@curl -sS http://127.0.0.1:$(PORT)/health | jq .

smoke:
	@set -euo pipefail; \
	API_KEY=""; \
	if [ -f "$(STATIC_KEY_FILE)" ]; then \
		API_KEY="$$(tr -d '\r\n' < "$(STATIC_KEY_FILE)")"; \
	fi; \
	for i in 1 2 3 4 5 6 7 8 9 10; do \
		if curl -fsS "$(BASE_URL)/health" >/dev/null 2>&1; then \
			break; \
		fi; \
		sleep 1; \
	done; \
	echo "Smoke: GET $(BASE_URL)/v1"; \
	curl -fsS "$(BASE_URL)/v1" | jq -e '.object == "service" and .chat_completions == "/v1/chat/completions"' >/dev/null; \
	echo "Smoke: GET $(BASE_URL)/v1/models"; \
	curl -fsS "$(BASE_URL)/v1/models" | jq -e '.object == "list" and (.data | type == "array") and (.data | length >= 1)' >/dev/null; \
	echo "Smoke: POST $(BASE_URL)/v1/chat/completions"; \
	if [ -n "$$API_KEY" ]; then \
		curl -fsS -X POST "$(BASE_URL)/v1/chat/completions" \
			-H "Authorization: Bearer $$API_KEY" \
			-H "Content-Type: application/json" \
			-d '{"model":"$(SMOKE_MODEL)","messages":[{"role":"user","content":"Reply OK"}],"stream":false}' \
			| jq -e '.object == "chat.completion" and (.choices | type == "array") and (.choices | length >= 1)' >/dev/null; \
	else \
		curl -fsS -X POST "$(BASE_URL)/v1/chat/completions" \
			-H "Content-Type: application/json" \
			-d '{"model":"$(SMOKE_MODEL)","messages":[{"role":"user","content":"Reply OK"}],"stream":false}' \
			| jq -e '.object == "chat.completion" and (.choices | type == "array") and (.choices | length >= 1)' >/dev/null; \
	fi; \
	echo "Smoke test passed"

smoke-keywords:
	@set -euo pipefail; \
	API_KEY=""; \
	if [ -f "$(STATIC_KEY_FILE)" ]; then \
		API_KEY="$$(tr -d '\r\n' < "$(STATIC_KEY_FILE)")"; \
	fi; \
	call_api() { \
		kw="$$1"; \
		if [ -n "$$API_KEY" ]; then \
			curl -fsS -X POST "$(BASE_URL)/v1/chat/completions" \
				-H "Authorization: Bearer $$API_KEY" \
				-H "Content-Type: application/json" \
				-d "{\"model\":\"$(SMOKE_MODEL)\",\"messages\":[{\"role\":\"user\",\"content\":\"!$${kw} Reply OK\"}],\"stream\":false}"; \
		else \
			curl -fsS -X POST "$(BASE_URL)/v1/chat/completions" \
				-H "Content-Type: application/json" \
				-d "{\"model\":\"$(SMOKE_MODEL)\",\"messages\":[{\"role\":\"user\",\"content\":\"!$${kw} Reply OK\"}],\"stream\":false}"; \
		fi; \
	}; \
	check_keyword() { \
		kw="$$1"; \
		expected="$$2"; \
		actual="$$(call_api "$$kw" | jq -r '.model')"; \
		if [ "$$actual" != "$$expected" ]; then \
			echo "Keyword !$$kw failed: expected $$expected got $$actual"; \
			exit 1; \
		fi; \
		echo "Keyword !$$kw -> $$actual"; \
	}; \
	check_keyword fast openai-codex/gpt-5.3-codex-spark; \
	check_keyword spark openai-codex/gpt-5.3-codex-spark; \
	check_keyword std openai-codex/gpt-5.1; \
	check_keyword gp openai-codex/gpt-5.1; \
	check_keyword mini openai-codex/gpt-5.1-codex-mini; \
	check_keyword deep openai-codex/gpt-5.1-codex-max; \
	check_keyword max openai-codex/gpt-5.1-codex-max; \
	check_keyword codex openai-codex/gpt-5.3-codex; \
	check_keyword heavy openai-codex/gpt-5.3-codex; \
	check_keyword 51 openai-codex/gpt-5.1; \
	check_keyword 52 openai-codex/gpt-5.2; \
	check_keyword 52c openai-codex/gpt-5.2-codex; \
	check_keyword 53 openai-codex/gpt-5.3-codex; \
	echo "Keyword smoke tests passed"

launchctl-diagnostics:
	@echo "==> launchctl print gui/$$(id -u)/$(LABEL) <=="
	@launchctl print gui/$$(id -u)/$(LABEL) | sed -n '1,80p'
	@echo
	@echo "==> launchctl print gui/$$(id -u)/$(TUNNEL_LABEL) <=="
	@launchctl print gui/$$(id -u)/$(TUNNEL_LABEL) | sed -n '1,80p' || true
	@echo
	@echo "==> launchctl list (filtered) <=="
	@launchctl list | rg "$(LABEL)|$(TUNNEL_LABEL)|openclaw|cloudflared" || true

print-static-api-key:
	@if [ ! -f "$(STATIC_KEY_FILE)" ]; then \
		echo "Missing static API key file: $(STATIC_KEY_FILE)"; \
		echo "Run: make install"; \
		exit 1; \
	fi
	@echo "TypingMind proxy static API key:"
	@cat "$(STATIC_KEY_FILE)"

rotate-static-api-key:
	@mkdir -p $(STATIC_KEY_DIR)
	@chmod 700 $(STATIC_KEY_DIR)
	@openssl rand -hex 32 > "$(STATIC_KEY_FILE)"
	@chmod 600 "$(STATIC_KEY_FILE)"
	@launchctl kickstart -k gui/$$(id -u)/$(LABEL)
	@echo "Rotated static API key: $(STATIC_KEY_FILE)"
	@echo "Update TypingMind Authorization bearer value with:"
	@echo "  make print-static-api-key"

enable-static-api-key-guard:
	@mkdir -p $(STATIC_KEY_DIR)
	@chmod 700 $(STATIC_KEY_DIR)
	@if [ ! -f "$(STATIC_KEY_FILE)" ]; then \
		openssl rand -hex 32 > "$(STATIC_KEY_FILE)"; \
	fi
	@chmod 600 "$(STATIC_KEY_FILE)"
	@launchctl kickstart -k gui/$$(id -u)/$(LABEL)
	@echo "Enabled static API key guard."
	@echo "Use this bearer in TypingMind:"
	@echo "  make print-static-api-key"

disable-static-api-key-guard:
	@rm -f "$(STATIC_KEY_FILE)"
	@launchctl kickstart -k gui/$$(id -u)/$(LABEL)
	@echo "Disabled static API key guard."
	@echo "Proxy no longer requires the static bearer key."

lint:
	@markdownlint --fix *.md
	@markdownlint *.md

install-cloudflare-tunnel:
	@if [ ! -f "$(TUNNEL_TOKEN_FILE)" ]; then \
		echo "Missing tunnel token file: $(TUNNEL_TOKEN_FILE)"; \
		echo "Create it with your Cloudflare tunnel token and chmod 600"; \
		exit 1; \
	fi
	@if [ "$(TUNNEL_HOSTNAME)" = "<TUNNEL_HOSTNAME>" ]; then \
		echo "Set TUNNEL_HOSTNAME for operator visibility (for example oc.example.com)"; \
		exit 1; \
	fi
	@mkdir -p $(HOME)/.openclaw/bin $(HOME)/Library/LaunchAgents $(LOG_DIR)
	@cp $(TUNNEL_SCRIPT_TEMPLATE) $(TUNNEL_SCRIPT)
	@sed -i '' 's#__TUNNEL_TOKEN_FILE__#$(TUNNEL_TOKEN_FILE)#g' $(TUNNEL_SCRIPT)
	@chmod 700 $(TUNNEL_SCRIPT)
	@cp $(TUNNEL_PLIST_TEMPLATE) $(TUNNEL_PLIST)
	@sed -i '' 's#__TUNNEL_LABEL__#$(TUNNEL_LABEL)#g' $(TUNNEL_PLIST)
	@sed -i '' 's#__TUNNEL_SCRIPT__#$(TUNNEL_SCRIPT)#g' $(TUNNEL_PLIST)
	@sed -i '' 's#__LOG_DIR__#$(LOG_DIR)#g' $(TUNNEL_PLIST)
	@launchctl bootout gui/$$(id -u)/$(TUNNEL_LABEL) 2>/dev/null || true
	@launchctl bootstrap gui/$$(id -u) $(TUNNEL_PLIST)
	@launchctl kickstart -k gui/$$(id -u)/$(TUNNEL_LABEL)
	@echo "Installed and started $(TUNNEL_LABEL) (token-managed) for https://$(TUNNEL_HOSTNAME)"

uninstall-cloudflare-tunnel:
	@launchctl bootout gui/$$(id -u)/$(TUNNEL_LABEL) 2>/dev/null || true
	@rm -f $(TUNNEL_PLIST)
	@rm -f $(TUNNEL_SCRIPT)
	@echo "Uninstalled $(TUNNEL_LABEL) (if present)"

start-cloudflare-tunnel:
	@launchctl kickstart -k gui/$$(id -u)/$(TUNNEL_LABEL)

stop-cloudflare-tunnel:
	@launchctl bootout gui/$$(id -u)/$(TUNNEL_LABEL)

restart-cloudflare-tunnel: stop-cloudflare-tunnel install-cloudflare-tunnel

status-cloudflare-tunnel:
	@launchctl print gui/$$(id -u)/$(TUNNEL_LABEL) | sed -n '1,40p'
	@echo "Token file: $(TUNNEL_TOKEN_FILE)"

logs-cloudflare-tunnel:
	@echo "==> $(LOG_DIR)/typingmind-proxy-tunnel.log <=="
	@tail -n 80 $(LOG_DIR)/typingmind-proxy-tunnel.log 2>/dev/null || true
	@echo
	@echo "==> $(LOG_DIR)/typingmind-proxy-tunnel.err.log <=="
	@tail -n 80 $(LOG_DIR)/typingmind-proxy-tunnel.err.log 2>/dev/null || true

install-cloudflare-tunnel-system:
	@if [ ! -f "$(TUNNEL_TOKEN_FILE)" ]; then \
		echo "Missing tunnel token file: $(TUNNEL_TOKEN_FILE)"; \
		echo "Create it with your Cloudflare tunnel token and chmod 600"; \
		exit 1; \
	fi
	@echo "Installing system-wide cloudflared service (requires sudo)..."
	@sudo cloudflared service install "$$(cat $(TUNNEL_TOKEN_FILE))"
	@echo "Installed system service: com.cloudflare.cloudflared"
	@echo "Inspect with: sudo launchctl print system/com.cloudflare.cloudflared | sed -n '1,40p'"

uninstall-cloudflare-tunnel-system:
	@echo "Removing system-wide cloudflared service (requires sudo)..."
	@sudo launchctl bootout system/com.cloudflare.cloudflared >/dev/null 2>&1 || true
	@sudo rm -f /Library/LaunchDaemons/com.cloudflare.cloudflared.plist
	@echo "Uninstalled system service (if present)."
