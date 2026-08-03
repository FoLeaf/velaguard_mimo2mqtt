"""Unit tests for secret redaction helpers."""

from __future__ import annotations

from ai_bridge.observability.logging import redact_secrets


def test_redact_dict_keys() -> None:
    data = {
        "device_id": "dev01",
        "password": "super-secret",
        "mqtt_password": "also-secret",
        "api_key": "mimo-key",
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
