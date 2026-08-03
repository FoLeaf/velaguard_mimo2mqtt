"""Env-driven bridge settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime configuration for the AI Bridge process."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mqtt_host: str = Field(default="localhost", alias="MQTT_HOST")
    mqtt_port: int = Field(default=1883, alias="MQTT_PORT")
    mqtt_username: str | None = Field(default=None, alias="MQTT_USERNAME")
    mqtt_password: str | None = Field(default=None, alias="MQTT_PASSWORD")
    mqtt_client_id: str = Field(default="ai-bridge-dev", alias="MQTT_CLIENT_ID")
    request_timeout_ms: int = Field(default=30_000, alias="REQUEST_TIMEOUT_MS")
    provider: Literal["stub", "mimo"] = Field(default="stub", alias="PROVIDER")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    stub_delay_ms: int = Field(default=0, alias="STUB_DELAY_MS")

    @field_validator("mqtt_port")
    @classmethod
    def _port_range(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("MQTT_PORT must be between 1 and 65535")
        return value

    @field_validator("request_timeout_ms")
    @classmethod
    def _timeout_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("REQUEST_TIMEOUT_MS must be positive")
        return value

    @field_validator("stub_delay_ms")
    @classmethod
    def _stub_delay_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("STUB_DELAY_MS must be non-negative")
        return value

    @field_validator("log_level")
    @classmethod
    def _log_level_upper(cls, value: str) -> str:
        normalized = value.strip().upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if normalized not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}")
        return normalized

    @property
    def request_timeout_s(self) -> float:
        return self.request_timeout_ms / 1000.0


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    return Settings()
