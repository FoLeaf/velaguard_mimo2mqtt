"""Unit tests for dashboard subscriber wiring and MqttBridgeClient
subscribe_filters generalization (no network)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ai_bridge.contracts.topics import AI_QOS, REQUEST_TOPIC_FILTER
from ai_bridge.transport.mqtt.client import MqttBridgeClient
from dashboard.contracts import topics
from dashboard.transport.subscriber import build_subscriber


def _patch_paho() -> tuple[MagicMock, object]:
    fake = MagicMock()
    return fake, patch(
        "ai_bridge.transport.mqtt.client.mqtt.Client", return_value=fake
    )


def _connect(client: MqttBridgeClient) -> None:
    # paho v2 callback signature: (client, userdata, flags, reason_code, props)
    client._handle_connect(client._client, None, {}, 0, None)


def test_default_subscribe_behavior_unchanged() -> None:
    """The AI Bridge default subscription must stay byte-identical."""
    fake, patcher = _patch_paho()
    with patcher:
        bridge = MqttBridgeClient(
            host="localhost", port=1883, client_id="ai-bridge-test"
        )
    _connect(bridge)
    fake.subscribe.assert_called_once_with(REQUEST_TOPIC_FILTER, qos=AI_QOS)
    fake.publish.assert_not_called()


def test_dashboard_filters_subscribed() -> None:
    fake, patcher = _patch_paho()
    with patcher:
        client = build_subscriber(
            host="localhost",
            port=1883,
            client_id="vg-dashboard-test",
            username=None,
            password=None,
            on_message=lambda topic, payload: None,
        )
    _connect(client)
    calls = {
        c.args[0]: c.kwargs.get("qos", c.args[1] if len(c.args) > 1 else None)
        for c in fake.subscribe.call_args_list
    }
    assert calls == {
        topics.STATUS_FILTER: 0,
        topics.TELEMETRY_FILTER: 0,
        topics.ALARM_FILTER: 1,
        topics.POINT_TABLE_FILTER: 1,
    }
    # Boundary V5: building the read-only collector client never publishes.
    fake.publish.assert_not_called()
