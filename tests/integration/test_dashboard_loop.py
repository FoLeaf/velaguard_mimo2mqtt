"""Dashboard integration: synthetic board → collector → HTTP API (optional).

Requires broker on localhost:1883:
  docker compose -f deploy/dev/docker-compose.yml up -d
"""

from __future__ import annotations

import json
import socket
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

import pytest

from dashboard.application.collector import Collector
from dashboard.http.server import DashboardHttpServer
from dashboard.storage.db import DashboardStore
from dashboard.tools.synthetic_board import (
    DEMO_POINT_TABLE,
    build_alarm,
    build_status,
    build_telemetry,
)
from ai_bridge.transport.mqtt.client import MqttBridgeClient

pytestmark = pytest.mark.integration


def _broker_available(host: str = "localhost", port: int = 1883, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def require_broker() -> None:
    if not _broker_available():
        pytest.skip("Mosquitto not available on localhost:1883")


class _DashboardStack:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DashboardStore(str(Path(self.tmp.name) / "dash.db"))
        self.collector = Collector(self.store, message_buffer_limit=100)
        self.http = DashboardHttpServer(self.store, "127.0.0.1", 0)
        self.port = self.http.port

    def start(self) -> None:
        self.http.start()

    def stop(self) -> None:
        self.http.stop()
        self.store.close()
        self.tmp.cleanup()


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as res:
        return json.loads(res.read().decode("utf-8"))


def _publish(client: MqttBridgeClient, topic: str, payload) -> None:
    body = json.dumps(payload).encode()
    client._client.publish(topic, body, qos=1).wait_for_publish(timeout=5)


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_synthetic_board_to_dashboard_api(require_broker: None) -> None:
    stack = _DashboardStack()
    stack.start()
    device_id = f"itest-{uuid.uuid4().hex[:6]}"
    root = f"vg/{device_id}"

    board = MqttBridgeClient(
        host="localhost",
        port=1883,
        client_id=f"synthetic-board-itest-{uuid.uuid4().hex[:6]}",
    )
    board.start()
    assert board.wait_connected(timeout=5.0)

    try:
        # Point table first (retained, QoS 1) — the cloud contract under test.
        _publish(board, f"{root}/point_table", DEMO_POINT_TABLE)
        _publish(board, f"{root}/status", build_status(device_id, True, 1000))
        _publish(board, f"{root}/telemetry", build_telemetry(tick=0))
        _publish(board, f"{root}/alarm",
                 build_alarm(device_id, "temp", "threshold_high", "raised", 36.5, 35.0, 1))

        assert _wait_for(
            lambda: any(
                d["device_id"] == device_id
                for d in _get_json("http://127.0.0.1:%d/api/devices" % stack.port)["devices"]
            ),
        )

        devices = _get_json(f"http://127.0.0.1:{stack.port}/api/devices")["devices"]
        mine = [d for d in devices if d["device_id"] == device_id][0]
        assert mine["online"] is True
        assert mine["point_count"] == 3

        detail = _get_json(f"http://127.0.0.1:{stack.port}/api/devices/{device_id}")
        assert [p["id"] for p in detail["points"]] == ["temp", "humidity", "flood"]
        temp_point = detail["points"][0]
        assert temp_point["name"] == "温度"
        assert temp_point["latest"]["value"] == build_telemetry(0)[0]["value"]

        alarms = _get_json(f"http://127.0.0.1:{stack.port}/api/alarms")
        active = [a for a in alarms["active"] if a["device_id"] == device_id]
        assert len(active) == 1
        assert active[0]["payload"]["state"] == "raised"

        messages = _get_json(f"http://127.0.0.1:{stack.port}/api/messages")["messages"]
        assert all(m["quarantine_reason"] is None for m in messages)
        kinds = {m["kind"] for m in messages}
        assert {"status", "telemetry", "alarm", "point_table"} <= kinds

        history = _get_json(
            f"http://127.0.0.1:{stack.port}/api/devices/{device_id}/history?point=temp&minutes=5"
        )
        assert len(history["samples"]) >= 1

        # Static page served for the browser UI.
        with urllib.request.urlopen(
            f"http://127.0.0.1:{stack.port}/", timeout=5
        ) as res:
            html = res.read().decode("utf-8")
        assert "VelaGuard 云看板" in html
    finally:
        board.stop()
        stack.stop()
