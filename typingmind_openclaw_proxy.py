#!/usr/bin/env python3
"""OpenAI-compatible shim for TypingMind -> OpenClaw chat-completions."""

from __future__ import annotations

import json
import os
import time
import uuid
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


GATEWAY_URL = os.environ.get("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789").rstrip("/")
GATEWAY_TOKEN = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")
STATIC_API_KEY = os.environ.get("OPENCLAW_PROXY_STATIC_API_KEY", "").strip()
LISTEN_HOST = os.environ.get("OPENCLAW_PROXY_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("OPENCLAW_PROXY_PORT", "18790"))
DEFAULT_MODEL_ID = os.environ.get("OPENCLAW_PROXY_MODEL_ID", "openclaw:main")
UPSTREAM_TIMEOUT_SECONDS = int(os.environ.get("OPENCLAW_PROXY_UPSTREAM_TIMEOUT_SECONDS", "600"))
ESCALATION_KEYWORDS_ENABLED = os.environ.get("OPENCLAW_PROXY_ESCALATION_KEYWORDS_ENABLED", "1") != "0"

KEYWORD_TO_MODEL = {
    # Fast default for ChatGPT-account Codex auth.
    "fast": "openai-codex/gpt-5.1",
    # General purpose.
    "std": "openai-codex/gpt-5.1",
    "gp": "openai-codex/gpt-5.1",
    # Lower-drain variant.
    "mini": "openai-codex/gpt-5.1-codex-mini",
    # Higher-rigor variants.
    "deep": "openai-codex/gpt-5.1-codex-max",
    "max": "openai-codex/gpt-5.1-codex-max",
    "codex": "openai-codex/gpt-5.3-codex",
    "heavy": "openai-codex/gpt-5.3-codex",
    # Explicit versions.
    "51": "openai-codex/gpt-5.1",
    "52": "openai-codex/gpt-5.2",
    "52c": "openai-codex/gpt-5.2-codex",
    "53": "openai-codex/gpt-5.3-codex",
}
KEYWORD_HELP_ALIASES = {"keywords", "keyword", "switches", "models"}


def _find_last_user_message(messages: list) -> tuple[int | None, dict | None]:
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, dict) and msg.get("role") == "user":
            return i, msg
    return None, None


def _extract_leading_keyword(text: str) -> tuple[str | None, str]:
    stripped = text.lstrip()
    if not stripped.startswith("!"):
        return None, stripped
    first, *rest = stripped.split(None, 1)
    keyword = first[1:].strip().lower()
    remainder = rest[0] if rest else ""
    return keyword, remainder


def _keyword_list_text() -> str:
    lines = ["Available model-switch keywords:"]
    for keyword, model in KEYWORD_TO_MODEL.items():
        lines.append(f"- !{keyword} -> {model}")
    lines.append("Usage example: !deep Explain the migration plan.")
    return "\n".join(lines)


def _completion_with_text(model: str, text: str) -> dict:
    ts = int(time.time())
    return {
        "id": f"chatcmpl_proxy_{uuid.uuid4()}",
        "object": "chat.completion",
        "created": ts,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _stream_completion_with_text(handler: BaseHTTPRequestHandler, model: str, text: str) -> None:
    ts = int(time.time())
    completion_id = f"chatcmpl_proxy_{uuid.uuid4()}"
    first = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": ts,
        "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}],
    }
    second = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": ts,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }

    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "close")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "authorization,content-type")
    handler.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    handler.end_headers()
    handler.wfile.write(f"data: {json.dumps(first)}\n\n".encode("utf-8"))
    handler.wfile.write(f"data: {json.dumps(second)}\n\n".encode("utf-8"))
    handler.wfile.write(b"data: [DONE]\n\n")
    handler.wfile.flush()
    handler.close_connection = True


def _local_keyword_command_completion(payload: dict, model: str) -> dict | None:
    if not ESCALATION_KEYWORDS_ENABLED:
        return None

    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        return None

    idx, user_message = _find_last_user_message(messages)
    if idx is None or not isinstance(user_message, dict):
        return None

    content = user_message.get("content")
    if not isinstance(content, str):
        return None

    keyword, _ = _extract_leading_keyword(content)
    if keyword not in KEYWORD_HELP_ALIASES:
        return None
    return _completion_with_text(model, _keyword_list_text())


def _apply_escalation_keyword(payload: dict) -> dict:
    if not ESCALATION_KEYWORDS_ENABLED:
        return payload

    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        return payload

    idx, user_message = _find_last_user_message(messages)
    if idx is None:
        return payload

    content = user_message.get("content")
    if not isinstance(content, str):
        return payload

    keyword, remainder = _extract_leading_keyword(content)
    if not keyword:
        return payload

    model = KEYWORD_TO_MODEL.get(keyword)
    if not model:
        return payload

    # Mutate in-place: override model and strip the keyword from the message.
    payload["model"] = model
    messages[idx]["content"] = remainder
    return payload


def _bearer_token(auth_header: str) -> str:
    parts = auth_header.split(" ", 1)
    if len(parts) != 2:
        return ""
    if parts[0].lower() != "bearer":
        return ""
    return parts[1].strip()


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "authorization,content-type")
    handler.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    handler.end_headers()
    handler.wfile.write(body)


def _mock_completion(model: str) -> dict:
    return _completion_with_text(model, "OK")


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        # Keep output small to avoid noisy token-bearing logs.
        print(f"[proxy] {self.address_string()} {format % args}")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "authorization,content-type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            return _json_response(self, 200, {"ok": True, "gateway": GATEWAY_URL})
        if self.path in ("/v1", "/v1/"):
            return _json_response(
                self,
                200,
                {
                    "object": "service",
                    "id": "openclaw-typingmind-proxy",
                    "chat_completions": "/v1/chat/completions",
                    "models": "/v1/models",
                },
            )
        if self.path in ("/v1/models", "/models"):
            return _json_response(
                self,
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": DEFAULT_MODEL_ID,
                            "object": "model",
                            "created": int(time.time()),
                            "owned_by": "openclaw",
                        }
                    ],
                },
            )
        _json_response(self, 404, {"error": {"message": "not found", "type": "invalid_request_error"}})

    def do_POST(self) -> None:  # noqa: N802
        # TypingMind can call POST /v1 during test/validation. Treat it as
        # chat-completions compatibility path.
        if self.path in ("/v1", "/v1/"):
            self.path = "/v1/chat/completions"

        if self.path != "/v1/chat/completions":
            return _json_response(
                self, 404, {"error": {"message": "unsupported endpoint", "type": "invalid_request_error"}}
            )

        if STATIC_API_KEY:
            provided = _bearer_token(self.headers.get("Authorization", ""))
            if provided != STATIC_API_KEY:
                return _json_response(
                    self,
                    401,
                    {"error": {"message": "invalid API key", "type": "authentication_error"}},
                )

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"

        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            payload = {}

        model = payload.get("model") or DEFAULT_MODEL_ID
        wants_stream = bool(payload.get("stream"))
        local_completion = _local_keyword_command_completion(payload, model)
        if local_completion:
            if wants_stream:
                _stream_completion_with_text(self, model, local_completion["choices"][0]["message"]["content"])
                return
            return _json_response(self, 200, local_completion)

        payload = _apply_escalation_keyword(payload)
        model = payload.get("model") or DEFAULT_MODEL_ID
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            # TypingMind "Test" can send tiny/invalid payloads; return a success envelope
            # so the model can be saved, then real chat requests can flow to OpenClaw.
            return _json_response(self, 200, _mock_completion(model))

        if not GATEWAY_TOKEN:
            return _json_response(
                self,
                500,
                {"error": {"message": "OPENCLAW_GATEWAY_TOKEN is not set", "type": "server_error"}},
            )

        raw = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url=f"{GATEWAY_URL}/v1/chat/completions",
            method="POST",
            data=raw,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {GATEWAY_TOKEN}",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=UPSTREAM_TIMEOUT_SECONDS) as response:
                content_type = response.headers.get("Content-Type", "application/json")
                is_sse = content_type.startswith("text/event-stream")

                self.send_response(response.status)
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "authorization,content-type")
                self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")

                if wants_stream or is_sse:
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    saw_done = False
                    while True:
                        chunk = response.read(1024)
                        if not chunk:
                            break
                        if b"data: [DONE]" in chunk:
                            saw_done = True
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        if saw_done:
                            break
                    if not saw_done:
                        self.wfile.write(b"data: [DONE]\n\n")
                        self.wfile.flush()
                    self.close_connection = True
                    return

                data = response.read()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(body)
            except Exception:
                payload = {"error": {"message": body[:1000], "type": "upstream_http_error"}}
            _json_response(self, exc.code, payload)
        except Exception as exc:  # noqa: BLE001
            _json_response(
                self,
                502,
                {"error": {"message": f"upstream connection failed: {exc}", "type": "upstream_connection_error"}},
            )


def main() -> None:
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), ProxyHandler)
    print(f"[proxy] listening on http://{LISTEN_HOST}:{LISTEN_PORT}")
    print(f"[proxy] upstream gateway: {GATEWAY_URL}")
    server.serve_forever()


if __name__ == "__main__":
    main()
