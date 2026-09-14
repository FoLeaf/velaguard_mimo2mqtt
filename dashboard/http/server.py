"""Read-only HTTP surface: static web page + JSON API (stdlib http.server).

Boundary V5: GET-only. There is deliberately no POST/PUT/DELETE route and no
MQTT publish path behind this server.
"""

from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from dashboard.observability.logging import get_logger
from dashboard.storage.db import DashboardStore

logger = get_logger(__name__)

_WEB_DIR = Path(__file__).resolve().parent.parent / "web"

_STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}

_DEVICE_HISTORY_RE = re.compile(r"^/api/devices/([^/]+)/history$")
_DEVICE_DETAIL_RE = re.compile(r"^/api/devices/([^/]+)$")

_MAX_HISTORY_MINUTES = 1440
_MAX_HISTORY_POINTS = 2000


def build_handler(store: DashboardStore) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "VelaGuardDashboard/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            logger.debug("http_request " + fmt, *args)

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            parsed = urlparse(self.path)
            path = parsed.path

            static = _STATIC_FILES.get(path)
            if static is not None:
                self._serve_static(static[0], static[1])
                return

            try:
                if path == "/api/devices":
                    self._send_json(200, {"devices": store.list_devices()})
                    return
                if path == "/api/alarms":
                    self._send_json(200, store.list_alarms())
                    return
                if path == "/api/messages":
                    query = parse_qs(parsed.query)
                    limit = _bounded_int(query, "limit", default=100, maximum=500)
                    self._send_json(200, {"messages": store.list_messages(limit)})
                    return

                match = _DEVICE_HISTORY_RE.match(path)
                if match is not None:
                    query = parse_qs(parsed.query)
                    points = query.get("point", [])
                    point_id = points[0] if points else None
                    if not point_id:
                        self._send_json(400, {"error": "missing point parameter"})
                        return
                    minutes = _bounded_int(
                        query, "minutes", default=60, maximum=_MAX_HISTORY_MINUTES
                    )
                    since = _now_ms() - minutes * 60 * 1000
                    rows = store.history(
                        match.group(1), point_id, since, limit=_MAX_HISTORY_POINTS
                    )
                    self._send_json(
                        200,
                        {
                            "device_id": match.group(1),
                            "point_id": point_id,
                            "minutes": minutes,
                            "samples": rows,
                        },
                    )
                    return

                match = _DEVICE_DETAIL_RE.match(path)
                if match is not None:
                    device = store.get_device(match.group(1))
                    if device is None:
                        self._send_json(404, {"error": "device_not_found"})
                    else:
                        self._send_json(200, device)
                    return

                self._send_json(404, {"error": "not_found"})
            except Exception:
                logger.exception("http_api_error path=%s", path)
                self._send_json(500, {"error": "internal_error"})

        def _serve_static(self, filename: str, content_type: str) -> None:
            file_path = _WEB_DIR / filename
            try:
                body = file_path.read_bytes()
            except OSError:
                self._send_json(500, {"error": "static_file_missing"})
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return DashboardHandler


def _bounded_int(
    query: dict[str, list[str]], key: str, *, default: int, maximum: int
) -> int:
    values = query.get(key, [])
    if not values:
        return default
    try:
        value = int(values[0])
    except ValueError:
        return default
    if value < 1:
        return default
    return min(value, maximum)


def _now_ms() -> int:
    return int(time.time() * 1000)


class DashboardHttpServer:
    """Threading HTTP server wrapper exposing start/stop lifecycle."""

    def __init__(self, store: DashboardStore, host: str, port: int) -> None:
        self._host = host
        self._port = port
        handler = build_handler(store)
        self._server = ThreadingHTTPServer((host, port), handler)
        self._server.daemon_threads = True

    @property
    def port(self) -> int:
        return self._server.server_port

    def start(self) -> None:
        thread = threading.Thread(
            target=self._server.serve_forever,
            name="dashboard-http",
            daemon=True,
        )
        thread.start()
        logger.info(
            "dashboard_http_listening host=%s port=%s", self._host, self.port
        )

    def stop(self) -> None:
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:
            logger.exception("dashboard_http_stop_error")
