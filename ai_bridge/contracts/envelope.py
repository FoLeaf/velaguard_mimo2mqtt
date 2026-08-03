"""v1 AI response envelope builders."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ResponseStatus(StrEnum):
    PROCESSING = "processing"
    SUCCESS = "success"
    ERROR = "error"


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "validation_error"
    CONFLICT = "conflict"
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    INTERNAL_ERROR = "internal_error"


ERROR_CODES = frozenset(code.value for code in ErrorCode)


@dataclass(frozen=True, slots=True)
class AiResponse:
    req_id: str
    device_id: str
    type: str
    status: ResponseStatus
    error_code: str | None
    error_message: str | None
    result: dict[str, Any] | None
    received_ts_ms: int
    bridge_ts_ms: int


def build_response(
    *,
    req_id: str,
    device_id: str,
    type_: str,
    status: ResponseStatus | str,
    received_ts_ms: int,
    bridge_ts_ms: int,
    error_code: ErrorCode | str | None = None,
    error_message: str | None = None,
    result: dict[str, Any] | None = None,
) -> AiResponse:
    """Build a v1 response envelope with status-specific field rules."""
    status_value = ResponseStatus(status)

    code: str | None
    if error_code is None:
        code = None
    elif isinstance(error_code, ErrorCode):
        code = error_code.value
    else:
        code = str(error_code)

    if status_value is ResponseStatus.ERROR:
        if not code:
            raise ValueError("error responses require error_code")
        if code not in ERROR_CODES:
            raise ValueError(f"unknown error_code: {code}")
        return AiResponse(
            req_id=req_id,
            device_id=device_id,
            type=type_,
            status=status_value,
            error_code=code,
            error_message=error_message,
            result=None,
            received_ts_ms=received_ts_ms,
            bridge_ts_ms=bridge_ts_ms,
        )

    if status_value is ResponseStatus.SUCCESS:
        if result is None:
            raise ValueError("success responses require result")
        return AiResponse(
            req_id=req_id,
            device_id=device_id,
            type=type_,
            status=status_value,
            error_code=None,
            error_message=None,
            result=result,
            received_ts_ms=received_ts_ms,
            bridge_ts_ms=bridge_ts_ms,
        )

    # processing
    return AiResponse(
        req_id=req_id,
        device_id=device_id,
        type=type_,
        status=status_value,
        error_code=None,
        error_message=None,
        result=None,
        received_ts_ms=received_ts_ms,
        bridge_ts_ms=bridge_ts_ms,
    )


def response_to_dict(response: AiResponse) -> dict[str, Any]:
    """Serialize envelope to the wire JSON object."""
    return {
        "req_id": response.req_id,
        "device_id": response.device_id,
        "type": response.type,
        "status": response.status.value,
        "error_code": response.error_code,
        "error_message": response.error_message,
        "result": response.result,
        "received_ts_ms": response.received_ts_ms,
        "bridge_ts_ms": response.bridge_ts_ms,
    }
