"""Unit tests for the dashboard SQLite store (alarm state machine, upserts,
retention) and collector quarantine behavior. Temporary DB files only."""

from __future__ import annotations

import json

import pytest

from dashboard.application.collector import Collector
from dashboard.storage.db import DashboardStore, now_ms


@pytest.fixture()
def store(tmp_path):
    s = DashboardStore(str(tmp_path / "test.db"))
    yield s
    s.close()


@pytest.fixture()
def collector(store):
    return Collector(store, message_buffer_limit=5)


def _publish(collector, topic: str, payload) -> None:
    body = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
    collector.handle_message(topic, body)


class TestAlarmStateMachine:
    def test_raise_refresh_clear_cycle(self, store, collector) -> None:
        _publish(collector, "vg/dev01/alarm",
                 {"id": "temp", "kind": "threshold_high", "state": "raised",
                  "value": 36, "thr": 35, "ts": 100, "alarm_id": "a-1"})
        _publish(collector, "vg/dev01/alarm",
                 {"id": "temp", "kind": "threshold_high", "state": "raised",
                  "value": 37, "thr": 35, "ts": 110, "alarm_id": "a-1"})
        _publish(collector, "vg/dev01/alarm",
                 {"id": "temp", "kind": "threshold_high", "state": "cleared",
                  "value": 30, "thr": 35, "ts": 120, "alarm_id": "a-1"})

        data = store.list_alarms()
        assert data["active"] == []
        # Duplicate raise refreshes last_seen instead of adding an event.
        assert [e["state"] for e in data["events"]] == ["cleared", "raised"]
        assert data["events"][0]["device_ts_ms"] == 120

    def test_reopen_after_clear_resets_first_seen(self, store, collector) -> None:
        _publish(collector, "vg/dev01/alarm",
                 {"id": "temp", "state": "raised", "ts": 100, "alarm_id": "a-1"})
        _publish(collector, "vg/dev01/alarm",
                 {"id": "temp", "state": "cleared", "ts": 200, "alarm_id": "a-1"})
        _publish(collector, "vg/dev01/alarm",
                 {"id": "temp", "state": "raised", "ts": 300, "alarm_id": "a-1"})
        data = store.list_alarms()
        assert len(data["active"]) == 1
        assert data["active"][0]["first_seen_ts_ms"] == 300
        assert [e["state"] for e in data["events"]] == ["raised", "cleared", "raised"]

    def test_orphan_clear_is_event_only(self, store, collector) -> None:
        _publish(collector, "vg/dev01/alarm",
                 {"id": "temp", "state": "cleared", "ts": 100})
        data = store.list_alarms()
        assert data["active"] == []
        assert len(data["events"]) == 1

    def test_key_fallback_without_alarm_id(self, store, collector) -> None:
        _publish(collector, "vg/dev01/alarm",
                 {"id": "flood", "kind": "digital", "state": "raised"})
        _publish(collector, "vg/dev01/alarm",
                 {"id": "flood", "kind": "digital", "state": "raised", "ts": 50})
        data = store.list_alarms()
        # Same implicit key (point:kind) → one open alarm, one event.
        assert len(data["active"]) == 1
        assert data["active"][0]["alarm_key"] == "flood:digital"
        assert len(data["events"]) == 1

    def test_devices_scoped_by_device_id(self, store, collector) -> None:
        _publish(collector, "vg/dev01/alarm",
                 {"id": "temp", "state": "raised", "alarm_id": "a-1"})
        _publish(collector, "vg/dev02/alarm",
                 {"id": "temp", "state": "raised", "alarm_id": "a-1"})
        assert len(store.list_alarms()["active"]) == 2


class TestStatusAndPointTable:
    def test_status_upsert_idempotent(self, store, collector) -> None:
        for _ in range(2):
            _publish(collector, "vg/dev01/status",
                     {"device_id": "dev01", "online": True, "ts_ms": 1})
        devices = store.list_devices()
        assert len(devices) == 1
        assert devices[0]["online"] is True

    def test_lwt_marks_offline(self, store, collector) -> None:
        _publish(collector, "vg/dev01/status",
                 {"device_id": "dev01", "online": True})
        _publish(collector, "vg/dev01/status",
                 {"device_id": "dev01", "online": False})
        assert store.list_devices()[0]["online"] is False

    def test_point_table_resync_replaces_points(self, store, collector) -> None:
        table_v1 = {"schema_version": 1,
                    "points": [{"id": "temp", "name": "温度", "warn": 40}]}
        table_v2 = {"schema_version": 1,
                    "points": [{"id": "temp", "name": "温度2", "warn": 41},
                               {"id": "flood", "name": "水浸", "crit": 1}]}
        _publish(collector, "vg/dev01/point_table", table_v1)
        _publish(collector, "vg/dev01/point_table", table_v2)
        device = store.get_device("dev01")
        ids = [p["id"] for p in device["points"]]
        assert ids == ["flood", "temp"]  # sorted by addr fallback → point_id
        assert device["points"][1]["name"] == "温度2"
        assert len(device["point_syncs"]) == 2

    def test_point_table_telemetry_mapping(self, store, collector) -> None:
        _publish(collector, "vg/dev01/point_table",
                 {"schema_version": 1, "points": [{"id": "temp", "unit": "C"}]})
        _publish(collector, "vg/dev01/telemetry",
                 [{"id": "temp", "value": 25.5, "ok": True, "age_ms": 10},
                  {"id": "ghost", "value": 1, "ok": True, "age_ms": 10}])
        device = store.get_device("dev01")
        assert device["points"][0]["latest"]["value"] == 25.5
        # Unknown point ids are still captured, shown as unsynced values.
        assert device["unsynced_latest"][0]["point_id"] == "ghost"

    def test_trend_history(self, store, collector) -> None:
        _publish(collector, "vg/dev01/telemetry", [{"id": "temp", "value": 1}])
        _publish(collector, "vg/dev01/telemetry", [{"id": "temp", "value": 2}])
        history = store.history("dev01", "temp", since_ts_ms=0)
        assert [h["value"] for h in history] == [1, 2]


class TestQuarantine:
    def test_non_json_quarantined(self, store, collector) -> None:
        collector.handle_message("vg/dev01/telemetry", b"garbage{{{")
        msgs = store.list_messages(10)
        assert msgs[0]["quarantine_reason"] == "non_json_payload"

    def test_device_mismatch_quarantined(self, store, collector) -> None:
        _publish(collector, "vg/dev01/status", {"device_id": "other", "online": True})
        assert store.list_messages(10)[0]["quarantine_reason"] == "device_id_mismatch"

    def test_unknown_topic_quarantined(self, store, collector) -> None:
        # Valid 3-part shape but no parser registered for the kind.
        _publish(collector, "vg/dev01/foo", {"x": 1})
        assert store.list_messages(10)[0]["quarantine_reason"] == "unknown_kind"

    def test_oversized_topic_path_quarantined(self, store, collector) -> None:
        # Deeper paths (e.g. AI Bridge topics) are outside dashboard scope.
        _publish(collector, "vg/dev01/ai/request", {"req_id": "r"})
        assert store.list_messages(10)[0]["quarantine_reason"] == "unknown_topic"

    def test_non_utf8_quarantined(self, store, collector) -> None:
        collector.handle_message("vg/dev01/status", b"\xff\xfe\xfa")
        assert store.list_messages(10)[0]["quarantine_reason"] == "non_utf8_payload"

    def test_quarantine_never_updates_domain_tables(self, store, collector) -> None:
        _publish(collector, "vg/dev01/telemetry", "nope")
        assert store.get_device("dev01") is None

    def test_valid_messages_enter_debug_buffer(self, store, collector) -> None:
        _publish(collector, "vg/dev01/status",
                 {"device_id": "dev01", "online": True})
        msgs = store.list_messages(10)
        assert msgs[0]["quarantine_reason"] is None
        assert msgs[0]["kind"] == "status"

    def test_oversize_quarantined(self, store, collector) -> None:
        from dashboard.contracts.topics import MAX_PAYLOAD_BYTES

        collector.handle_message("vg/dev01/status", b"x" * (MAX_PAYLOAD_BYTES + 1))
        assert store.list_messages(10)[0]["quarantine_reason"] == "payload_too_large"

    def test_buffer_capped(self, store, collector) -> None:
        for i in range(10):
            _publish(collector, "vg/dev01/telemetry", f"bad{i}")
        msgs = store.list_messages(10)
        assert len(msgs) == 5  # message_buffer_limit fixture
        assert json.loads(msgs[0]["payload"]) == "bad9"  # newest kept


class TestRetention:
    def test_cleanup_removes_old_history(self, store) -> None:
        store.record_telemetry("dev01", [{"id": "temp", "value": 1, "ok": True}],
                               received_ts_ms=now_ms() - 10 * 3600 * 1000)
        store.record_telemetry("dev01", [{"id": "temp", "value": 2, "ok": True}],
                               received_ts_ms=now_ms())
        store.cleanup(retention_hours=1, message_buffer_limit=500,
                      alarm_event_limit=5000)
        assert [h["value"] for h in store.history("dev01", "temp", 0)] == [2]

    def test_alarm_events_capped(self, store) -> None:
        for i in range(10):
            store.record_alarm(
                "dev01",
                {"alarm_key": f"a-{i}", "state": "raised", "point_id": "temp",
                 "payload": {}},
                received_ts_ms=now_ms(),
            )
        store.cleanup(retention_hours=24, message_buffer_limit=500, alarm_event_limit=5)
        assert len(store.list_alarms()["events"]) == 5
