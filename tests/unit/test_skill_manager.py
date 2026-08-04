"""Unit tests for SkillManager."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_bridge.runtime.skill_manager import DEFAULT_DIAGNOSIS_SKILL, SkillManager


def test_loads_skill_file(tmp_path) -> None:
    (tmp_path / "my_skill.md").write_text(
        "# My Skill\n\nschema instructions",
        encoding="utf-8",
    )
    manager = SkillManager(tmp_path)
    text = manager.load("my_skill")
    assert text == "# My Skill\n\nschema instructions"


def test_load_caches(tmp_path) -> None:
    path = tmp_path / "cached.md"
    path.write_text("v1", encoding="utf-8")
    manager = SkillManager(tmp_path)
    assert manager.load("cached") == "v1"
    path.write_text("v2", encoding="utf-8")
    assert manager.load("cached") == "v1"


def test_missing_skill_falls_back_to_default(tmp_path) -> None:
    manager = SkillManager(tmp_path)
    assert manager.load("missing") == DEFAULT_DIAGNOSIS_SKILL


def test_empty_skill_falls_back_to_default(tmp_path) -> None:
    (tmp_path / "empty.md").write_text("   ", encoding="utf-8")
    manager = SkillManager(tmp_path)
    assert manager.load("empty") == DEFAULT_DIAGNOSIS_SKILL


def test_unreadable_skill_falls_back_to_default(tmp_path) -> None:
    # A directory in place of the .md file makes read_text raise OSError.
    (tmp_path / "blocked.md").mkdir()
    manager = SkillManager(tmp_path)
    assert manager.load("blocked") == DEFAULT_DIAGNOSIS_SKILL


@pytest.mark.parametrize("name", ["", "../evil", "a/b", "a b", "UPPER", ".hidden"])
def test_invalid_name_rejected(tmp_path, name: str) -> None:
    manager = SkillManager(tmp_path)
    with pytest.raises(ValueError):
        manager.load(name)


def test_default_skill_requires_simplified_chinese() -> None:
    assert "Simplified Chinese" in DEFAULT_DIAGNOSIS_SKILL


def test_checked_in_diagnosis_skill_requires_simplified_chinese() -> None:
    skill_path = Path(__file__).resolve().parents[2] / "ai_bridge" / "skills" / "industrial_fault_diagnosis.md"
    assert "Simplified Chinese" in skill_path.read_text(encoding="utf-8")
