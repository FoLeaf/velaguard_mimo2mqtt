"""AI request orchestration: validate, idempotency, deadline, provider, response."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ai_bridge.contracts.envelope import (
    AiResponse,
    ErrorCode,
    ResponseStatus,
    build_response,
    response_to_dict,
)
from ai_bridge.contracts.request import AiRequest, RequestValidationError, parse_request
from ai_bridge.contracts.topics import parse_request_topic, response_topic
from ai_bridge.observability.logging import get_logger
from ai_bridge.persistence.idempotency import (
    Completed,
    Conflict,
    IdempotencyStore,
    NewClaim,
    Processing,
)
from ai_bridge.providers.base import Provider, ProviderFailure, ProviderSuccess

logger = get_logger(__name__)

PublishFn = Callable[[str, dict[str, Any]], None]
NowMsFn = Callable[[], int]


def _now_ms() -> int:
    return int(time.time() * 1000)


class HandleAiRequest:
    """Use case for one inbound MQTT AI request message."""

    def __init__(
        self,
        *,
        store: IdempotencyStore,
        provider: Provider,
        publish: PublishFn,
        request_timeout_ms: int,
        now_ms: NowMsFn | None = None,
        publish_processing: bool = True,
    ) -> None:
        self._store = store
        self._provider = provider
        self._publish = publish
        self._request_timeout_ms = request_timeout_ms
        self._now_ms = now_ms or _now_ms
        self._publish_processing = publish_processing

    def handle_message(self, topic: str, payload: bytes) -> None:
        received_ts_ms = self._now_ms()
        topic_device_id = parse_request_topic(topic)

        try:
            request = parse_request(payload, topic_device_id=topic_device_id)
        except RequestValidationError as exc:
            self._handle_validation_error(
                exc,
                topic_device_id=topic_device_id,
                received_ts_ms=received_ts_ms,
            )
            return

        self._handle_valid_request(request, received_ts_ms=received_ts_ms)

    def _handle_validation_error(
        self,
        exc: RequestValidationError,
        *,
        topic_device_id: str | None,
        received_ts_ms: int,
    ) -> None:
        device_id = exc.device_id or topic_device_id
        req_id = exc.req_id
        logger.warning(
            "validation_error device_id=%s req_id=%s message=%s",
            device_id,
            req_id,
            exc.message,
        )
        if not device_id or not req_id:
            # Cannot correlate a response topic safely.
            return

        response = build_response(
            req_id=req_id,
            device_id=device_id,
            type_=exc.type or "unknown",
            status=ResponseStatus.ERROR,
            error_code=ErrorCode.VALIDATION_ERROR,
            error_message=exc.message,
            received_ts_ms=received_ts_ms,
            bridge_ts_ms=self._now_ms(),
        )
        self._emit(response)

    def _handle_valid_request(self, request: AiRequest, *, received_ts_ms: int) -> None:
        claim = self._store.claim(request.req_id, request.payload_hash)

        if isinstance(claim, Conflict):
            logger.warning(
                "conflict device_id=%s req_id=%s payload_hash=%s",
                request.device_id,
                request.req_id,
                request.payload_hash,
            )
            response = build_response(
                req_id=request.req_id,
                device_id=request.device_id,
                type_=request.type,
                status=ResponseStatus.ERROR,
                error_code=ErrorCode.CONFLICT,
                error_message="req_id reused with different payload_hash",
                received_ts_ms=received_ts_ms,
                bridge_ts_ms=self._now_ms(),
            )
            self._emit(response)
            return

        if isinstance(claim, Processing):
            logger.info(
                "idempotency=processing device_id=%s req_id=%s payload_hash=%s",
                request.device_id,
                request.req_id,
                request.payload_hash,
            )
            response = build_response(
                req_id=request.req_id,
                device_id=request.device_id,
                type_=request.type,
                status=ResponseStatus.PROCESSING,
                received_ts_ms=received_ts_ms,
                bridge_ts_ms=self._now_ms(),
            )
            self._emit(response)
            return

        if isinstance(claim, Completed):
            logger.info(
                "idempotency=completed_replay device_id=%s req_id=%s payload_hash=%s",
                request.device_id,
                request.req_id,
                request.payload_hash,
            )
            # Republish the exact stored response (same result/status/timestamps).
            replay = dict(claim.response)
            topic = response_topic(request.device_id, request.req_id)
            self._publish(topic, replay)
            return

        assert isinstance(claim, NewClaim)
        logger.info(
            "idempotency=new device_id=%s req_id=%s type=%s payload_hash=%s",
            request.device_id,
            request.req_id,
            request.type,
            request.payload_hash,
        )

        if self._publish_processing:
            processing = build_response(
                req_id=request.req_id,
                device_id=request.device_id,
                type_=request.type,
                status=ResponseStatus.PROCESSING,
                received_ts_ms=received_ts_ms,
                bridge_ts_ms=self._now_ms(),
            )
            self._emit(processing)

        deadline_s = self._remaining_deadline_s(received_ts_ms)
        try:
            if deadline_s <= 0:
                self._finish_error(
                    request,
                    received_ts_ms=received_ts_ms,
                    error_code=ErrorCode.TIMEOUT,
                    error_message="request deadline exceeded",
                )
                return

            result = self._provider.handle(request, deadline_s=deadline_s)
        except Exception:
            logger.exception(
                "provider_unexpected device_id=%s req_id=%s",
                request.device_id,
                request.req_id,
            )
            self._finish_error(
                request,
                received_ts_ms=received_ts_ms,
                error_code=ErrorCode.INTERNAL_ERROR,
                error_message="unexpected bridge failure",
            )
            return

        # Re-check deadline after provider returns (covers slow stub without internal timeout).
        if self._remaining_deadline_s(received_ts_ms) <= 0 and isinstance(
            result, ProviderSuccess
        ):
            self._finish_error(
                request,
                received_ts_ms=received_ts_ms,
                error_code=ErrorCode.TIMEOUT,
                error_message="request deadline exceeded",
            )
            return

        if isinstance(result, ProviderFailure):
            code = (
                ErrorCode.TIMEOUT
                if result.code == "timeout"
                else ErrorCode.PROVIDER_ERROR
            )
            if result.code not in {"timeout", "provider_error"}:
                code = ErrorCode.PROVIDER_ERROR
            self._finish_error(
                request,
                received_ts_ms=received_ts_ms,
                error_code=code,
                error_message=result.message,
            )
            return

        if not isinstance(result, ProviderSuccess) or not isinstance(result.result, dict):
            self._finish_error(
                request,
                received_ts_ms=received_ts_ms,
                error_code=ErrorCode.PROVIDER_ERROR,
                error_message="provider returned invalid structured output",
            )
            return

        response = build_response(
            req_id=request.req_id,
            device_id=request.device_id,
            type_=request.type,
            status=ResponseStatus.SUCCESS,
            result=result.result,
            received_ts_ms=received_ts_ms,
            bridge_ts_ms=self._now_ms(),
        )
        payload = response_to_dict(response)
        self._store.complete(request.req_id, request.payload_hash, payload)
        self._emit(response)
        logger.info(
            "completed device_id=%s req_id=%s status=success elapsed_ms=%s",
            request.device_id,
            request.req_id,
            self._now_ms() - received_ts_ms,
        )

    def _finish_error(
        self,
        request: AiRequest,
        *,
        received_ts_ms: int,
        error_code: ErrorCode,
        error_message: str,
    ) -> None:
        response = build_response(
            req_id=request.req_id,
            device_id=request.device_id,
            type_=request.type,
            status=ResponseStatus.ERROR,
            error_code=error_code,
            error_message=error_message,
            received_ts_ms=received_ts_ms,
            bridge_ts_ms=self._now_ms(),
        )
        payload = response_to_dict(response)
        self._store.fail(request.req_id, request.payload_hash, payload)
        self._emit(response)
        logger.warning(
            "failed device_id=%s req_id=%s error_code=%s",
            request.device_id,
            request.req_id,
            error_code.value,
        )

    def _remaining_deadline_s(self, received_ts_ms: int) -> float:
        elapsed_ms = self._now_ms() - received_ts_ms
        remaining_ms = self._request_timeout_ms - elapsed_ms
        return remaining_ms / 1000.0

    def _emit(self, response: AiResponse) -> None:
        topic = response_topic(response.device_id, response.req_id)
        self._publish(topic, response_to_dict(response))
