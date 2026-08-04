"""Skill file loading for provider prompt assembly.

Loads markdown skill files from a configurable directory, validates file
names against a strict whitelist, caches loaded text, and falls back to a
built-in default prompt when a skill file is missing or unreadable so the
bridge stays available.
"""

from __future__ import annotations

import re
from pathlib import Path

from ai_bridge.observability.logging import get_logger

logger = get_logger(__name__)

_SKILL_NAME_RE = re.compile(r"^[a-z0-9_]+$")

DEFAULT_DIAGNOSIS_SKILL = """You are a VelaGuard industrial fault diagnosis assistant.

Analyze the device event and sensor context and produce a structured diagnosis.
Use Simplified Chinese as the primary language for diagnosis_summary, possible_causes, recommended_actions, reasons, and recommendations. Keep device IDs, field names, units, error codes, model/product names, code expressions, and necessary technical terms in their original form when useful.
Your output is advisory only: the device owner validates risk and confirms any
action locally. Never instruct the device to write registers, change
configuration, clear alarms, or control actuators directly.

Input context is provided as JSON with device_id, req_id, type, a context
object (event, history, rules, device) and optional context_notes listing
missing sections. When a section is missing or empty, say so explicitly in the
summary instead of inventing data.

Return ONLY a single JSON object (no markdown, no text outside the object)
matching exactly this schema:
{"diagnosis_summary": string (required, non-empty),
 "risk_level": "low"|"medium"|"high" (required),
 "possible_causes": [string] (required, empty list allowed),
 "recommended_actions": [string] (required, empty list allowed),
 "need_shutdown": boolean (required),
 "confidence": number between 0 and 1 (optional),
 "reasons": [string] (optional),
 "recommendations": [string] (optional)}

Set need_shutdown to true only for a risk that justifies stopping the device.
Use risk_level high for critical/error severity, medium for warnings, low
otherwise. Prefer conservative, non-shutdown recommendations when evidence is
missing.
"""


class SkillManager:
    """Loads and caches skill markdown files from one directory."""

    def __init__(self, skills_dir: str | Path) -> None:
        self._skills_dir = Path(skills_dir)
        self._cache: dict[str, str] = {}

    def load(self, name: str) -> str:
        """Return skill text for ``name``, falling back to the built-in prompt.

        Raises ``ValueError`` for names outside the ``^[a-z0-9_]+$`` whitelist
        (path traversal is rejected, never treated as a fallback).
        """
        if not _SKILL_NAME_RE.fullmatch(name):
            raise ValueError(f"invalid skill name: {name!r}")

        cached = self._cache.get(name)
        if cached is not None:
            return cached

        path = self._skills_dir / f"{name}.md"
        try:
            text = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            logger.warning(
                "skill_fallback name=%s dir=%s reason=unreadable",
                name,
                str(self._skills_dir),
            )
            text = DEFAULT_DIAGNOSIS_SKILL

        if not text:
            logger.warning(
                "skill_fallback name=%s dir=%s reason=empty",
                name,
                str(self._skills_dir),
            )
            text = DEFAULT_DIAGNOSIS_SKILL
        else:
            logger.info(
                "skill_loaded name=%s bytes=%s",
                name,
                len(text.encode("utf-8")),
            )

        self._cache[name] = text
        return text
