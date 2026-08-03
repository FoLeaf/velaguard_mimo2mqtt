"""Contract tests for topic parse/format helpers."""

from __future__ import annotations

import pytest

from ai_bridge.contracts.topics import (
    AI_QOS,
    AI_RETAIN,
    REQUEST_TOPIC_FILTER,
    parse_request_topic,
    response_topic,
)


def test_request_filter_is_plus_wildcard() -> None:
    assert REQUEST_TOPIC_FILTER == "vg/+/ai/request"


def test_ai_traffic_qos_and_retain_policy() -> None:
    assert AI_QOS == 1
    assert AI_RETAIN is False


@pytest.mark.parametrize(
    ("topic", "expected"),
    [
        ("vg/dev01/ai/request", "dev01"),
        ("vg/ABC-123/ai/request", "ABC-123"),
        ("vg//ai/request", None),
        ("vg/+/ai/request", None),
        ("vg/dev01/ai/response/r1", None),
        ("other/dev01/ai/request", None),
        ("vg/dev01/ai/request/extra", None),
    ],
)
def test_parse_request_topic(topic: str, expected: str | None) -> None:
    assert parse_request_topic(topic) == expected


def test_response_topic_format() -> None:
    assert response_topic("dev01", "req-1") == "vg/dev01/ai/response/req-1"


def test_response_topic_requires_ids() -> None:
    with pytest.raises(ValueError):
        response_topic("", "req-1")
    with pytest.raises(ValueError):
        response_topic("dev01", "")
