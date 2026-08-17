"""Context normalization for ``type=diagnosis`` requests.

The request-level contract only checks that ``context`` is an object (see
``ai_bridge/contracts/request.py``). This module tolerantly normalizes the
inner sections: invalid child structures are dropped with a warning, oversized
sections are truncated with a visible marker, and missing sections are
reported so the prompt can state what it does not have.

Result-schema validation for provider output stays in
``ai_bridge/providers/schema.py``; this module never duplicates it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ai_bridge.observability.logging import get_logger

logger = get_logger(__name__)

MAX_HISTORY_ITEMS = 50
MAX_RULES_ITEMS = 20
MAX_EVENT_CHARS = 4096
MAX_DEVICE_CHARS = 2048
MAX_RULES_CHARS = 8192
MAX_HISTORY_CHARS = 16_384
MAX_SENSOR_CONFIG_CHARS = 4096
MAX_MANUAL_SUMMARY_CHARS = 2048
TRUNCATED_MARKER = "...[truncated]"


@dataclass(frozen=True, slots=True)
class ContextBundle:
    """Normalized diagnosis context sections.

    ``None`` / ``missing`` means the section was absent or invalid and was
    dropped; an empty list is a present-but-empty section.
    """

    event: dict[str, Any] | None
    history: list[dict[str, Any]] | None
    rules: list[dict[str, Any]] | None
    device: dict[str, Any] | None
    sensor_config: dict[str, Any] | None
    manual_summary: str | None
    missing: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Wire-facing context object with absent sections omitted."""
        data: dict[str, Any] = {}
        if self.event is not None:
            data["event"] = self.event
        if self.history is not None:
            data["history"] = self.history
        if self.rules is not None:
            data["rules"] = self.rules
        if self.device is not None:
            data["device"] = self.device
        if self.sensor_config is not None:
            data["sensor_config"] = self.sensor_config
        if self.manual_summary is not None:
            data["manual_summary"] = self.manual_summary
        return data


def _json_size(value: Any) -> int:
    return len(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    )


def truncate_json_value(value: Any, limit: int, *, field: str) -> Any:
    """Return a JSON-safe ``value`` no larger than ``limit`` serialized chars.

    Dicts keep leading keys and add an explicit marker key; lists keep leading
    items and append the marker; strings are cut with the marker appended. The
    result always remains valid JSON.
    """
    if _json_size(value) <= limit:
        return value

    logger.warning("context_truncated field=%s limit=%s", field, limit)

    if isinstance(value, dict):
        kept: dict[str, Any] = {}
        for key, item in value.items():
            dict_candidate = {**kept, key: item}
            if _json_size(dict_candidate) <= limit:
                kept = dict_candidate
                continue
            room = limit - _json_size(kept) - len(TRUNCATED_MARKER) - 3
            if room > 0:
                kept[key] = truncate_json_value(item, room, field=f"{field}.{key}")
            break
        kept["__truncated__"] = TRUNCATED_MARKER
        return kept

    if isinstance(value, list):
        kept_items: list[Any] = []
        for item in value:
            list_candidate = [*kept_items, item]
            if _json_size(list_candidate) <= limit - len(TRUNCATED_MARKER) - 3:
                kept_items = list_candidate
                continue
            room = limit - _json_size(kept_items) - len(TRUNCATED_MARKER) - 3
            if room > 0:
                kept_items.append(truncate_json_value(item, room, field=field))
            break
        kept_items.append(TRUNCATED_MARKER)
        return kept_items

    if isinstance(value, str):
        room = max(0, limit - len(TRUNCATED_MARKER))
        return value[:room] + TRUNCATED_MARKER

    return value


def _normalize_object_section(
    raw: dict[str, Any],
    key: str,
    max_chars: int,
) -> dict[str, Any] | None:
    if key not in raw:
        return None
    value = raw[key]
    if not isinstance(value, dict):
        logger.warning("context_dropped field=%s reason=not_object", key)
        return None
    truncated = truncate_json_value(value, max_chars, field=key)
    return truncated if isinstance(truncated, dict) else value


def _normalize_text_section(
    raw: dict[str, Any],
    key: str,
    max_chars: int,
) -> str | None:
    if key not in raw:
        return None
    value = raw[key]
    if not isinstance(value, str):
        logger.warning("context_dropped field=%s reason=not_string", key)
        return None
    truncated = truncate_json_value(value, max_chars, field=key)
    return truncated if isinstance(truncated, str) else value


def _normalize_list_section(
    raw: dict[str, Any],
    key: str,
    max_items: int,
    max_chars: int,
) -> list[dict[str, Any]] | None:
    if key not in raw:
        return None
    value = raw[key]
    if not isinstance(value, list):
        logger.warning("context_dropped field=%s reason=not_list", key)
        return None

    kept: list[dict[str, Any]] = []
    dropped = 0
    for item in value:
        if not isinstance(item, dict):
            dropped += 1
            continue
        # Copy so later per-entry markers never mutate the caller's raw request.
        kept.append(dict(item))
    if dropped:
        logger.warning(
            "context_dropped field=%s dropped_items=%s reason=not_object_entry",
            key,
            dropped,
        )
    if len(kept) > max_items:
        logger.warning(
            "context_truncated field=%s kept=%s max=%s reason=item_limit",
            key,
            max_items,
            max_items,
        )
        kept = kept[:max_items]

    if key == "history":
        marked: list[dict[str, Any]] = []
        for entry in kept:
            missing = [name for name in ("ts_ms", "values") if name not in entry]
            if missing:
                marked.append({**entry, "__missing__": missing})
            else:
                marked.append(entry)
        incomplete = [entry for entry in marked if "__missing__" in entry]
        if incomplete:
            logger.warning(
                "context_warn field=history incomplete_entries=%s "
                "(kept; ts_ms/values absent in JSON)",
                len(incomplete),
            )
        kept = marked

    truncated = truncate_json_value(kept, max_chars, field=key)
    return truncated if isinstance(truncated, list) else kept


def normalize_diagnosis_context(raw_context: Any) -> ContextBundle:
    """Normalize an optional diagnosis ``context`` value into a bundle."""
    if raw_context is None:
        raw: dict[str, Any] = {}
    elif isinstance(raw_context, dict):
        raw = raw_context
    else:
        # Defensive: parse_request already rejects non-object context.
        logger.warning("context_invalid reason=not_object")
        raw = {}

    event = _normalize_object_section(raw, "event", MAX_EVENT_CHARS)
    device = _normalize_object_section(raw, "device", MAX_DEVICE_CHARS)
    history = _normalize_list_section(
        raw, "history", MAX_HISTORY_ITEMS, MAX_HISTORY_CHARS
    )
    rules = _normalize_list_section(raw, "rules", MAX_RULES_ITEMS, MAX_RULES_CHARS)
    sensor_config = _normalize_object_section(
        raw, "sensor_config", MAX_SENSOR_CONFIG_CHARS
    )
    manual_summary = _normalize_text_section(
        raw, "manual_summary", MAX_MANUAL_SUMMARY_CHARS
    )

    missing = tuple(
        name
        for name, value in (
            ("event", event),
            ("history", history),
            ("rules", rules),
            ("device", device),
            ("sensor_config", sensor_config),
            ("manual_summary", manual_summary),
        )
        if value is None
    )
    return ContextBundle(
        event=event,
        history=history,
        rules=rules,
        device=device,
        sensor_config=sensor_config,
        manual_summary=manual_summary,
        missing=missing,
    )
