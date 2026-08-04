"""Local OpenAI-compatible MiMo stub HTTP server for tests (no live MiMo key).

Serves ``{base_url}/chat/completions`` with configurable responses so provider
unit tests can exercise request building, schema validation, retries, and
timeouts without network access or a real API key.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class MiMoStubHandler(BaseHTTPRequestHandler):
    """Serves the configured response script for the stub test server."""

    server: "MiMoStubServer"

    # Quiet default logging; tests assert on server.requests instead.
    def log_message(self, _format: str, *args: Any) -> None:
        del _format, args

    def do_POST(self) -> None:  # noqa: N802 (http.server naming)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = None

        self.server.requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers),
                "body": parsed,
            }
        )

        # Validate that the caller always sent the Bearer auth header.
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self._send_json(401, {"error": {"message": "missing bearer auth"}})
            return

        step = self.server.pop_step()
        if step is None:
            self._send_json(
                200,
                chat_completion_response_json(
                    {
                        "diagnosis_summary": "stub default",
                        "risk_level": "low",
                        "possible_causes": [],
                        "recommended_actions": [],
                        "need_shutdown": False,
                    }
                ),
            )
            return

        if step.get("sleep_ms"):
            import time

            time.sleep(step["sleep_ms"] / 1000.0)

        if "status" in step:
            self._send_json(step["status"], step.get("body", {}))
            return

        content = step.get("content", "default valid content")
        if isinstance(content, dict):
            self._send_json(200, chat_completion_response_json(content))
            return
        self._send_json(200, chat_completion_response(content))

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except (ConnectionError, BrokenPipeError):
            # The test client may have timed out and aborted the connection;
            # that is expected noise, not a server failure.
            pass


def chat_completion_response(content: str) -> dict[str, Any]:
    """OpenAI-compatible envelope wrapping a string message content."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "mimo-chat",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def chat_completion_response_json(content: dict[str, Any]) -> dict[str, Any]:
    """OpenAI-compatible envelope wrapping a structured content object."""
    return chat_completion_response(json.dumps(content))


def chat_completion_response_missing_content() -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "mimo-chat",
        "choices": [{"index": 0, "message": {"role": "assistant"}, "finish_reason": "stop"}],
        "usage": {},
    }


class MiMoStubServer(ThreadingHTTPServer):
    """Threaded OpenAI-compatible stub server with a per-test response script."""

    daemon_threads = True

    def __init__(self, script: list[dict[str, Any]] | None = None) -> None:
        self.script = script if script is not None else []
        self.requests: list[dict[str, Any]] = []
        super().__init__(("127.0.0.1", 0), MiMoStubHandler)
        self._thread = threading.Thread(
            target=self.serve_forever,
            daemon=True,
            name="mimo-stub-server",
        )

    @property
    def base_url(self) -> str:
        host = self.server_address[0]
        port = self.server_address[1]
        if isinstance(host, bytes):
            host = host.decode("utf-8")
        return f"http://{host}:{port}"

    def pop_step(self) -> dict[str, Any] | None:
        if not self.script:
            return None
        return self.script.pop(0)

    def start(self) -> "MiMoStubServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
        self._thread.join(timeout=5.0)

    def __enter__(self) -> "MiMoStubServer":
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.stop()
