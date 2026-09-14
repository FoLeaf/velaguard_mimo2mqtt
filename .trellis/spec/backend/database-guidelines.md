# Database and Persistence Guidelines

## Storage Owner

`dashboard/storage/db.py` owns the SQLite schema and `DashboardStore`.
It uses stdlib `sqlite3` with `check_same_thread=False` and an `RLock` around
shared-connection operations. Do not introduce an ORM or alternate store
without an explicit design decision.

`DB_PATH` defaults to `dashboard.db`; reopening the same file preserves state.
The development Compose stack puts the database in tmpfs and is deliberately
temporary. It must not be described as durable across container recreation.

## Tables and Transitions

| Table | Role |
|---|---|
| `devices` | Latest raw status and cloud receipt time per device |
| `points` | Current device point set, including full `spec_json` |
| `point_syncs` | Full JSON snapshot history with sync sequence |
| `telemetry_latest` | Latest sample per device/point |
| `telemetry_history` | Append-only received sample history |
| `alarms` | Current alarm state per device/alarm key |
| `alarm_events` | Raised/cleared transitions with original payload and time |
| `raw_messages` | Bounded recent traffic including quarantine reasons |

The collector passes validated records to storage. State snapshots replace or
upsert current state. Point-table syncs and telemetry history can have repeated
records; do not claim all writes are deduplicated.

Alarm transitions:

- First `raised`: open the alarm and append an event.
- Duplicate `raised` while open: refresh last-seen/payload only.
- `cleared` while open: close the alarm and append an event.
- Orphan `cleared`: append an event only.
- A later `raised` after clearing starts a new occurrence.

## Identity, Queries and Retention

- Scope SQL by `device_id`; use bound SQL parameters.
- Preserve original IDs and device time in stored payloads.
- Add `received_ts_ms` without overwriting source `ts_ms`/`uptime_ms`/`time_quality`.
- Keep current state separate from historical transitions and raw traffic.
- HTTP history queries cap at 1440 minutes and 2000 points; raw queries cap at 500.
- `cleanup(retention_hours, message_buffer_limit, alarm_event_limit)` trims
  telemetry history, raw traffic and alarm events. Point-sync history and
  current state are not removed by this cleanup.
- The current runtime schedules one cleanup timer; recurring maintenance,
  migrations and backup/restore policy need separate production work.

Schema changes require explicit compatibility, backup and rollback decisions.
Never store credentials or private key material in ordinary domain records.
