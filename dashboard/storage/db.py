"""SQLite persistence for the dashboard collector (stdlib sqlite3, no ORM).

First durable store in this repository (implementation choice recorded in
`.trellis/spec/backend/index.md`). Device IDs and timestamps are preserved as
received; cloud receipt time is stored separately as ``received_ts_ms``.
All writes are idempotent upserts so QoS 1 duplicates are safe.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
  device_id TEXT PRIMARY KEY,
  online INTEGER NOT NULL DEFAULT 0,
  last_status_json TEXT NOT NULL,
  received_ts_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS points (
  device_id TEXT NOT NULL,
  point_id TEXT NOT NULL,
  name TEXT,
  unit TEXT,
  scale REAL,
  addr INTEGER,
  fc INTEGER,
  reg INTEGER,
  qty INTEGER,
  dtype TEXT,
  cmp TEXT,
  warn REAL,
  crit REAL,
  spec_json TEXT NOT NULL,
  synced_ts_ms INTEGER NOT NULL,
  PRIMARY KEY (device_id, point_id)
);

CREATE TABLE IF NOT EXISTS point_syncs (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id TEXT NOT NULL,
  points_json TEXT NOT NULL,
  received_ts_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS telemetry_latest (
  device_id TEXT NOT NULL,
  point_id TEXT NOT NULL,
  value REAL,
  value_text TEXT,
  ok INTEGER NOT NULL,
  age_ms INTEGER,
  received_ts_ms INTEGER NOT NULL,
  PRIMARY KEY (device_id, point_id)
);

CREATE TABLE IF NOT EXISTS telemetry_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id TEXT NOT NULL,
  point_id TEXT NOT NULL,
  value REAL,
  value_text TEXT,
  ok INTEGER NOT NULL,
  received_ts_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_telemetry_history
  ON telemetry_history(device_id, point_id, received_ts_ms);

CREATE TABLE IF NOT EXISTS alarms (
  device_id TEXT NOT NULL,
  alarm_key TEXT NOT NULL,
  state TEXT NOT NULL,
  point_id TEXT,
  first_seen_ts_ms INTEGER,
  last_seen_ts_ms INTEGER,
  last_json TEXT NOT NULL,
  PRIMARY KEY (device_id, alarm_key)
);

CREATE TABLE IF NOT EXISTS alarm_events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id TEXT NOT NULL,
  alarm_key TEXT NOT NULL,
  state TEXT NOT NULL,
  point_id TEXT,
  device_ts_ms INTEGER,
  received_ts_ms INTEGER NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alarm_events_received
  ON alarm_events(received_ts_ms DESC);

CREATE TABLE IF NOT EXISTS raw_messages (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  topic TEXT NOT NULL,
  device_id TEXT,
  kind TEXT,
  payload TEXT NOT NULL,
  received_ts_ms INTEGER NOT NULL,
  quarantine_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_raw_messages_received
  ON raw_messages(received_ts_ms DESC);
"""


class DashboardStore:
    """Thread-safe SQLite facade. One connection guarded by an RLock; writes
    are idempotent upserts so at-least-once delivery cannot corrupt state."""

    def __init__(self, db_path: str) -> None:
        path = Path(db_path)
        if path.parent and str(path.parent) not in ("", "."):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._write():
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _write(self) -> Iterator[None]:
        """Commit a successful write; roll back so a failed statement cannot
        leave the shared connection aborted for later ingest/quarantine."""
        with self._lock:
            try:
                yield
                self._conn.commit()
            except Exception:
                try:
                    self._conn.rollback()
                except sqlite3.Error:
                    pass
                raise

    # -- status -----------------------------------------------------------

    def upsert_status(
        self,
        device_id: str,
        status: dict[str, Any],
        received_ts_ms: int,
    ) -> None:
        online = 1 if status.get("online") is True else 0
        body = json.dumps(status, separators=(",", ":"), ensure_ascii=False)
        with self._write():
            self._conn.execute(
                """
                INSERT INTO devices (device_id, online, last_status_json, received_ts_ms)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                  online = excluded.online,
                  last_status_json = excluded.last_status_json,
                  received_ts_ms = excluded.received_ts_ms
                """,
                (device_id, online, body, received_ts_ms),
            )

    def _ensure_device(self, device_id: str, received_ts_ms: int) -> None:
        """Create a placeholder device row so telemetry/alarm/point_table can
        register a device before its first status message arrives."""
        self._conn.execute(
            """
            INSERT INTO devices (device_id, online, last_status_json, received_ts_ms)
            VALUES (?, 0, ?, ?)
            ON CONFLICT(device_id) DO NOTHING
            """,
            (
                device_id,
                json.dumps(
                    {"device_id": device_id, "online": False, "status_source": "implicit"},
                    separators=(",", ":"),
                    ensure_ascii=False,
                ),
                received_ts_ms,
            ),
        )

    # -- point table ------------------------------------------------------

    def sync_point_table(
        self,
        device_id: str,
        points: list[dict[str, Any]],
        table: dict[str, Any],
        received_ts_ms: int,
    ) -> int:
        """Replace the device point set (full snapshot sync) and record a
        version row. Returns the sync sequence number."""
        body = json.dumps(table, separators=(",", ":"), ensure_ascii=False)
        with self._write():
            self._ensure_device(device_id, received_ts_ms)
            self._conn.execute(
                "DELETE FROM points WHERE device_id = ?",
                (device_id,),
            )
            self._conn.executemany(
                """
                INSERT INTO points (
                  device_id, point_id, name, unit, scale, addr, fc, reg, qty,
                  dtype, cmp, warn, crit, spec_json, synced_ts_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        device_id,
                        p["id"],
                        p.get("name"),
                        p.get("unit"),
                        p.get("scale"),
                        p.get("addr"),
                        p.get("fc"),
                        p.get("reg"),
                        p.get("qty"),
                        p.get("dtype"),
                        p.get("cmp"),
                        p.get("warn"),
                        p.get("crit"),
                        p["spec_json"],
                        received_ts_ms,
                    )
                    for p in points
                ],
            )
            cur = self._conn.execute(
                "INSERT INTO point_syncs (device_id, points_json, received_ts_ms)"
                " VALUES (?, ?, ?)",
                (device_id, body, received_ts_ms),
            )
            seq = int(cur.lastrowid or 0)
        return seq

    # -- telemetry --------------------------------------------------------

    def record_telemetry(
        self,
        device_id: str,
        samples: list[dict[str, Any]],
        received_ts_ms: int,
    ) -> None:
        with self._write():
            self._ensure_device(device_id, received_ts_ms)
            for sample in samples:
                value = sample.get("value")
                numeric = value if isinstance(value, (int, float)) else None
                text = value if isinstance(value, str) else None
                ok = 1 if sample.get("ok") is not False else 0
                self._conn.execute(
                    """
                    INSERT INTO telemetry_latest (
                      device_id, point_id, value, value_text, ok, age_ms, received_ts_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(device_id, point_id) DO UPDATE SET
                      value = excluded.value,
                      value_text = excluded.value_text,
                      ok = excluded.ok,
                      age_ms = excluded.age_ms,
                      received_ts_ms = excluded.received_ts_ms
                    """,
                    (
                        device_id,
                        sample["id"],
                        numeric,
                        text,
                        ok,
                        sample.get("age_ms"),
                        received_ts_ms,
                    ),
                )
                self._conn.execute(
                    """
                    INSERT INTO telemetry_history (
                      device_id, point_id, value, value_text, ok, received_ts_ms
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (device_id, sample["id"], numeric, text, ok, received_ts_ms),
                )

    # -- alarms -----------------------------------------------------------

    def record_alarm(
        self,
        device_id: str,
        record: dict[str, Any],
        received_ts_ms: int,
    ) -> None:
        state = record["state"]
        alarm_key = record["alarm_key"]
        point_id = record.get("point_id")
        device_ts = record.get("device_ts_ms")
        payload_json = json.dumps(
            record.get("payload") or {}, separators=(",", ":"), ensure_ascii=False
        )
        with self._write():
            self._ensure_device(device_id, received_ts_ms)
            row = self._conn.execute(
                "SELECT state FROM alarms WHERE device_id = ? AND alarm_key = ?",
                (device_id, alarm_key),
            ).fetchone()
            current_state = row["state"] if row is not None else None
            last_seen = device_ts or received_ts_ms

            if state == "raised" and current_state == "raised":
                # Duplicate/refresh raise for an open alarm: update last_seen only.
                self._conn.execute(
                    """
                    UPDATE alarms
                    SET last_seen_ts_ms = ?, last_json = ?
                    WHERE device_id = ? AND alarm_key = ?
                    """,
                    (last_seen, payload_json, device_id, alarm_key),
                )
                return

            if state == "cleared" and current_state != "raised":
                # Orphan clear without an open alarm: event log only.
                self._insert_alarm_event(
                    device_id, alarm_key, state, point_id, device_ts,
                    received_ts_ms, payload_json,
                )
                return

            if row is None:
                self._conn.execute(
                    """
                    INSERT INTO alarms (
                      device_id, alarm_key, state, point_id,
                      first_seen_ts_ms, last_seen_ts_ms, last_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        device_id,
                        alarm_key,
                        state,
                        point_id,
                        device_ts or received_ts_ms,
                        last_seen,
                        payload_json,
                    ),
                )
            elif state == "raised":
                # Re-raise after a clear: new occurrence, first_seen resets.
                self._conn.execute(
                    """
                    UPDATE alarms
                    SET state = ?, point_id = ?, first_seen_ts_ms = ?,
                        last_seen_ts_ms = ?, last_json = ?
                    WHERE device_id = ? AND alarm_key = ?
                    """,
                    (
                        state,
                        point_id,
                        device_ts or received_ts_ms,
                        last_seen,
                        payload_json,
                        device_id,
                        alarm_key,
                    ),
                )
            else:
                # Cleared closing an open alarm: keep first_seen.
                self._conn.execute(
                    """
                    UPDATE alarms
                    SET state = ?, last_seen_ts_ms = ?, last_json = ?
                    WHERE device_id = ? AND alarm_key = ?
                    """,
                    (state, last_seen, payload_json, device_id, alarm_key),
                )
            self._insert_alarm_event(
                device_id, alarm_key, state, point_id, device_ts,
                received_ts_ms, payload_json,
            )

    def _insert_alarm_event(
        self,
        device_id: str,
        alarm_key: str,
        state: str,
        point_id: str | None,
        device_ts: int | None,
        received_ts_ms: int,
        payload_json: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO alarm_events (
              device_id, alarm_key, state, point_id, device_ts_ms,
              received_ts_ms, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (device_id, alarm_key, state, point_id, device_ts, received_ts_ms, payload_json),
        )

    # -- raw message buffer -------------------------------------------------

    def record_raw(
        self,
        topic: str,
        device_id: str | None,
        kind: str | None,
        payload_text: str,
        received_ts_ms: int,
        quarantine_reason: str | None = None,
        buffer_limit: int = 500,
    ) -> None:
        with self._write():
            self._conn.execute(
                """
                INSERT INTO raw_messages (
                  topic, device_id, kind, payload, received_ts_ms, quarantine_reason
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (topic, device_id, kind, payload_text, received_ts_ms, quarantine_reason),
            )
            self._conn.execute(
                """
                DELETE FROM raw_messages WHERE seq NOT IN (
                  SELECT seq FROM raw_messages ORDER BY seq DESC LIMIT ?
                )
                """,
                (buffer_limit,),
            )

    # -- queries (read-only HTTP API) --------------------------------------

    def list_devices(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT d.device_id, d.online, d.last_status_json, d.received_ts_ms,
                  (SELECT COUNT(*) FROM alarms a
                   WHERE a.device_id = d.device_id AND a.state = 'raised') AS active_alarms,
                  (SELECT COUNT(*) FROM points p WHERE p.device_id = d.device_id) AS point_count
                FROM devices d
                ORDER BY d.device_id
                """
            ).fetchall()
        return [
            {
                "device_id": r["device_id"],
                "online": bool(r["online"]),
                "active_alarms": r["active_alarms"],
                "point_count": r["point_count"],
                "received_ts_ms": r["received_ts_ms"],
                "status": json.loads(r["last_status_json"]),
            }
            for r in rows
        ]

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        with self._lock:
            dev = self._conn.execute(
                "SELECT device_id, online, last_status_json, received_ts_ms"
                " FROM devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()
            if dev is None:
                return None
            points = self._conn.execute(
                "SELECT * FROM points WHERE device_id = ? ORDER BY"
                " COALESCE(addr, 0), point_id",
                (device_id,),
            ).fetchall()
            latest = self._conn.execute(
                "SELECT point_id, value, value_text, ok, age_ms, received_ts_ms"
                " FROM telemetry_latest WHERE device_id = ?",
                (device_id,),
            ).fetchall()
            syncs = self._conn.execute(
                "SELECT seq, received_ts_ms FROM point_syncs"
                " WHERE device_id = ? ORDER BY seq DESC LIMIT 10",
                (device_id,),
            ).fetchall()
            open_alarms = self._conn.execute(
                """
                SELECT device_id, alarm_key, state, point_id, first_seen_ts_ms,
                       last_seen_ts_ms, last_json
                FROM alarms WHERE device_id = ? AND state = 'raised'
                ORDER BY COALESCE(first_seen_ts_ms, 0) DESC
                """,
                (device_id,),
            ).fetchall()

        latest_map = {
            r["point_id"]: {
                "value": r["value"] if r["value"] is not None else r["value_text"],
                "ok": bool(r["ok"]),
                "age_ms": r["age_ms"],
                "received_ts_ms": r["received_ts_ms"],
            }
            for r in latest
        }
        alarms = [self._active_alarm_from_row(r) for r in open_alarms]
        alarms_by_point: dict[str, list[dict[str, Any]]] = {}
        for alarm in alarms:
            point_id = alarm["point_id"]
            if not isinstance(point_id, str) or not point_id:
                continue
            alarms_by_point.setdefault(point_id, []).append(alarm)
        return {
            "device_id": dev["device_id"],
            "online": bool(dev["online"]),
            "received_ts_ms": dev["received_ts_ms"],
            "status": json.loads(dev["last_status_json"]),
            "active_alarms": len(alarms),
            "alarms": alarms,
            "point_syncs": [
                {"seq": s["seq"], "received_ts_ms": s["received_ts_ms"]} for s in syncs
            ],
            "points": [
                {
                    "id": p["point_id"],
                    "name": p["name"],
                    "unit": p["unit"],
                    "scale": p["scale"],
                    "addr": p["addr"],
                    "fc": p["fc"],
                    "reg": p["reg"],
                    "qty": p["qty"],
                    "dtype": p["dtype"],
                    "cmp": p["cmp"],
                    "warn": p["warn"],
                    "crit": p["crit"],
                    "spec": json.loads(p["spec_json"]),
                    "latest": latest_map.get(p["point_id"]),
                    "alarms": alarms_by_point.get(p["point_id"], []),
                }
                for p in points
            ],
            "unsynced_latest": [
                {
                    "point_id": pid,
                    "value": v["value"],
                    "ok": bool(v["ok"]),
                    "age_ms": v["age_ms"],
                    "received_ts_ms": v["received_ts_ms"],
                    "alarms": alarms_by_point.get(pid, []),
                }
                for pid, v in latest_map.items()
                if pid not in {p["point_id"] for p in points}
            ],
        }

    def history(
        self,
        device_id: str,
        point_id: str,
        since_ts_ms: int,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT value, value_text, ok, received_ts_ms
                FROM telemetry_history
                WHERE device_id = ? AND point_id = ? AND received_ts_ms >= ?
                ORDER BY received_ts_ms ASC
                LIMIT ?
                """,
                (device_id, point_id, since_ts_ms, limit),
            ).fetchall()
        return [
            {
                "value": r["value"] if r["value"] is not None else r["value_text"],
                "ok": bool(r["ok"]),
                "received_ts_ms": r["received_ts_ms"],
            }
            for r in rows
        ]

    @staticmethod
    def _active_alarm_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "device_id": row["device_id"],
            "alarm_key": row["alarm_key"],
            "point_id": row["point_id"],
            "first_seen_ts_ms": row["first_seen_ts_ms"],
            "last_seen_ts_ms": row["last_seen_ts_ms"],
            "payload": json.loads(row["last_json"]),
        }

    def list_alarms(self, event_limit: int = 200) -> dict[str, Any]:
        with self._lock:
            active = self._conn.execute(
                """
                SELECT device_id, alarm_key, state, point_id, first_seen_ts_ms,
                       last_seen_ts_ms, last_json
                FROM alarms WHERE state = 'raised'
                ORDER BY COALESCE(first_seen_ts_ms, 0) DESC
                """
            ).fetchall()
            events = self._conn.execute(
                """
                SELECT seq, device_id, alarm_key, state, point_id, device_ts_ms,
                       received_ts_ms, payload_json
                FROM alarm_events ORDER BY seq DESC LIMIT ?
                """,
                (event_limit,),
            ).fetchall()
        return {
            "active": [self._active_alarm_from_row(r) for r in active],
            "events": [
                {
                    "seq": r["seq"],
                    "device_id": r["device_id"],
                    "alarm_key": r["alarm_key"],
                    "state": r["state"],
                    "point_id": r["point_id"],
                    "device_ts_ms": r["device_ts_ms"],
                    "received_ts_ms": r["received_ts_ms"],
                    "payload": json.loads(r["payload_json"]),
                }
                for r in events
            ],
        }

    def list_messages(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT seq, topic, device_id, kind, payload, received_ts_ms,
                       quarantine_reason
                FROM raw_messages ORDER BY seq DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "seq": r["seq"],
                "topic": r["topic"],
                "device_id": r["device_id"],
                "kind": r["kind"],
                "payload": r["payload"],
                "received_ts_ms": r["received_ts_ms"],
                "quarantine_reason": r["quarantine_reason"],
            }
            for r in rows
        ]

    # -- retention ---------------------------------------------------------

    def cleanup(
        self,
        retention_hours: int,
        message_buffer_limit: int,
        alarm_event_limit: int,
    ) -> None:
        cutoff = now_ms() - int(retention_hours * 3600 * 1000)
        with self._write():
            self._conn.execute(
                "DELETE FROM telemetry_history WHERE received_ts_ms < ?", (cutoff,)
            )
            self._conn.execute(
                """
                DELETE FROM raw_messages WHERE seq NOT IN (
                  SELECT seq FROM raw_messages ORDER BY seq DESC LIMIT ?
                )
                """,
                (message_buffer_limit,),
            )
            self._conn.execute(
                """
                DELETE FROM alarm_events WHERE seq NOT IN (
                  SELECT seq FROM alarm_events ORDER BY seq DESC LIMIT ?
                )
                """,
                (alarm_event_limit,),
            )


def now_ms() -> int:
    return int(time.time() * 1000)
