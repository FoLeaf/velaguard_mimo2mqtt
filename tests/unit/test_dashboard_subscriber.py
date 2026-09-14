"""Unit tests for dashboard MQTT wiring without a broker."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import paho.mqtt.client as mqtt
import pytest

from dashboard.contracts import topics
from dashboard.transport.mqtt import MqttClient
from dashboard.transport.subscriber import build_subscriber


@pytest.fixture
def paho_client() -> Iterator[MagicMock]:
    fake = MagicMock()
    fake.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS
    with patch("dashboard.transport.mqtt.mqtt.Client", return_value=fake):
        yield fake


def _connect(client: MqttClient, fake: MagicMock, reason: int = 0) -> None:
    client._handle_connect(fake, None, {}, reason, None)


@pytest.mark.parametrize("options", [{}, {"subscribe_filters": None}, {"subscribe_filters": []}])
def test_publisher_has_no_implicit_subscriptions(paho_client, options) -> None:
    client = MqttClient(
        host="localhost", port=1883, client_id="synthetic-board-test", **options
    )
    try:
        _connect(client, paho_client)
        assert client.wait_connected(timeout=0)
        paho_client.subscribe.assert_not_called()
        paho_client.publish.assert_not_called()
    finally:
        client.stop()


def test_dashboard_filters_subscribed_on_every_connect(paho_client) -> None:
    client = build_subscriber(
        host="localhost",
        port=1883,
        client_id="vg-dashboard-test",
        username=None,
        password=None,
        on_message=lambda topic, payload: None,
    )
    try:
        _connect(client, paho_client)
        expected = [
            call(topic_filter, qos=qos) for topic_filter, qos in topics.SUBSCRIBE_FILTERS
        ]
        assert paho_client.subscribe.call_args_list == expected
        client._handle_disconnect(paho_client, None, 0)
        assert not client.is_connected()
        _connect(client, paho_client)
        assert paho_client.subscribe.call_args_list == expected * 2
        # The collector never publishes, including on reconnect.
        paho_client.publish.assert_not_called()
    finally:
        client.stop()
    assert not client.is_connected()


def test_failed_connect_does_not_subscribe(paho_client) -> None:
    client = MqttClient(
        host="localhost", port=1883, client_id="vg-dashboard-test",
        subscribe_filters=topics.SUBSCRIBE_FILTERS,
    )
    try:
        _connect(client, paho_client, reason=5)
        assert not client.wait_connected(timeout=0)
        paho_client.subscribe.assert_not_called()
    finally:
        client.stop()


@pytest.mark.parametrize(
    ("kind", "payload", "qos", "retain"),
    [
        ("status", {"device_id": "dev01", "online": True}, 0, True),
        ("telemetry", [{"id": "temp", "value": 35.0}], 0, False),
        ("alarm", {"id": "temp", "state": "raised"}, 1, False),
        ("point_table", {"schema_version": 1, "points": [{"id": "temp"}]}, 1, True),
    ],
)
def test_publisher_preserves_json_and_wire_policy(paho_client, kind, payload, qos, retain) -> None:
    client = MqttClient(host="localhost", port=1883, client_id="synthetic-board-test")
    try:
        info = client.publish_json(f"vg/dev01/{kind}", payload, qos=qos, retain=retain)
        published = paho_client.publish.call_args
        assert published.args[0] == f"vg/dev01/{kind}"
        assert json.loads(published.args[1].decode("utf-8")) == payload
        assert published.kwargs == {"qos": qos, "retain": retain}
        assert info is paho_client.publish.return_value
    finally:
        client.stop()


def test_message_dispatch_runs_off_network_thread(paho_client) -> None:
    received = []
    done = threading.Event()

    def handle(topic: str, payload: bytes) -> None:
        received.append((topic, payload, threading.current_thread().name))
        done.set()

    client = MqttClient(
        host="localhost", port=1883, client_id="vg-dashboard-test", on_message=handle
    )
    try:
        message = SimpleNamespace(topic="vg/dev01/status", payload=b'{"online":true}')
        client._handle_message(paho_client, None, message)
        assert done.wait(timeout=2)
        assert received[0][:2] == (message.topic, message.payload)
        assert received[0][2].startswith("dashboard-mqtt")
    finally:
        client.stop()


def test_handler_error_is_logged_without_escaping(paho_client, caplog) -> None:
    def fail(topic: str, payload: bytes) -> None:
        raise ValueError("invalid test message")

    client = MqttClient(host="localhost", port=1883, client_id="vg-dashboard-test")
    try:
        client._dispatch_message(fail, "vg/dev01/status", b"{}")
        assert "mqtt_message_handler_error" in caplog.text
    finally:
        client.stop()
