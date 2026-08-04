"""Bounded prompt assembly for ``type=diagnosis`` provider calls."""

from __future__ import annotations

import json
from typing import Any

from ai_bridge.contracts.request import AiRequest
from ai_bridge.observability.logging import get_logger
from ai_bridge.runtime.json_validator import (
    TRUNCATED_MARKER,
    normalize_diagnosis_context,
    truncate_json_value,
)

logger = get_logger(__name__)

MAX_USER_CONTENT_CHARS = 8192
_IDENTITY_MAX_CHARS = 256

DIAGNOSIS_LANGUAGE_INSTRUCTIONS = (
    "Language requirement: Use Simplified Chinese as the primary language for "
    "all explanatory diagnosis fields: diagnosis_summary, possible_causes, "
    "recommended_actions, reasons, and recommendations. Translate English "
    "explanations from the input context into Chinese instead of copying them "
    "as the response language. Keep device IDs, field names, units, error "
    "codes, model/product names, code expressions, and necessary technical "
    "terms in their original form when useful. Mixed Chinese and technical "
    "terms are allowed, but do not return English prose as the default. "
)

DIAGNOSIS_SCHEMA_INSTRUCTIONS = (
    "Return ONLY a single JSON object (no markdown, no text outside the "
    "object) matching exactly this schema: "
    '{"diagnosis_summary": string (required, non-empty), '
    '"risk_level": "low"|"medium"|"high" (required), '
    '"possible_causes": [string] (required, empty list allowed), '
    '"recommended_actions": [string] (required, empty list allowed), '
    '"need_shutdown": boolean (required), '
    '"confidence": number between 0 and 1 (optional), '
    '"reasons": [string] (optional), '
    '"recommendations": [string] (optional)}. '
    "Unknown extra keys are allowed. The diagnosis is advisory only; do not "
    "include direct device-control instructions."
)


def build_diagnosis_system_prompt(skill_text: str) -> str:
    """Append fixed JSON/schema instructions to a skill text."""
    return f"{skill_text.strip()}\n\n{DIAGNOSIS_LANGUAGE_INSTRUCTIONS}\n{DIAGNOSIS_SCHEMA_INSTRUCTIONS}"


def _bounded_identity(value: str, *, field: str) -> str:
    """Bound identity fields so the user message limit is unconditional."""
    if len(value) <= _IDENTITY_MAX_CHARS:
        return value
    logger.warning(
        "prompt_identity_truncated field=%s chars=%s limit=%s",
        field,
        len(value),
        _IDENTITY_MAX_CHARS,
    )
    return value[:_IDENTITY_MAX_CHARS] + TRUNCATED_MARKER


def build_diagnosis_user_content(request: AiRequest) -> str:
    """Build the bounded user message for a diagnosis request."""
    bundle = normalize_diagnosis_context(request.raw.get("context"))
    device_id = _bounded_identity(request.device_id, field="device_id")
    req_id = _bounded_identity(request.req_id, field="req_id")
    data: dict[str, Any] = {
        "device_id": device_id,
        "req_id": req_id,
        "type": request.type,
        "context": bundle.to_dict(),
    }
    if bundle.missing:
        data["context_notes"] = [f"{name} missing" for name in bundle.missing]

    serialized = json.dumps(
        data, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    if len(serialized) <= MAX_USER_CONTENT_CHARS:
        return serialized

    logger.warning(
        "prompt_user_truncated device_id=%s req_id=%s limit=%s",
        request.device_id,
        request.req_id,
        MAX_USER_CONTENT_CHARS,
    )

    # Prefer a structurally valid, smaller context over dropping the request.
    compact = dict(data)
    if isinstance(compact.get("context"), dict):
        compact["context"] = truncate_json_value(
            compact["context"],
            max(0, MAX_USER_CONTENT_CHARS - 160),
            field="context",
        )
    compact.pop("context_notes", None)
    serialized = json.dumps(
        compact, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    if len(serialized) <= MAX_USER_CONTENT_CHARS:
        return serialized

    # Last resort: bounded raw request JSON embedded as a string (v1 shape).
    body = json.dumps(request.raw, ensure_ascii=True, sort_keys=True)
    if len(body) > MAX_USER_CONTENT_CHARS - 160:
        body = body[: MAX_USER_CONTENT_CHARS - 160] + TRUNCATED_MARKER
    # JSON string escaping can expand the embedded body beyond its char count,
    # so shrink until the serialized message actually fits the bound.
    while True:
        candidate = json.dumps(
            {
                "device_id": device_id,
                "req_id": req_id,
                "type": request.type,
                "request": body,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        if len(candidate) <= MAX_USER_CONTENT_CHARS or len(body) <= 1:
            return candidate
        body = body[: max(1, len(body) // 2)] + TRUNCATED_MARKER


def build_diagnosis_messages(
    request: AiRequest,
    skill_text: str,
) -> list[dict[str, str]]:
    """Build the complete bounded system/user message pair."""
    return [
        {"role": "system", "content": build_diagnosis_system_prompt(skill_text)},
        {"role": "user", "content": build_diagnosis_user_content(request)},
    ]
