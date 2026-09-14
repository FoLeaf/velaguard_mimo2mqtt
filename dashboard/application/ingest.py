"""Tolerant normalization of board-published dashboard payloads.

Every parse function returns a normalized :class:`Parsed` record or raises
:class:`IngestError` with a quarantine reason. Parse failures never crash the
collector; the caller quarantines the raw payload. Device timestamps are
preserved exactly as received; the cloud only adds ``received_ts_ms``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from dashboard.contracts import topics

_POINT_ID_RE = re.compile(r"^[A-Za-z0-9_]{1,23}$")

ALARM_STATE_RAISED = "raised"
ALARM_STATE_CLEARED = "cleared"


class IngestError(Exception):
    """Quarantine-worthy ingest failure with a safe, loggable reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Parsed:
    """Normalized ingest result ready for storage."""

    kind: str
    device_id: str
    record: dict[str, Any]


def _decode_object(payload: bytes) -> dict[str, Any]:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IngestError("non_json_payload") from exc
    if not isinstance(data, dict):
        raise IngestError("payload_not_object")
    return data


def _require_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    raise IngestError(f"invalid_field:{field}")


def _optional_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise IngestError(f"invalid_field:{field}")
    return value


def _optional_number(value: Any, field: str) -> float | int | str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise IngestError(f"invalid_field:{field}")
    if isinstance(value, (int, float, str)):
        return value
    raise IngestError(f"invalid_field:{field}")


def parse_status(device_id: str, payload: bytes) -> Parsed:
    data = _decode_object(payload)
    payload_device_id = data.get("device_id")
    if not isinstance(payload_device_id, str) or not payload_device_id:
        raise IngestError("missing_field:device_id")
    if payload_device_id != device_id:
        raise IngestError("device_id_mismatch")
    # LWT payloads carry only {"device_id", "online"}; online stays required.
    _require_bool(data.get("online"), "online")
    return Parsed(topics.KIND_STATUS, device_id, data)


def parse_telemetry(device_id: str, payload: bytes) -> Parsed:
    try:
        entries = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IngestError("non_json_payload") from exc
    if not isinstance(entries, list):
        raise IngestError("payload_not_array")

    samples: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        point_id = entry.get("id")
        if not isinstance(point_id, str) or not point_id:
            continue
        try:
            value = _optional_number(entry.get("value"), "value")
        except IngestError:
            continue
        samples.append(
            {
                "id": point_id,
                "value": value,
                "ok": _entry_bool(entry.get("ok")),
                "age_ms": _entry_age(entry.get("age_ms")),
            }
        )

    return Parsed(
        topics.KIND_TELEMETRY,
        device_id,
        {"device_id": device_id, "samples": samples},
    )


def _entry_bool(value: Any) -> bool:
    return value if isinstance(value, bool) else True


def _entry_age(value: Any) -> int | None:
    if value is None or isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def parse_alarm(device_id: str, payload: bytes) -> Parsed:
    data = _decode_object(payload)
    state = data.get("state")
    if state not in (ALARM_STATE_RAISED, ALARM_STATE_CLEARED):
        raise IngestError("invalid_field:state")

    point_id = data.get("id") or data.get("sensor_id")
    if not isinstance(point_id, str) or not point_id:
        raise IngestError("missing_field:id")

    device_ts = data.get("ts_ms")
    if device_ts is None:
        device_ts = data.get("ts")
    if device_ts is not None and (
        isinstance(device_ts, bool) or not isinstance(device_ts, int)
    ):
        raise IngestError("invalid_field:ts")

    alarm_id = data.get("alarm_id")
    if alarm_id is not None and not isinstance(alarm_id, str):
        raise IngestError("invalid_field:alarm_id")

    kind = data.get("kind")
    if kind is not None and not isinstance(kind, str):
        raise IngestError("invalid_field:kind")

    # Dedup/state key: explicit alarm_id wins, else (device, point, kind).
    key = alarm_id if alarm_id else f"{point_id}:{kind or 'alarm'}"
    record = {
        "alarm_key": key,
        "alarm_id": alarm_id,
        "state": state,
        "point_id": point_id,
        "kind": kind,
        "value": data.get("value"),
        "thr": data.get("thr"),
        "device_ts_ms": device_ts,
        # Full original JSON preserved for display/passthrough (ack fields etc.).
        "payload": data,
    }
    return Parsed(topics.KIND_ALARM, device_id, record)


def parse_point_table(device_id: str, payload: bytes) -> Parsed:
    data = _decode_object(payload)
    schema_version = data.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != 1:
        raise IngestError("unsupported_schema_version")

    points = data.get("points")
    if not isinstance(points, list) or not points:
        raise IngestError("invalid_field:points")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for point in points:
        if not isinstance(point, dict):
            raise IngestError("invalid_field:points")
        point_id = point.get("id")
        if not isinstance(point_id, str) or not _POINT_ID_RE.fullmatch(point_id):
            raise IngestError("invalid_field:points")
        if point_id in seen_ids:
            raise IngestError("duplicate_field:id")
        seen_ids.add(point_id)
        # TeamFalcons rule: threshold keys may be omitted but never null.
        if "warn" in point and point["warn"] is None:
            raise IngestError("null_field:warn")
        if "crit" in point and point["crit"] is None:
            raise IngestError("null_field:crit")
        normalized.append(
            {
                "id": point_id,
                "name": point.get("name") if isinstance(point.get("name"), str) else None,
                "unit": point.get("unit") if isinstance(point.get("unit"), str) else None,
                "scale": _scale(point.get("scale")),
                "addr": _opt_int_field(point.get("addr")),
                "fc": _opt_int_field(point.get("fc")),
                "reg": _opt_int_field(point.get("reg")),
                "qty": _opt_int_field(point.get("qty")),
                "dtype": point.get("dtype") if isinstance(point.get("dtype"), str) else None,
                "cmp": point.get("cmp") if isinstance(point.get("cmp"), str) else None,
                "warn": _opt_num_field(point.get("warn")),
                "crit": _opt_num_field(point.get("crit")),
                "spec_json": json.dumps(point, separators=(",", ":"), ensure_ascii=False),
            }
        )

    return Parsed(
        topics.KIND_POINT_TABLE,
        device_id,
        {"device_id": device_id, "table": data, "points": normalized},
    )


def _scale(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _opt_int_field(value: Any) -> int | None:
    if value is None or isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _opt_num_field(value: Any) -> float | int | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value
