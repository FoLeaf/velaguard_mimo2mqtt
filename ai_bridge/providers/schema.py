"""v2 diagnosis result schema validation for provider output.

Provider raw output is advisory text produced by an external model. It must be
validated against the v2 wire schema before the bridge may publish it as a
structured success result. Invalid output is classified as ``provider_error``,
never success.
"""

from __future__ import annotations

from typing import Any

REQUIRED_SUMMARY_FIELD = "diagnosis_summary"
REQUIRED_RISK_LEVEL_FIELD = "risk_level"
REQUIRED_POSSIBLE_CAUSES_FIELD = "possible_causes"
REQUIRED_RECOMMENDED_ACTIONS_FIELD = "recommended_actions"
REQUIRED_NEED_SHUTDOWN_FIELD = "need_shutdown"
OPTIONAL_STRING_LIST_FIELDS = ("reasons", "recommendations")
OPTIONAL_CONFIDENCE_FIELD = "confidence"
RISK_LEVELS = frozenset({"low", "medium", "high"})


class SchemaValidationError(ValueError):
    """Raised when provider output does not satisfy the v2 diagnosis schema."""


def validate_diagnosis_result(data: Any) -> dict[str, Any]:
    """Validate and normalize a provider result against the v2 schema.

    Rules (v2):

    - ``diagnosis_summary``: required, non-empty string (whitespace-stripped).
    - ``risk_level``: required, one of ``low`` | ``medium`` | ``high``.
    - ``possible_causes`` / ``recommended_actions``: required lists of strings
      (empty lists are valid).
    - ``need_shutdown``: required bool (bool-like ints rejected).
    - ``reasons`` / ``recommendations``: optional lists of strings.
    - ``confidence``: optional number in ``[0, 1]`` (bool rejected).
    - Unknown extra keys: allowed and passed through (forward-compatible).

    Returns the normalized dict. Raises :class:`SchemaValidationError` on any
    violation. The error message never includes provider content.
    """
    if not isinstance(data, dict):
        raise SchemaValidationError("provider output is not a JSON object")

    summary = data.get(REQUIRED_SUMMARY_FIELD)
    if not isinstance(summary, str) or not summary.strip():
        raise SchemaValidationError(
            f"provider output missing required field: {REQUIRED_SUMMARY_FIELD}"
        )

    risk_level = data.get(REQUIRED_RISK_LEVEL_FIELD)
    if not isinstance(risk_level, str) or risk_level.strip() not in RISK_LEVELS:
        raise SchemaValidationError(
            f"provider output missing or invalid required field: "
            f"{REQUIRED_RISK_LEVEL_FIELD}"
        )

    for field in (
        REQUIRED_POSSIBLE_CAUSES_FIELD,
        REQUIRED_RECOMMENDED_ACTIONS_FIELD,
    ):
        value = data.get(field)
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise SchemaValidationError(f"provider output field has invalid type: {field}")

    need_shutdown = data.get(REQUIRED_NEED_SHUTDOWN_FIELD)
    if not isinstance(need_shutdown, bool):
        raise SchemaValidationError(
            f"provider output field has invalid type: {REQUIRED_NEED_SHUTDOWN_FIELD}"
        )

    for field in OPTIONAL_STRING_LIST_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise SchemaValidationError(f"provider output field has invalid type: {field}")

    if OPTIONAL_CONFIDENCE_FIELD in data:
        confidence = data[OPTIONAL_CONFIDENCE_FIELD]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise SchemaValidationError(
                f"provider output field has invalid type: {OPTIONAL_CONFIDENCE_FIELD}"
            )
        # Compare directly: float() overflows on huge ints and would escape as
        # an unclassified exception instead of a provider_error.
        if not 0.0 <= confidence <= 1.0:
            raise SchemaValidationError(
                f"provider output field out of range: {OPTIONAL_CONFIDENCE_FIELD}"
            )

    normalized = dict(data)
    normalized[REQUIRED_SUMMARY_FIELD] = summary.strip()
    normalized[REQUIRED_RISK_LEVEL_FIELD] = risk_level.strip()
    return normalized
