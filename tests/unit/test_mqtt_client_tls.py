"""Unit tests for MqttClient TLS wiring (no network)."""

from __future__ import annotations

from unittest.mock import patch

import paho.mqtt.client as mqtt

from dashboard.transport.mqtt import MqttClient


def _client(**kwargs: object) -> MqttClient:
    return MqttClient(
        host="localhost",
        port=8883,
        client_id="vg-dashboard-test",
        **kwargs,  # type: ignore[arg-type]
    )


def test_tls_disabled_does_not_call_tls_set() -> None:
    with patch.object(mqtt.Client, "tls_set") as tls_set:
        _client(tls_enabled=False, ca_path="ca.crt")
    tls_set.assert_not_called()


def test_tls_enabled_with_ca_passes_ca_certs() -> None:
    with patch.object(mqtt.Client, "tls_set") as tls_set:
        _client(tls_enabled=True, ca_path="ca.crt")
    tls_set.assert_called_once_with(
        ca_certs="ca.crt",
        certfile=None,
        keyfile=None,
    )


def test_tls_enabled_without_ca_uses_system_store() -> None:
    with patch.object(mqtt.Client, "tls_set") as tls_set:
        _client(tls_enabled=True)
    tls_set.assert_called_once_with(
        ca_certs=None,
        certfile=None,
        keyfile=None,
    )


def test_tls_enabled_with_mtls_passes_cert_and_key() -> None:
    with patch.object(mqtt.Client, "tls_set") as tls_set:
        _client(
            tls_enabled=True,
            ca_path="ca.crt",
            client_cert_path="client.crt",
            client_key_path="client.key",
        )
    tls_set.assert_called_once_with(
        ca_certs="ca.crt",
        certfile="client.crt",
        keyfile="client.key",
    )


def test_blank_ca_path_falls_back_to_system_store() -> None:
    with patch.object(mqtt.Client, "tls_set") as tls_set:
        _client(tls_enabled=True, ca_path="")
    tls_set.assert_called_once_with(
        ca_certs=None,
        certfile=None,
        keyfile=None,
    )
