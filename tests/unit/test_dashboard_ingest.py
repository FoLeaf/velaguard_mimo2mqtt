"""Unit tests for dashboard ingest normalization (status/telemetry/alarm)."""

from __future__ import annotations

import json

import pytest

from dashboard.application.ingest import (
    IngestError,
    parse_alarm,
    parse_status,
    parse_telemetry,
)


def _obj(data: dict) -> bytes:
    return json.dumps(data).encode()


class TestStatus:
    def test_valid_status(self) -> None:
        payload = _obj(
            {
                "device_id": "dev01",
                "online": True,
                "firmware": "0.1.0",
                "network": "rj45",
                "uptime_ms": 100,
                "ts_ms": 5,
                "time_quality": "rtc",
            }
        )
        parsed = parse_status("dev01", payload)
        assert parsed.kind == "status"
        # Device fields preserved exactly.
        assert parsed.record["ts_ms"] == 5
        assert parsed.record["time_quality"] == "rtc"

    def test_lwt_minimal_payload(self) -> None:
        payload = _obj({"device_id": "dev01", "online": False})
        parsed = parse_status("dev01", payload)
        assert parsed.record["online"] is False

    def test_unknown_fields_preserved(self) -> None:
        payload = _obj({"device_id": "dev01", "online": True, "custom": {"a": 1}})
        assert parse_status("dev01", payload).record["custom"] == {"a": 1}

    @pytest.mark.parametrize(
        "payload",
        [
            b"not json",
            b"[1]",  # not object
            _obj({"online": True}),  # missing device_id
            _obj({"device_id": "dev01"}),  # missing online
            _obj({"device_id": "dev01", "online": 1}),  # bool-like int rejected
            _obj({"device_id": "other", "online": True}),  # topic/payload mismatch
        ],
    )
    def test_invalid(self, payload: bytes) -> None:
        with pytest.raises(IngestError):
            parse_status("dev01", payload)


class TestTelemetry:
    def test_valid_array(self) -> None:
        payload = json.dumps(
            [{"id": "temp", "value": 36.5, "ok": True, "age_ms": 100}]
        ).encode()
        parsed = parse_telemetry("dev01", payload)
        assert parsed.kind == "telemetry"
        assert parsed.record["samples"] == [
            {"id": "temp", "value": 36.5, "ok": True, "age_ms": 100}
        ]

    def test_defaults_and_optional_fields(self) -> None:
        payload = json.dumps([{"id": "flood"}]).encode()
        parsed = parse_telemetry("dev01", payload)
        assert parsed.record["samples"] == [
            {"id": "flood", "value": None, "ok": True, "age_ms": None}
        ]

    def test_string_value_allowed(self) -> None:
        payload = json.dumps([{"id": "mode", "value": "auto"}]).encode()
        assert parse_telemetry("dev01", payload).record["samples"][0]["value"] == "auto"

    def test_bad_entries_skipped_valid_kept(self) -> None:
        payload = json.dumps(
            [
                {"value": 1},  # missing id
                {"id": "ok1", "value": 2},
                {"id": "bad", "value": True},  # bool is not a number
                {"id": "ok2"},
            ]
        ).encode()
        samples = parse_telemetry("dev01", payload).record["samples"]
        assert [s["id"] for s in samples] == ["ok1", "ok2"]

    @pytest.mark.parametrize(
        "payload",
        [
            b"not json",
            b'{"id": "temp"}',  # object, not array
        ],
    )
    def test_structurally_invalid(self, payload: bytes) -> None:
        with pytest.raises(IngestError):
            parse_telemetry("dev01", payload)


class TestAlarm:
    def test_valid_raised(self) -> None:
        payload = _obj(
            {
                "ts": 111,
                "id": "temp",
                "kind": "threshold_high",
                "value": 36.5,
                "thr": 35,
                "state": "raised",
                "alarm_id": "a-1",
            }
        )
        parsed = parse_alarm("dev01", payload)
        assert parsed.record["state"] == "raised"
        assert parsed.record["alarm_key"] == "a-1"  # explicit alarm_id wins
        assert parsed.record["device_ts_ms"] == 111

    def test_sensor_id_alias_and_key_fallback(self) -> None:
        payload = _obj({"ts_ms": 1, "sensor_id": "flood", "state": "cleared"})
        parsed = parse_alarm("dev01", payload)
        assert parsed.record["point_id"] == "flood"
        assert parsed.record["alarm_key"] == "flood:alarm"
        assert parsed.record["device_ts_ms"] == 1

    def test_original_payload_preserved_for_passthrough(self) -> None:
        payload = _obj(
            {"id": "temp", "state": "raised", "custom_ack": {"ack": True}}
        )
        parsed = parse_alarm("dev01", payload)
        assert parsed.record["payload"]["custom_ack"] == {"ack": True}

    @pytest.mark.parametrize(
        "payload",
        [
            b"not json",
            _obj({"id": "temp"}),  # missing state
            _obj({"id": "temp", "state": "acknowledged"}),  # unknown state
            _obj({"state": "raised"}),  # missing point id
            _obj({"id": "temp", "state": "raised", "ts_ms": True}),  # bool ts
            _obj({"id": "temp", "state": "raised", "alarm_id": 7}),  # bad alarm_id
        ],
    )
    def test_invalid(self, payload: bytes) -> None:
        with pytest.raises(IngestError):
            parse_alarm("dev01", payload)
