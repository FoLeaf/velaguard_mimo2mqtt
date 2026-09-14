"""Collector orchestration: topic → ingest → store, with quarantine."""

from __future__ import annotations

from typing import Any

from dashboard.application import ingest
from dashboard.application.ingest import IngestError, Parsed
from dashboard.contracts import topics
from dashboard.observability.logging import get_logger
from dashboard.storage.db import DashboardStore, now_ms

logger = get_logger(__name__)

_KIND_PARSERS = {
    topics.KIND_STATUS: ingest.parse_status,
    topics.KIND_TELEMETRY: ingest.parse_telemetry,
    topics.KIND_ALARM: ingest.parse_alarm,
    topics.KIND_POINT_TABLE: ingest.parse_point_table,
}


class Collector:
    """Consume raw (topic, payload) deliveries into the dashboard store.

    Fail-safe by contract: any parse or storage error is quarantined into the
    raw-message buffer with a reason and logged; the collector keeps serving.
    """

    def __init__(
        self,
        store: DashboardStore,
        *,
        message_buffer_limit: int = 500,
    ) -> None:
        self._store = store
        self._message_buffer_limit = message_buffer_limit

    def handle_message(self, topic: str, payload: bytes) -> None:
        received_ts_ms = now_ms()
        parsed_topic = topics.parse_device_topic(topic)
        device_id = parsed_topic[0] if parsed_topic else None
        kind = parsed_topic[1] if parsed_topic else None

        payload_text = self._decode_text(topic, payload)
        if payload_text is None:
            self._quarantine(
                topic, device_id, kind, received_ts_ms, "non_utf8_payload", payload
            )
            return

        if len(payload) > topics.MAX_PAYLOAD_BYTES:
            # Store only a bounded preview of oversized payloads.
            self._quarantine(
                topic, device_id, kind, received_ts_ms, "payload_too_large",
                payload_text[:512],
            )
            return

        if parsed_topic is None:
            self._quarantine(
                topic, device_id, kind, received_ts_ms, "unknown_topic", payload_text
            )
            return

        parser = _KIND_PARSERS.get(kind)
        if parser is None:
            self._quarantine(
                topic, device_id, kind, received_ts_ms, "unknown_kind", payload_text
            )
            return

        try:
            parsed = parser(device_id or "", payload)
            self._apply(parsed, received_ts_ms)
        except IngestError as exc:
            logger.warning(
                "dashboard_ingest_quarantined topic=%s device_id=%s kind=%s reason=%s",
                topic,
                device_id,
                kind,
                exc.reason,
            )
            self._quarantine(
                topic, device_id, kind, received_ts_ms, exc.reason, payload_text
            )
            return
        except Exception:
            # Storage or unexpected failure must never take the collector down.
            logger.exception(
                "dashboard_ingest_error topic=%s device_id=%s kind=%s",
                topic,
                device_id,
                kind,
            )
            self._quarantine(
                topic, device_id, kind, received_ts_ms, "internal_error", payload_text
            )
            return

        # Valid messages also enter the ring buffer so the debug view shows
        # the full recent traffic, not just quarantined payloads.
        self._store.record_raw(
            topic,
            device_id,
            kind,
            payload_text,
            received_ts_ms,
            quarantine_reason=None,
            buffer_limit=self._message_buffer_limit,
        )
        logger.debug(
            "dashboard_ingest_ok topic=%s device_id=%s kind=%s", topic, device_id, kind
        )

    def _apply(self, parsed: Parsed, received_ts_ms: int) -> None:
        record: dict[str, Any] = parsed.record
        device_id = parsed.device_id
        if parsed.kind == topics.KIND_STATUS:
            self._store.upsert_status(device_id, record, received_ts_ms)
        elif parsed.kind == topics.KIND_TELEMETRY:
            self._store.record_telemetry(device_id, record["samples"], received_ts_ms)
        elif parsed.kind == topics.KIND_ALARM:
            self._store.record_alarm(device_id, record, received_ts_ms)
        elif parsed.kind == topics.KIND_POINT_TABLE:
            self._store.sync_point_table(
                device_id, record["points"], record["table"], received_ts_ms
            )
        else:  # pragma: no cover - guarded by parser map
            raise IngestError("unknown_kind")

    def _quarantine(
        self,
        topic: str,
        device_id: str | None,
        kind: str | None,
        received_ts_ms: int,
        reason: str,
        payload: bytes | str,
    ) -> None:
        text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
        self._store.record_raw(
            topic,
            device_id,
            kind,
            text,
            received_ts_ms,
            quarantine_reason=reason,
            buffer_limit=self._message_buffer_limit,
        )

    @staticmethod
    def _decode_text(topic: str, payload: bytes) -> str | None:
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            logger.warning("dashboard_payload_decode_error topic=%s", topic)
            return None
