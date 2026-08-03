"""Centralized MQTT topic parse/format helpers."""

from __future__ import annotations

REQUEST_TOPIC_FILTER = "vg/+/ai/request"
REQUEST_TOPIC_PARTS = 4  # vg / {device_id} / ai / request

# AI request/response traffic policy (contracts).
AI_QOS = 1
AI_RETAIN = False


def parse_request_topic(topic: str) -> str | None:
    """Return device_id from ``vg/{device_id}/ai/request``, else None."""
    parts = topic.split("/")
    if len(parts) != REQUEST_TOPIC_PARTS:
        return None
    if parts[0] != "vg" or parts[2] != "ai" or parts[3] != "request":
        return None
    device_id = parts[1]
    if not device_id or device_id == "+":
        return None
    return device_id


def response_topic(device_id: str, req_id: str) -> str:
    """Build ``vg/{device_id}/ai/response/{req_id}``."""
    if not device_id:
        raise ValueError("device_id is required")
    if not req_id:
        raise ValueError("req_id is required")
    return f"vg/{device_id}/ai/response/{req_id}"
