"""Contract tests for AI request validation."""

from __future__ import annotations

import json

import pytest

from ai_bridge.contracts.request import RequestValidationError, parse_request


def _valid(**overrides: object) -> dict:
    data: dict = {
        "req_id": "r1",
        "device_id": "dev01",
        "created_ts_ms": 1_700_000_000_000,
        "type": "diagnosis",
        "payload_hash": "abc",
    }
    data.update(overrides)
    return data


def test_valid_request() -> None:
    req = parse_request(_valid(), topic_device_id="dev01")
    assert req.req_id == "r1"
    assert req.device_id == "dev01"
    assert req.type == "diagnosis"
    assert req.payload_hash == "abc"


def test_bytes_json_payload() -> None:
    raw = json.dumps(_valid()).encode("utf-8")
    req = parse_request(raw, topic_device_id="dev01")
    assert req.req_id == "r1"


@pytest.mark.parametrize("missing", ["req_id", "device_id", "created_ts_ms", "type", "payload_hash"])
def test_missing_required_field(missing: str) -> None:
    data = _valid()
    del data[missing]
    with pytest.raises(RequestValidationError) as exc:
        parse_request(data, topic_device_id="dev01")
    assert "missing or invalid" in exc.value.message


def test_device_id_mismatch() -> None:
    with pytest.raises(RequestValidationError) as exc:
        parse_request(_valid(), topic_device_id="other")
    assert "does not match" in exc.value.message
    assert exc.value.req_id == "r1"
    assert exc.value.device_id == "other"


def test_unknown_type() -> None:
    with pytest.raises(RequestValidationError) as exc:
        parse_request(_valid(type="tts"), topic_device_id="dev01")
    assert "unsupported" in exc.value.message


def test_invalid_json() -> None:
    with pytest.raises(RequestValidationError):
        parse_request(b"not-json", topic_device_id="dev01")


def test_created_ts_ms_rejects_bool() -> None:
    with pytest.raises(RequestValidationError):
        parse_request(_valid(created_ts_ms=True), topic_device_id="dev01")  # type: ignore[arg-type]


def test_oversized_ordinary_payload_rejected() -> None:
    huge = b"{" + (b"x" * (65 * 1024)) + b"}"
    with pytest.raises(RequestValidationError) as exc:
        parse_request(huge, topic_device_id="dev01")
    assert "size limit" in exc.value.message
