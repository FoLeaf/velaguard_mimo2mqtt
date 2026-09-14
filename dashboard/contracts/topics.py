"""Topic filters, QoS, and retain policy for the dashboard collector.

Single owner of dashboard topic definitions. Board publishing semantics are
documented in `.trellis/spec/backend/mqtt-dashboard-contracts.md`
(Scenario: Dashboard consumption contract) and must be updated together.
"""

from __future__ import annotations

# Topic root is exactly vg/{device_id}/...; no environment prefix.
TOPIC_ROOT = "vg"

STATUS_FILTER = "vg/+/status"
TELEMETRY_FILTER = "vg/+/telemetry"
ALARM_FILTER = "vg/+/alarm"
POINT_TABLE_FILTER = "vg/+/point_table"

# Board-facing wire policy: events never retained; state snapshots (status,
# point_table) may be retained so late-joining dashboards recover state.
STATUS_QOS = 0
STATUS_RETAINED = True
TELEMETRY_QOS = 0
TELEMETRY_RETAINED = False
ALARM_QOS = 1
ALARM_RETAINED = False
POINT_TABLE_QOS = 1
POINT_TABLE_RETAINED = True

SUBSCRIBE_FILTERS: tuple[tuple[str, int], ...] = (
    (STATUS_FILTER, STATUS_QOS),
    (TELEMETRY_FILTER, TELEMETRY_QOS),
    (ALARM_FILTER, ALARM_QOS),
    (POINT_TABLE_FILTER, POINT_TABLE_QOS),
)

# Ordinary dashboard JSON soft cap.
MAX_PAYLOAD_BYTES = 64 * 1024

KIND_STATUS = "status"
KIND_TELEMETRY = "telemetry"
KIND_ALARM = "alarm"
KIND_POINT_TABLE = "point_table"


def parse_device_topic(topic: str) -> tuple[str, str] | None:
    """Split ``vg/{device_id}/{kind}`` into ``(device_id, kind)``.

    Returns None when the topic is outside the dashboard namespace.
    """
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != TOPIC_ROOT:
        return None
    device_id, kind = parts[1], parts[2]
    if not device_id or not kind:
        return None
    return device_id, kind
