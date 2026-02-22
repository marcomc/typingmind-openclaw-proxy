#!/usr/bin/env python3
"""OpenAI-compatible shim for TypingMind -> OpenClaw chat-completions."""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


GATEWAY_URL = os.environ.get("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789").rstrip("/")
GATEWAY_TOKEN = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")
STATIC_API_KEY = os.environ.get("OPENCLAW_PROXY_STATIC_API_KEY", "").strip()
LISTEN_HOST = os.environ.get("OPENCLAW_PROXY_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("OPENCLAW_PROXY_PORT", "18790"))
DEFAULT_MODEL_ID = os.environ.get("OPENCLAW_PROXY_MODEL_ID", "openclaw:main")
UPSTREAM_TIMEOUT_SECONDS = int(os.environ.get("OPENCLAW_PROXY_UPSTREAM_TIMEOUT_SECONDS", "600"))
MAX_UPSTREAM_TOKENS = int(os.environ.get("OPENCLAW_PROXY_MAX_UPSTREAM_TOKENS", "0"))
ESCALATION_KEYWORDS_ENABLED = os.environ.get("OPENCLAW_PROXY_ESCALATION_KEYWORDS_ENABLED", "1") != "0"
MODEL_ID_ALIASING_ENABLED = os.environ.get("OPENCLAW_PROXY_MODEL_ID_ALIASING_ENABLED", "1") != "0"
MODEL_ID_ALIAS_PREFIX = os.environ.get("OPENCLAW_PROXY_MODEL_ID_ALIAS_PREFIX", "ocm:")
DEBUG_MODEL_ROUTING = os.environ.get("OPENCLAW_PROXY_DEBUG_MODEL_ROUTING", "1") != "0"
UPSTREAM_TO_FRIENDLY_MODEL_ID = {
    "openai-codex/gpt-5.1": "openclaw:gpt-5-1",
    "openai-codex/gpt-5.1-codex-mini": "openclaw:gpt-5-1-codex-mini",
    "openai-codex/gpt-5.1-codex-max": "openclaw:gpt-5-1-codex-max",
    "openai-codex/gpt-5.2": "openclaw:gpt-5-2",
    "openai-codex/gpt-5.2-codex": "openclaw:gpt-5-2-codex",
    "openai-codex/gpt-5.3-codex": "openclaw:gpt-5-3-codex",
    "openai-codex/gpt-5.3-codex-spark": "openclaw:gpt-5-3-codex-spark",
}
FRIENDLY_TO_UPSTREAM_MODEL_ID = {v: k for k, v in UPSTREAM_TO_FRIENDLY_MODEL_ID.items()}

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
        lines.append(f"- !{keyword} -> {_encode_model_id_for_client(model)}")
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
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        return


def _mock_completion(model: str) -> dict:
    return _completion_with_text(model, "OK")


def _encode_model_id_for_client(model_id: str) -> str:
    if not MODEL_ID_ALIASING_ENABLED:
        return model_id
    known = UPSTREAM_TO_FRIENDLY_MODEL_ID.get(model_id)
    if known:
        return known
    if "/" not in model_id:
        return model_id
    return f"{MODEL_ID_ALIAS_PREFIX}{model_id.replace('/', '__')}"


def _decode_model_id_from_client(model_id: str) -> str:
    if not MODEL_ID_ALIASING_ENABLED:
        return model_id
    known = FRIENDLY_TO_UPSTREAM_MODEL_ID.get(model_id)
    if known:
        return known
    if not model_id.startswith(MODEL_ID_ALIAS_PREFIX):
        return model_id
    aliased = model_id[len(MODEL_ID_ALIAS_PREFIX) :]
    if not aliased:
        return model_id
    return aliased.replace("__", "/")


def _encode_models_payload_for_client(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return payload
    data = payload.get("data")
    if not isinstance(data, list):
        return payload
    encoded_data: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        encoded_item = dict(item)
        model_id = encoded_item.get("id")
        if isinstance(model_id, str):
            encoded_item["id"] = _encode_model_id_for_client(model_id)
        encoded_data.append(encoded_item)
    encoded_payload = dict(payload)
    encoded_payload["data"] = encoded_data
    return encoded_payload


def _normalized_path(raw_path: str) -> str:
    path = urllib.parse.unquote(raw_path or "")
    path = path.split("?", 1)[0].strip()
    return path


def _coerce_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _apply_generation_limits(payload: dict) -> dict:
    if MAX_UPSTREAM_TOKENS <= 0:
        return payload
    for field in ("max_tokens", "max_completion_tokens"):
        value = _coerce_int(payload.get(field))
        if value is None:
            continue
        if value > MAX_UPSTREAM_TOKENS:
            payload[field] = MAX_UPSTREAM_TOKENS
    return payload


def _fetch_upstream_models() -> dict | None:
    if not GATEWAY_TOKEN:
        return None
    request = urllib.request.Request(
        url=f"{GATEWAY_URL}/v1/models",
        method="GET",
        headers={"Authorization": f"Bearer {GATEWAY_TOKEN}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=UPSTREAM_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("data"), list):
                return payload
    except Exception:
        return None
    return None


def _fetch_cli_models() -> dict | None:
    try:
        proc = subprocess.run(
            ["openclaw", "models", "list", "--json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=UPSTREAM_TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads(proc.stdout)
    except Exception:
        return None
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return None
    data: list[dict] = []
    now = int(time.time())
    for item in models:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if not isinstance(key, str) or not key:
            continue
        data.append(
            {
                "id": key,
                "object": "model",
                "created": now,
                "owned_by": "openclaw",
            }
        )
    if not data:
        return None
    return {"object": "list", "data": data}


def _sse_event_data(event_bytes: bytes) -> str:
    text = event_bytes.decode("utf-8", errors="ignore")
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    return "\n".join(data_lines)


def _sse_has_finish_reason_stop(event_bytes: bytes) -> bool:
    data = _sse_event_data(event_bytes)
    if not data or data == "[DONE]":
        return False
    try:
        payload = json.loads(data)
    except Exception:
        return False
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return False
    for choice in choices:
        if isinstance(choice, dict) and choice.get("finish_reason") == "stop":
            return True
    return False


def _write_bytes(handler: BaseHTTPRequestHandler, data: bytes) -> bool:
    try:
        handler.wfile.write(data)
        handler.wfile.flush()
        return True
    except (BrokenPipeError, ConnectionResetError):
        handler.close_connection = True
    return False


def _synthetic_stop_chunk(model: str) -> bytes:
    stop_chunk = {
        "id": f"chatcmpl_proxy_{uuid.uuid4()}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    return f"data: {json.dumps(stop_chunk)}\n\n".encode("utf-8")


def _debug_log_model_routing(
    *,
    path: str,
    requested_model: str,
    decoded_model: str,
    forwarded_model: str,
    wants_stream: bool,
) -> None:
    if not DEBUG_MODEL_ROUTING:
        return
    print(
        "[proxy][route] "
        f"path={path} requested={requested_model} decoded={decoded_model} "
        f"forwarded={forwarded_model} stream={str(wants_stream).lower()}"
    )


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
        path = _normalized_path(self.path)
        if path == "/health":
            return _json_response(self, 200, {"ok": True, "gateway": GATEWAY_URL})
        if path in ("/v1", "/v1/"):
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
        if path in ("/v1/models", "/models"):
            upstream_models = _fetch_upstream_models()
            if upstream_models:
                return _json_response(self, 200, _encode_models_payload_for_client(upstream_models))
            cli_models = _fetch_cli_models()
            if cli_models:
                return _json_response(self, 200, _encode_models_payload_for_client(cli_models))
            return _json_response(
                self,
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": _encode_model_id_for_client(DEFAULT_MODEL_ID),
                            "object": "model",
                            "created": int(time.time()),
                            "owned_by": "openclaw",
                        }
                    ],
                },
            )
        _json_response(self, 404, {"error": {"message": "not found", "type": "invalid_request_error"}})

    def do_POST(self) -> None:  # noqa: N802
        path = _normalized_path(self.path)
        # TypingMind can call POST /v1 during test/validation. Treat it as
        # chat-completions compatibility path.
        if path in ("/v1", "/v1/"):
            path = "/v1/chat/completions"

        if path != "/v1/chat/completions":
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

        requested_model = payload.get("model") or DEFAULT_MODEL_ID
        model = _decode_model_id_from_client(requested_model)
        payload["model"] = model
        wants_stream = bool(payload.get("stream"))
        local_completion = _local_keyword_command_completion(payload, requested_model)
        if local_completion:
            if wants_stream:
                _stream_completion_with_text(self, requested_model, local_completion["choices"][0]["message"]["content"])
                return
            return _json_response(self, 200, local_completion)

        payload = _apply_escalation_keyword(payload)
        payload = _apply_generation_limits(payload)
        model = payload.get("model") or DEFAULT_MODEL_ID
        _debug_log_model_routing(
            path=path,
            requested_model=requested_model,
            decoded_model=_decode_model_id_from_client(requested_model),
            forwarded_model=model,
            wants_stream=wants_stream,
        )
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
                    saw_finish_reason_stop = False
                    sse_buffer = b""
                    while True:
                        chunk = response.read(1024)
                        if not chunk:
                            break
                        sse_buffer += chunk
                        while b"\n\n" in sse_buffer:
                            event, sse_buffer = sse_buffer.split(b"\n\n", 1)
                            event_bytes = event + b"\n\n"
                            if _sse_has_finish_reason_stop(event_bytes):
                                saw_finish_reason_stop = True
                            if _sse_event_data(event_bytes) == "[DONE]":
                                if not saw_finish_reason_stop and not _write_bytes(self, _synthetic_stop_chunk(model)):
                                    return
                                if not _write_bytes(self, b"data: [DONE]\n\n"):
                                    return
                                saw_done = True
                                break
                            if not _write_bytes(self, event_bytes):
                                return
                        if saw_done:
                            break
                    if not saw_done:
                        if not saw_finish_reason_stop and not _write_bytes(self, _synthetic_stop_chunk(model)):
                            return
                        if not _write_bytes(self, b"data: [DONE]\n\n"):
                            return
                    self.close_connection = True
                    return

                data = response.read()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    return
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(body)
            except Exception:
                payload = {"error": {"message": body[:1000], "type": "upstream_http_error"}}
            _json_response(self, exc.code, payload)
        except (BrokenPipeError, ConnectionResetError):
            return
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
