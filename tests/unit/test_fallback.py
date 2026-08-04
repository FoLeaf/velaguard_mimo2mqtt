"""Unit tests for fallback diagnosis results."""

from __future__ import annotations

from typing import Any

import pytest

from ai_bridge.contracts.request import AiRequest
from ai_bridge.providers.schema import validate_diagnosis_result
from ai_bridge.runtime.fallback import build_fallback_diagnosis


def _request(*, context: dict[str, Any] | None = None) -> AiRequest:
    raw: dict[str, Any] = {
        "req_id": "r1",
        "device_id": "dev01",
        "created_ts_ms": 1,
        "type": "diagnosis",
        "payload_hash": "h1",
    }
    if context is not None:
        raw["context"] = context
    return AiRequest(
        req_id="r1",
        device_id="dev01",
        created_ts_ms=1,
        type="diagnosis",
        payload_hash="h1",
        raw=raw,
    )


def test_fallback_passes_v2_schema() -> None:
    result = build_fallback_diagnosis(_request(), "mimo provider error (HTTP 500)")
    assert validate_diagnosis_result(result) == result
    assert result["source"] == "fallback"
    assert result["advisory_only"] is True
    assert result["confidence"] == 0.0
    assert result["need_shutdown"] is False
    assert result["fallback_reason"] == "mimo provider error (HTTP 500)"


@pytest.mark.parametrize(
    ("severity", "expected"),
    [
        ("critical", "high"),
        ("error", "high"),
        ("warning", "medium"),
        ("info", "low"),
        (None, "low"),
    ],
)
def test_severity_maps_to_risk(severity: str | None, expected: str) -> None:
    context = None if severity is None else {"event": {"severity": severity}}
    result = build_fallback_diagnosis(_request(context=context), "reason")
    assert result["risk_level"] == expected


def test_missing_event_is_low_risk() -> None:
    result = build_fallback_diagnosis(_request(), "reason")
    assert result["risk_level"] == "low"


def test_summary_never_echoes_raw_payload() -> None:
    context = {
        "event": {"title": "sensitive raw detail", "severity": "warning"},
        "device": {"description": "another sensitive raw detail"},
    }
    result = build_fallback_diagnosis(_request(context=context), "reason")
    assert "sensitive raw detail" not in result["diagnosis_summary"]
