"""Env-driven bridge settings."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_SKILL_NAME_RE = re.compile(r"^[a-z0-9_]+$")


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

    # Diagnosis skill / prompt runtime settings.
    skills_dir: str | None = Field(default=None, alias="SKILLS_DIR")
    diagnosis_skill: str = Field(
        default="industrial_fault_diagnosis",
        alias="DIAGNOSIS_SKILL",
    )
    fallback_enabled: bool = Field(default=True, alias="FALLBACK_ENABLED")

    # MiMo HTTPS provider settings (OpenAI-compatible chat completions).
    mimo_base_url: str = Field(
        default="https://token-plan-cn.xiaomimimo.com/v1",
        alias="MIMO_BASE_URL",
    )
    mimo_model: str = Field(default="mimo-v2.5", alias="MIMO_MODEL")
    mimo_api_key: str | None = Field(default=None, alias="MIMO_API_KEY")
    mimo_http_timeout_ms: int = Field(default=15_000, alias="MIMO_HTTP_TIMEOUT_MS")
    mimo_max_retries: int = Field(default=2, alias="MIMO_MAX_RETRIES")
    mimo_retry_backoff_ms: int = Field(default=500, alias="MIMO_RETRY_BACKOFF_MS")

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

    @field_validator("diagnosis_skill")
    @classmethod
    def _diagnosis_skill_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or not _SKILL_NAME_RE.fullmatch(normalized):
            raise ValueError("DIAGNOSIS_SKILL must match ^[a-z0-9_]+$")
        return normalized

    @field_validator("mimo_base_url")
    @classmethod
    def _mimo_base_url_strip(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized:
            raise ValueError("MIMO_BASE_URL must not be empty")
        return normalized

    @field_validator("mimo_model")
    @classmethod
    def _mimo_model_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("MIMO_MODEL must not be empty")
        return normalized

    @field_validator("mimo_api_key")
    @classmethod
    def _mimo_api_key_no_default(cls, value: str | None) -> str | None:
        # A set-but-blank key is treated the same as unset so build_provider
        # can fail fast with a clear message when PROVIDER=mimo.
        if value is not None and not value.strip():
            return None
        return value

    @field_validator("mimo_http_timeout_ms")
    @classmethod
    def _mimo_timeout_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("MIMO_HTTP_TIMEOUT_MS must be positive")
        return value

    @field_validator("mimo_max_retries")
    @classmethod
    def _mimo_retries_bounded(cls, value: int) -> int:
        if not 0 <= value <= 5:
            raise ValueError("MIMO_MAX_RETRIES must be between 0 and 5")
        return value

    @field_validator("mimo_retry_backoff_ms")
    @classmethod
    def _mimo_backoff_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("MIMO_RETRY_BACKOFF_MS must be non-negative")
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
