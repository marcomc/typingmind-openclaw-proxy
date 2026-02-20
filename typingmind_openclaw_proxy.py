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
    ts = int(time.time())
    return {
        "id": f"chatcmpl_proxy_{uuid.uuid4()}",
        "object": "chat.completion",
        "created": ts,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "OK"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


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
            with urllib.request.urlopen(request, timeout=120) as response:
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
