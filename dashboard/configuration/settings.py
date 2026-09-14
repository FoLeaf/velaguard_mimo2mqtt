"""Env-driven dashboard settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime configuration for the dashboard collector process."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MQTT connection.
    mqtt_host: str = Field(default="localhost", alias="MQTT_HOST")
    mqtt_port: int = Field(default=1883, alias="MQTT_PORT")
    mqtt_username: str | None = Field(default=None, alias="MQTT_USERNAME")
    mqtt_password: str | None = Field(default=None, alias="MQTT_PASSWORD")
    mqtt_client_id: str = Field(default="vg-dashboard-dev", alias="MQTT_CLIENT_ID")
    mqtt_tls: bool = Field(default=False, alias="MQTT_TLS")
    mqtt_ca_path: str | None = Field(default=None, alias="MQTT_CA_PATH")
    mqtt_client_cert_path: str | None = Field(
        default=None, alias="MQTT_CLIENT_CERT_PATH"
    )
    mqtt_client_key_path: str | None = Field(
        default=None, alias="MQTT_CLIENT_KEY_PATH"
    )

    # Read-only HTTP surface.
    http_host: str = Field(default="0.0.0.0", alias="HTTP_HOST")
    http_port: int = Field(default=8080, alias="HTTP_PORT")

    # Storage.
    db_path: str = Field(default="dashboard.db", alias="DB_PATH")
    history_retention_hours: int = Field(default=24, alias="HISTORY_RETENTION_HOURS")
    message_buffer_limit: int = Field(default=500, alias="MESSAGE_BUFFER_LIMIT")
    alarm_event_limit: int = Field(default=5000, alias="ALARM_EVENT_LIMIT")
    cleanup_interval_s: int = Field(default=600, alias="CLEANUP_INTERVAL_S")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator(
        "mqtt_ca_path", "mqtt_client_cert_path", "mqtt_client_key_path", mode="before"
    )
    @classmethod
    def _normalize_certificate_path(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def _validate_ranges(self) -> Settings:
        if not 1 <= self.mqtt_port <= 65535:
            raise ValueError("MQTT_PORT must be between 1 and 65535")
        if not 1 <= self.http_port <= 65535:
            raise ValueError("HTTP_PORT must be between 1 and 65535")
        if self.history_retention_hours <= 0:
            raise ValueError("HISTORY_RETENTION_HOURS must be positive")
        if self.message_buffer_limit <= 0:
            raise ValueError("MESSAGE_BUFFER_LIMIT must be positive")
        if self.alarm_event_limit <= 0:
            raise ValueError("ALARM_EVENT_LIMIT must be positive")
        if self.cleanup_interval_s <= 0:
            raise ValueError("CLEANUP_INTERVAL_S must be positive")
        if self.mqtt_tls:
            if bool(self.mqtt_client_cert_path) != bool(self.mqtt_client_key_path):
                raise ValueError(
                    "MQTT_CLIENT_CERT_PATH and MQTT_CLIENT_KEY_PATH must be configured together"
                )
            for name, value in (
                ("MQTT_CA_PATH", self.mqtt_ca_path),
                ("MQTT_CLIENT_CERT_PATH", self.mqtt_client_cert_path),
                ("MQTT_CLIENT_KEY_PATH", self.mqtt_client_key_path),
            ):
                if value is not None and not Path(value).is_file():
                    raise ValueError(f"{name} file does not exist: {value}")
        level = self.log_level.strip().upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if level not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}")
        self.log_level = level
        return self


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    return Settings()
