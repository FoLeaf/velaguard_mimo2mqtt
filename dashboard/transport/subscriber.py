"""MQTT subscriber wiring: reuses the AI Bridge paho client infra.

The collector is read-only: it only subscribes to device-published topics and
never publishes to ``vg/{device_id}/...`` (boundary V5).
"""

from __future__ import annotations

from collections.abc import Callable

from ai_bridge.transport.mqtt.client import MqttBridgeClient
from dashboard.contracts import topics

MessageHandler = Callable[[str, bytes], None]


def build_subscriber(
    *,
    host: str,
    port: int,
    client_id: str,
    username: str | None,
    password: str | None,
    tls_enabled: bool = False,
    ca_path: str | None = None,
    client_cert_path: str | None = None,
    client_key_path: str | None = None,
    on_message: MessageHandler,
    worker_threads: int = 4,
) -> MqttBridgeClient:
    """Create the collector MQTT client subscribed to the four dashboard filters."""
    return MqttBridgeClient(
        host=host,
        port=port,
        client_id=client_id,
        username=username,
        password=password,
        on_message=on_message,
        worker_threads=worker_threads,
        tls_enabled=tls_enabled,
        ca_path=ca_path,
        client_cert_path=client_cert_path,
        client_key_path=client_key_path,
        subscribe_filters=list(topics.SUBSCRIBE_FILTERS),
    )
