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
