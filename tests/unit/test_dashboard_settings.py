"""Dashboard settings and TLS validation."""

from __future__ import annotations

from typing import Any

import pytest

from dashboard.configuration.settings import Settings


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_dashboard_defaults() -> None:
    settings = _settings()
    assert settings.mqtt_client_id == "vg-dashboard-dev"
    assert settings.http_port == 8080
    assert settings.db_path == "dashboard.db"
    assert settings.mqtt_tls is False
    assert settings.mqtt_ca_path is None


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MQTT_PORT", 0),
        ("MQTT_PORT", 65536),
        ("HTTP_PORT", 0),
        ("HTTP_PORT", 65536),
        ("HISTORY_RETENTION_HOURS", 0),
        ("MESSAGE_BUFFER_LIMIT", 0),
        ("ALARM_EVENT_LIMIT", 0),
        ("CLEANUP_INTERVAL_S", 0),
        ("LOG_LEVEL", "invalid"),
    ],
)
def test_invalid_settings_rejected(name, value) -> None:
    with pytest.raises(ValueError, match=name):
        _settings(**{name: value})


def test_log_level_normalized() -> None:
    assert _settings(LOG_LEVEL=" debug ").log_level == "DEBUG"


def test_tls_accepts_existing_certificate_pair(tmp_path) -> None:
    paths = {}
    for name in ("MQTT_CA_PATH", "MQTT_CLIENT_CERT_PATH", "MQTT_CLIENT_KEY_PATH"):
        path = tmp_path / name
        path.write_text("test certificate placeholder", encoding="utf-8")
        paths[name] = str(path)
    settings = _settings(MQTT_TLS=True, **paths)
    assert settings.mqtt_ca_path == paths["MQTT_CA_PATH"]
    assert settings.mqtt_client_cert_path == paths["MQTT_CLIENT_CERT_PATH"]
    assert settings.mqtt_client_key_path == paths["MQTT_CLIENT_KEY_PATH"]


@pytest.mark.parametrize("name", ["MQTT_CLIENT_CERT_PATH", "MQTT_CLIENT_KEY_PATH"])
def test_tls_rejects_unpaired_existing_certificate(tmp_path, name) -> None:
    path = tmp_path / "certificate"
    path.write_text("test certificate placeholder", encoding="utf-8")
    with pytest.raises(ValueError, match="configured together"):
        _settings(MQTT_TLS=True, **{name: str(path)})


def test_tls_rejects_missing_ca() -> None:
    with pytest.raises(ValueError, match="MQTT_CA_PATH file does not exist"):
        _settings(MQTT_TLS=True, MQTT_CA_PATH="nonexistent-test-ca.crt")


def test_tls_blank_paths_use_system_store() -> None:
    settings = _settings(
        MQTT_TLS=True, MQTT_CA_PATH=" ", MQTT_CLIENT_CERT_PATH="", MQTT_CLIENT_KEY_PATH=" "
    )
    assert settings.mqtt_ca_path is None
    assert settings.mqtt_client_cert_path is None
    assert settings.mqtt_client_key_path is None


def test_plaintext_ignores_stale_certificate_paths() -> None:
    assert not _settings(
        MQTT_TLS=False, MQTT_CA_PATH="missing-ca.crt", MQTT_CLIENT_CERT_PATH="missing.crt"
    ).mqtt_tls
