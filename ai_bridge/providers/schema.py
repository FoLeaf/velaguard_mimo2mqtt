"""v1 diagnosis result schema validation for provider output.

Provider raw output is advisory text produced by an external model. It must be
validated against the v1 wire schema before the bridge may publish it as a
structured success result. Invalid output is classified as ``provider_error``,
never success.
"""

from __future__ import annotations

from typing import Any

REQUIRED_SUMMARY_FIELD = "diagnosis_summary"
OPTIONAL_STRING_LIST_FIELDS = ("reasons", "recommendations")
OPTIONAL_CONFIDENCE_FIELD = "confidence"


class SchemaValidationError(ValueError):
    """Raised when provider output does not satisfy the v1 diagnosis schema."""


def validate_diagnosis_result(data: Any) -> dict[str, Any]:
    """Validate and normalize a provider result against the v1 schema.

    Rules (v1):

    - ``diagnosis_summary``: required, non-empty string (whitespace-stripped).
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
        if not 0.0 <= float(confidence) <= 1.0:
            raise SchemaValidationError(
                f"provider output field out of range: {OPTIONAL_CONFIDENCE_FIELD}"
            )

    normalized = dict(data)
    normalized[REQUIRED_SUMMARY_FIELD] = summary.strip()
    return normalized
