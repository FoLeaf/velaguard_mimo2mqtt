"""Unit tests for secret redaction helpers."""

from __future__ import annotations

from dashboard.observability.logging import redact_secrets


def test_redact_dict_keys() -> None:
    data = {
        "device_id": "dev01",
        "password": "super-secret",
        "mqtt_password": "also-secret",
        "api_key": "test-key",
        "nested": {"token": "abc", "ok": 1},
    }
    redacted = redact_secrets(data)
    assert redacted["device_id"] == "dev01"
    assert redacted["password"] == "***"
    assert redacted["mqtt_password"] == "***"
    assert redacted["api_key"] == "***"
    assert redacted["nested"]["token"] == "***"
    assert redacted["nested"]["ok"] == 1


def test_redact_string_patterns() -> None:
    text = "Authorization: Bearer abc.def.ghi password=hunter2"
    redacted = redact_secrets(text)
    assert "abc.def.ghi" not in redacted
    assert "hunter2" not in redacted
    assert "***" in redacted


def test_redact_prefixed_secrets() -> None:
    data = {
        "service_api_key": "sk-live-secret-value",
        "SERVICE_API_KEY": "sk-other-case-value",
        "device-token": "device-token-value",
    }
    redacted = redact_secrets(data)
    assert redacted["service_api_key"] == "***"
    assert redacted["SERVICE_API_KEY"] == "***"
    assert redacted["device-token"] == "***"
    assert "sk-live-secret-value" not in str(redacted)


def test_redact_prefixed_secrets_in_plain_text() -> None:
    text = "SERVICE_API_KEY=sk-plain-text-value MQTT_PASSWORD=broker-password status=ok"
    redacted = redact_secrets(text)
    assert "sk-plain-text-value" not in redacted
    assert "broker-password" not in redacted
    assert "***" in redacted


def test_redact_bearer_header_value_in_text() -> None:
    text = "Authorization: Bearer test-token-123"
    redacted = redact_secrets(text)
    assert "test-token-123" not in redacted
    assert "Bearer" not in redacted  # whole token consumed by redaction
    assert "***" in redacted
