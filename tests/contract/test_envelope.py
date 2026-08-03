"""Contract tests for v1 response envelope."""

from __future__ import annotations

import pytest

from ai_bridge.contracts.envelope import (
    ErrorCode,
    ResponseStatus,
    build_response,
    response_to_dict,
)


def test_success_envelope_puts_result_under_result() -> None:
    result = {
        "diagnosis_summary": "stub: no live MiMo call",
        "source": "stub",
        "advisory_only": True,
    }
    response = build_response(
        req_id="r1",
        device_id="dev01",
        type_="diagnosis",
        status=ResponseStatus.SUCCESS,
        result=result,
        received_ts_ms=10,
        bridge_ts_ms=20,
    )
    wire = response_to_dict(response)
    assert set(wire) == {
        "req_id",
        "device_id",
        "type",
        "status",
        "error_code",
        "error_message",
        "result",
        "received_ts_ms",
        "bridge_ts_ms",
    }
    assert wire["status"] == "success"
    assert wire["error_code"] is None
    assert wire["error_message"] is None
    assert wire["result"] == result
    assert wire["result"]["advisory_only"] is True


def test_error_envelope_nulls_result() -> None:
    response = build_response(
        req_id="r1",
        device_id="dev01",
        type_="diagnosis",
        status=ResponseStatus.ERROR,
        error_code=ErrorCode.TIMEOUT,
        error_message="deadline",
        received_ts_ms=1,
        bridge_ts_ms=2,
        result={"should": "be ignored"},
    )
    wire = response_to_dict(response)
    assert wire["status"] == "error"
    assert wire["error_code"] == "timeout"
    assert wire["result"] is None


def test_processing_envelope() -> None:
    response = build_response(
        req_id="r1",
        device_id="dev01",
        type_="diagnosis",
        status="processing",
        received_ts_ms=1,
        bridge_ts_ms=2,
    )
    wire = response_to_dict(response)
    assert wire["status"] == "processing"
    assert wire["error_code"] is None
    assert wire["result"] is None


def test_success_requires_result() -> None:
    with pytest.raises(ValueError):
        build_response(
            req_id="r1",
            device_id="dev01",
            type_="diagnosis",
            status=ResponseStatus.SUCCESS,
            received_ts_ms=1,
            bridge_ts_ms=2,
        )


def test_error_requires_code() -> None:
    with pytest.raises(ValueError):
        build_response(
            req_id="r1",
            device_id="dev01",
            type_="diagnosis",
            status=ResponseStatus.ERROR,
            received_ts_ms=1,
            bridge_ts_ms=2,
        )
