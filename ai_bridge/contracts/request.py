"""AI request validation models."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

SUPPORTED_TYPES = frozenset({"diagnosis"})
MAX_ORDINARY_PAYLOAD_BYTES = 64 * 1024


class RequestValidationError(Exception):
    """Raised when an inbound AI request fails contract validation."""

    def __init__(
        self,
        message: str,
        *,
        req_id: str | None = None,
        device_id: str | None = None,
        type_: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.req_id = req_id
        self.device_id = device_id
        self.type = type_


@dataclass(frozen=True, slots=True)
class AiRequest:
    """Validated AI request envelope fields plus raw extras."""

    req_id: str
    device_id: str
    created_ts_ms: int
    type: str
    payload_hash: str
    raw: dict[str, Any]


def _require_str(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RequestValidationError(f"missing or invalid field: {field}")
    return value.strip()


def _require_int(data: dict[str, Any], field: str) -> int:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RequestValidationError(f"missing or invalid field: {field}")
    return value


def parse_request(
    payload: bytes | str | dict[str, Any],
    *,
    topic_device_id: str | None,
) -> AiRequest:
    """Parse and validate a request payload against the v1 contract."""
    if isinstance(payload, (bytes, bytearray)):
        if len(payload) > MAX_ORDINARY_PAYLOAD_BYTES:
            raise RequestValidationError("payload exceeds ordinary MQTT size limit")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RequestValidationError("payload is not valid UTF-8 JSON") from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RequestValidationError("payload is not valid JSON") from exc
    elif isinstance(payload, str):
        if len(payload.encode("utf-8")) > MAX_ORDINARY_PAYLOAD_BYTES:
            raise RequestValidationError("payload exceeds ordinary MQTT size limit")
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RequestValidationError("payload is not valid JSON") from exc
    elif isinstance(payload, dict):
        data = payload
    else:
        raise RequestValidationError("payload must be JSON object")

    if not isinstance(data, dict):
        raise RequestValidationError("payload must be a JSON object")

    partial_req_id = data.get("req_id") if isinstance(data.get("req_id"), str) else None
    partial_device_id = (
        data.get("device_id") if isinstance(data.get("device_id"), str) else None
    )
    partial_type = data.get("type") if isinstance(data.get("type"), str) else None

    try:
        req_id = _require_str(data, "req_id")
        device_id = _require_str(data, "device_id")
        created_ts_ms = _require_int(data, "created_ts_ms")
        type_ = _require_str(data, "type")
        payload_hash = _require_str(data, "payload_hash")
    except RequestValidationError as exc:
        raise RequestValidationError(
            exc.message,
            req_id=partial_req_id,
            device_id=partial_device_id or topic_device_id,
            type_=partial_type,
        ) from None

    if topic_device_id is None:
        raise RequestValidationError(
            "unable to parse device_id from topic",
            req_id=req_id,
            device_id=device_id,
            type_=type_,
        )

    if device_id != topic_device_id:
        raise RequestValidationError(
            "topic device_id does not match payload device_id",
            req_id=req_id,
            device_id=topic_device_id,
            type_=type_,
        )

    if type_ not in SUPPORTED_TYPES:
        raise RequestValidationError(
            f"unsupported request type: {type_}",
            req_id=req_id,
            device_id=device_id,
            type_=type_,
        )

    if created_ts_ms < 0:
        raise RequestValidationError(
            "created_ts_ms must be non-negative",
            req_id=req_id,
            device_id=device_id,
            type_=type_,
        )

    if "context" in data and not isinstance(data["context"], dict):
        raise RequestValidationError(
            "context must be an object",
            req_id=req_id,
            device_id=device_id,
            type_=type_,
        )

    return AiRequest(
        req_id=req_id,
        device_id=device_id,
        created_ts_ms=created_ts_ms,
        type=type_,
        payload_hash=payload_hash,
        raw=dict(data),
    )
