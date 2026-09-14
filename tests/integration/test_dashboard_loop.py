"""Dashboard integration: synthetic board → collector → HTTP API (optional).

Requires broker on localhost:1883 (override with TEST_MQTT_HOST/TEST_MQTT_PORT):
  docker compose -f deploy/dev/docker-compose.yml up -d mosquitto
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

import pytest

from dashboard.application.collector import Collector
from dashboard.contracts import topics
from dashboard.http.server import DashboardHttpServer
from dashboard.storage.db import DashboardStore
from dashboard.tools.synthetic_board import (
    DEMO_POINT_TABLE,
    build_alarm,
    build_status,
    build_telemetry,
)
from dashboard.transport.mqtt import MqttClient
from dashboard.transport.subscriber import build_subscriber

pytestmark = pytest.mark.integration

MQTT_HOST = os.environ.get("TEST_MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("TEST_MQTT_PORT", "1883"))


def _broker_available(timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((MQTT_HOST, MQTT_PORT), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def require_broker() -> None:
    if not _broker_available():
        pytest.skip(f"MQTT broker not available on {MQTT_HOST}:{MQTT_PORT}")


class _DashboardStack:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DashboardStore(str(Path(self.tmp.name) / "dash.db"))
        self.collector = Collector(self.store, message_buffer_limit=100)
        self.http = DashboardHttpServer(self.store, "127.0.0.1", 0)
        self.port = self.http.port
        self.subscriber = build_subscriber(
            host=MQTT_HOST,
            port=MQTT_PORT,
            client_id=f"dashboard-itest-{uuid.uuid4().hex[:8]}",
            username=None,
            password=None,
            on_message=self.collector.handle_message,
        )

    def start_subscriber(self) -> None:
        self.subscriber.start()
        assert self.subscriber.wait_connected(timeout=5)

    def stop(self) -> None:
        self.subscriber.stop()
        self.http.stop()
        self.store.close()
        self.tmp.cleanup()


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as res:
        return json.loads(res.read().decode("utf-8"))


def _publish(client: MqttClient, topic: str, payload, *, qos: int, retain: bool = False) -> None:
    client.publish_json(topic, payload, qos=qos, retain=retain).wait_for_publish(timeout=5)


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_synthetic_board_to_dashboard_api(require_broker: None) -> None:
    stack = _DashboardStack()
    device_id = f"itest-{uuid.uuid4().hex[:6]}"
    root = f"vg/{device_id}"

    board = MqttClient(
        host=MQTT_HOST,
        port=MQTT_PORT,
        client_id=f"synthetic-board-itest-{uuid.uuid4().hex[:6]}",
    )
    try:
        stack.http.start()
        board.start()
        assert board.wait_connected(timeout=5.0)
        # Publish snapshots before the collector starts to verify retained delivery.
        _publish(board, f"{root}/point_table", DEMO_POINT_TABLE,
                 qos=topics.POINT_TABLE_QOS, retain=topics.POINT_TABLE_RETAINED)
        _publish(board, f"{root}/status", build_status(device_id, True, 1000),
                 qos=topics.STATUS_QOS, retain=topics.STATUS_RETAINED)
        stack.start_subscriber()
        assert _wait_for(
            lambda: any(
                d["device_id"] == device_id and d["online"] and d["point_count"] == 3
                for d in stack.store.list_devices()
            )
        )
        _publish(board, f"{root}/telemetry", build_telemetry(tick=0),
                 qos=topics.TELEMETRY_QOS)
        _publish(board, f"{root}/alarm",
                 build_alarm(device_id, "temp", "threshold_high", "raised", 36.5, 35.0, 1),
                 qos=topics.ALARM_QOS)

        assert _wait_for(
            lambda: {"status", "telemetry", "alarm", "point_table"} <= {
                message["kind"] for message in stack.store.list_messages()
                if message["device_id"] == device_id
            },
        )

        devices = _get_json(f"http://127.0.0.1:{stack.port}/api/devices")["devices"]
        mine = next(d for d in devices if d["device_id"] == device_id)
        assert mine["online"] is True
        assert mine["point_count"] == 3

        detail = _get_json(f"http://127.0.0.1:{stack.port}/api/devices/{device_id}")
        assert {p["id"] for p in detail["points"]} == {"temp", "humidity", "flood"}
        temp_point = next(p for p in detail["points"] if p["id"] == "temp")
        assert temp_point["name"] == "温度"
        assert temp_point["latest"]["value"] == build_telemetry(0)[0]["value"]

        alarms = _get_json(f"http://127.0.0.1:{stack.port}/api/alarms")
        active = [a for a in alarms["active"] if a["device_id"] == device_id]
        assert len(active) == 1
        assert active[0]["payload"]["state"] == "raised"

        messages = _get_json(f"http://127.0.0.1:{stack.port}/api/messages")["messages"]
        own_messages = [m for m in messages if m["device_id"] == device_id]
        assert all(m["quarantine_reason"] is None for m in own_messages)
        kinds = {m["kind"] for m in own_messages}
        assert {"status", "telemetry", "alarm", "point_table"} <= kinds

        history = _get_json(
            f"http://127.0.0.1:{stack.port}/api/devices/{device_id}/history?point=temp&minutes=5"
        )
        assert len(history["samples"]) >= 1

        _publish(board, f"{root}/alarm",
                 build_alarm(device_id, "temp", "threshold_high", "cleared", 30.0, 35.0, 1),
                 qos=topics.ALARM_QOS)
        assert _wait_for(
            lambda: not any(
                a["device_id"] == device_id for a in stack.store.list_alarms()["active"]
            )
        )
        _publish(board, f"{root}/status", build_status(device_id, False, 2000),
                 qos=topics.STATUS_QOS, retain=topics.STATUS_RETAINED)
        assert _wait_for(lambda: stack.store.get_device(device_id)["online"] is False)

        # Static page served for the browser UI.
        with urllib.request.urlopen(
            f"http://127.0.0.1:{stack.port}/", timeout=5
        ) as res:
            html = res.read().decode("utf-8")
        assert "VelaGuard 云看板" in html
    finally:
        try:
            if board.is_connected():
                for kind in ("point_table", "status"):
                    board._client.publish(
                        f"{root}/{kind}", b"", qos=1, retain=True
                    ).wait_for_publish(timeout=5)
        finally:
            board.stop()
            stack.stop()
