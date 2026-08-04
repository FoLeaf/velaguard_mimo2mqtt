"""Agent Runtime: skill loading, prompt building, context normalization, fallback."""

from ai_bridge.runtime.fallback import build_fallback_diagnosis
from ai_bridge.runtime.json_validator import (
    ContextBundle,
    normalize_diagnosis_context,
)
from ai_bridge.runtime.prompt_builder import (
    MAX_USER_CONTENT_CHARS,
    build_diagnosis_messages,
    build_diagnosis_system_prompt,
    build_diagnosis_user_content,
)
from ai_bridge.runtime.skill_manager import DEFAULT_DIAGNOSIS_SKILL, SkillManager

__all__ = [
    "ContextBundle",
    "DEFAULT_DIAGNOSIS_SKILL",
    "MAX_USER_CONTENT_CHARS",
    "SkillManager",
    "build_diagnosis_messages",
    "build_diagnosis_system_prompt",
    "build_diagnosis_user_content",
    "build_fallback_diagnosis",
    "normalize_diagnosis_context",
]
