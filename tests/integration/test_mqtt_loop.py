"""Integration tests against local Mosquitto (optional).

Requires broker on localhost:1883:
  docker compose -f deploy/dev/docker-compose.yml up -d
"""

from __future__ import annotations

import json
import socket
import time
import uuid
from typing import Any

import pytest

from ai_bridge.application.handle_request import HandleAiRequest
from ai_bridge.cli.synthetic_publisher import build_request
from ai_bridge.persistence.idempotency import InMemoryIdempotencyStore
from ai_bridge.providers.stub import StubProvider
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


def _wait_for(
    predicate: Any,
    *,
    timeout: float = 5.0,
    interval: float = 0.05,
) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_end_to_end_success(require_broker: None) -> None:
    device_id = "itest-dev"
    client_id = f"ai-bridge-itest-{uuid.uuid4().hex[:8]}"
    store = InMemoryIdempotencyStore()
    responses: list[dict[str, Any]] = []

    bridge = MqttBridgeClient(
        host="localhost",
        port=1883,
        client_id=client_id,
    )
    use_case = HandleAiRequest(
        store=store,
        provider=StubProvider(),
        publish=bridge.publish_json,
        request_timeout_ms=10_000,
        publish_processing=True,
    )
    bridge.set_message_handler(use_case.handle_message)
    bridge.start()
    assert bridge.wait_connected(timeout=5.0)

    request = build_request(device_id=device_id)
    req_id = request["req_id"]
    response_filter = f"vg/{device_id}/ai/response/{req_id}"

    observer = MqttBridgeClient(
        host="localhost",
        port=1883,
        client_id=f"observer-{uuid.uuid4().hex[:8]}",
    )

    def _on_msg(topic: str, payload: bytes) -> None:
        if topic == response_filter:
            responses.append(json.loads(payload.decode("utf-8")))

    observer.set_message_handler(_on_msg)
    observer.start()
    assert observer.wait_connected(timeout=5.0)
    # subscribe via underlying client for exact response topic
    observer._client.subscribe(response_filter, qos=1)
    time.sleep(0.2)

    try:
        bridge.publish_json(f"vg/{device_id}/ai/request", request)
        assert _wait_for(lambda: any(r.get("status") == "success" for r in responses), timeout=5.0)
        success = [r for r in responses if r.get("status") == "success"][-1]
        assert success["req_id"] == req_id
        assert success["device_id"] == device_id
        assert success["result"]["source"] == "stub"
        assert success["result"]["risk_level"] == "low"
        assert success["result"]["possible_causes"] == []
        assert success["result"]["need_shutdown"] is False
        assert success["result"]["confidence"] == 0.0
    finally:
        observer.stop()
        bridge.stop()
