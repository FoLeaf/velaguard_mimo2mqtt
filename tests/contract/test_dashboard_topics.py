"""Contract tests for dashboard topic definitions and wire policy."""

from __future__ import annotations

import pytest

from dashboard.contracts import topics


def test_topic_root_has_no_environment_prefix() -> None:
    assert topics.TOPIC_ROOT == "vg"
    assert topics.STATUS_FILTER == "vg/+/status"
    assert topics.TELEMETRY_FILTER == "vg/+/telemetry"
    assert topics.ALARM_FILTER == "vg/+/alarm"
    assert topics.POINT_TABLE_FILTER == "vg/+/point_table"


def test_qos_and_retain_policy() -> None:
    # Forbidden patterns (quality-guidelines): QoS0 alarms, retained
    # alarms/telemetry are violations. State snapshots may be retained.
    assert topics.ALARM_QOS == 1
    assert topics.ALARM_RETAINED is False
    assert topics.TELEMETRY_QOS == 0
    assert topics.TELEMETRY_RETAINED is False
    assert topics.STATUS_QOS == 0
    assert topics.STATUS_RETAINED is True
    assert topics.POINT_TABLE_QOS == 1
    assert topics.POINT_TABLE_RETAINED is True


def test_subscribe_filters_cover_four_classes() -> None:
    filters = {f for f, _q in topics.SUBSCRIBE_FILTERS}
    assert filters == {
        topics.STATUS_FILTER,
        topics.TELEMETRY_FILTER,
        topics.ALARM_FILTER,
        topics.POINT_TABLE_FILTER,
    }
    qoses = {f: q for f, q in topics.SUBSCRIBE_FILTERS}
    assert qoses[topics.ALARM_FILTER] == 1
    assert qoses[topics.POINT_TABLE_FILTER] == 1
    assert qoses[topics.STATUS_FILTER] == 0
    assert qoses[topics.TELEMETRY_FILTER] == 0


@pytest.mark.parametrize(
    ("topic", "expected"),
    [
        ("vg/dev01/status", ("dev01", "status")),
        ("vg/velaguard_abc123/alarm", ("velaguard_abc123", "alarm")),
        ("vg/dev01/telemetry", ("dev01", "telemetry")),
        ("vg/dev01/point_table", ("dev01", "point_table")),
    ],
)
def test_parse_device_topic_valid(topic: str, expected: tuple[str, str]) -> None:
    assert topics.parse_device_topic(topic) == expected


@pytest.mark.parametrize(
    "topic",
    [
        "vg/dev01/status/extra",  # deeper path is outside the dashboard contract
        "other/dev01/status",  # wrong root
        "vg/status",  # missing device_id
        "vg//status",  # empty device_id
        "",
    ],
)
def test_parse_device_topic_invalid(topic: str) -> None:
    assert topics.parse_device_topic(topic) is None


def test_payload_cap_is_64_kib() -> None:
    assert topics.MAX_PAYLOAD_BYTES == 64 * 1024
