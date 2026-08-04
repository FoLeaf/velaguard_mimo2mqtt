"""Fallback diagnosis result when MiMo is unavailable."""

from __future__ import annotations

from typing import Any

from ai_bridge.contracts.request import AiRequest
from ai_bridge.observability.logging import get_logger
from ai_bridge.providers.schema import validate_diagnosis_result
from ai_bridge.runtime.json_validator import normalize_diagnosis_context

logger = get_logger(__name__)

_SEVERITY_RISK = {
    "critical": "high",
    "error": "high",
    "warning": "medium",
}


def _risk_from_event(event: dict[str, Any] | None) -> str:
    if not isinstance(event, dict):
        return "low"
    severity = event.get("severity")
    if not isinstance(severity, str):
        return "low"
    return _SEVERITY_RISK.get(severity.strip().lower(), "low")


def build_fallback_diagnosis(request: AiRequest, reason: str) -> dict[str, Any]:
    """Build a v2-schema-valid fallback diagnosis result.

    The result is deliberately template-based: it never echoes arbitrary raw
    payload content into the summary. It is validated defensively against the
    v2 schema before returning (a static template should always pass).
    """
    bundle = normalize_diagnosis_context(request.raw.get("context"))
    result = {
        "diagnosis_summary": (
            "Cloud AI diagnosis is temporarily unavailable; local template "
            "result."
        ),
        "risk_level": _risk_from_event(bundle.event),
        "possible_causes": [
            "Cloud AI service is temporarily unavailable (provider failure)."
        ],
        "recommended_actions": [
            "Retry the diagnosis after a short delay.",
            "Continue local monitoring and check the latest alarm/telemetry "
            "values.",
        ],
        "need_shutdown": False,
        "confidence": 0.0,
        "source": "fallback",
        "advisory_only": True,
        "fallback_reason": reason,
    }
    validated = validate_diagnosis_result(result)
    logger.warning(
        "fallback_built device_id=%s req_id=%s reason=%s risk_level=%s",
        request.device_id,
        request.req_id,
        reason,
        validated["risk_level"],
    )
    return validated
