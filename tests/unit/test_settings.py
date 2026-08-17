"""Unit tests for AI Bridge settings validation."""

from __future__ import annotations

from typing import Any

import pytest

from ai_bridge.configuration.settings import Settings


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, PROVIDER="stub", **overrides)  # type: ignore[call-arg]


def test_runtime_defaults() -> None:
    settings = _settings()
    assert settings.skills_dir is None
    assert settings.diagnosis_skill == "industrial_fault_diagnosis"
    assert settings.fallback_enabled is True


def test_custom_runtime_values() -> None:
    settings = _settings(
        SKILLS_DIR="/tmp/skills",
        DIAGNOSIS_SKILL="my_skill_1",
        FALLBACK_ENABLED=False,
    )
    assert settings.skills_dir == "/tmp/skills"
    assert settings.diagnosis_skill == "my_skill_1"
    assert settings.fallback_enabled is False


@pytest.mark.parametrize("bad", ["", " ", "../x", "a-b", "A", "a b", "a.b"])
def test_diagnosis_skill_rejects_invalid_names(bad: str) -> None:
    with pytest.raises(ValueError):
        _settings(DIAGNOSIS_SKILL=bad)


def test_tls_defaults_off() -> None:
    settings = _settings()
    assert settings.mqtt_tls is False
    assert settings.mqtt_ca_path is None
    assert settings.mqtt_client_cert_path is None
    assert settings.mqtt_client_key_path is None


def test_tls_enabled_with_existing_paths(tmp_path) -> None:
    ca = tmp_path / "ca.crt"
    cert = tmp_path / "client.crt"
    key = tmp_path / "client.key"
    for path in (ca, cert, key):
        path.write_text("x", encoding="utf-8")
    settings = _settings(
        MQTT_TLS=True,
        MQTT_CA_PATH=str(ca),
        MQTT_CLIENT_CERT_PATH=str(cert),
        MQTT_CLIENT_KEY_PATH=str(key),
    )
    assert settings.mqtt_tls is True
    assert settings.mqtt_ca_path == str(ca)
    assert settings.mqtt_client_cert_path == str(cert)
    assert settings.mqtt_client_key_path == str(key)


@pytest.mark.parametrize(
    "overrides",
    [
        {"MQTT_CLIENT_CERT_PATH": "cert.pem"},
        {"MQTT_CLIENT_KEY_PATH": "client.key"},
        {
            "MQTT_CLIENT_CERT_PATH": "cert.pem",
            "MQTT_CLIENT_KEY_PATH": "missing.key",
        },
        {"MQTT_CA_PATH": "missing-ca.crt"},
    ],
)
def test_tls_on_rejects_unpaired_or_missing_paths(overrides) -> None:
    # A key/cert placeholder that exists keeps the pairing check in focus.
    with pytest.raises(ValueError):
        _settings(MQTT_TLS=True, **overrides)


def test_tls_off_ignores_certificate_paths() -> None:
    # Plaintext dev posture: stale/missing cert paths must not block startup.
    settings = _settings(
        MQTT_TLS=False,
        MQTT_CA_PATH="missing-ca.crt",
        MQTT_CLIENT_CERT_PATH="cert.pem",
        MQTT_CLIENT_KEY_PATH="client.key",
    )
    assert settings.mqtt_tls is False


def test_tls_blank_paths_treated_as_unset(tmp_path) -> None:
    settings = _settings(MQTT_TLS=True, MQTT_CA_PATH="  ")
    assert settings.mqtt_ca_path is None
    assert settings.mqtt_tls is True
