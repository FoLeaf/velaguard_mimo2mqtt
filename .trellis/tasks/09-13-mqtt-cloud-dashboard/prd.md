# MQTT cloud dashboard

## Goal

Pivot this repository from AI Bridge (deprecated, kept) to an **MQTT cloud dashboard**
for VelaGuard boards: a Python collector subscribes to board-published MQTT topics,
persists state to SQLite, and serves a read-only Chinese web dashboard.

## Background / Confirmed Decisions (2026-09-13)

- Form factor: **Python collector service + SQLite (stdlib) + built-in static web page
  (stdlib http.server, fetch polling)**. No new dependencies beyond existing
  (paho-mqtt, pydantic-settings). No FastAPI / SQLAlchemy / Redis.
- `ai_bridge/` code is **kept and reused** (paho client, logging redaction, TLS/config
  infra); the `ai-bridge` entry point stays but is no longer maintained.
- Protocol reuses TeamFalcons reference constraints (`contest2026_004_TeamFalcons`
  repo): topic root `vg/{device_id}/...`, QoS table, point-table JSON schema,
  telemetry/alarm payload shapes, status/LWT semantics.
- Cloud is **read-only** (boundary V5): no write endpoints, no alarm clearing,
  no config push.
- Additional scope confirmed by user: trend charts (from SQLite history) and a raw
  message debug view.

## Requirements

1. **Board status monitoring**: consume `vg/{id}/status` (QoS0, retained, incl. LWT
   offline) → device list with online/offline, firmware, build_mode, network, uptime.
2. **Alarm sync**: consume `vg/{id}/alarm` (QoS1, non-retained) → durable alarm event
   log (raised/cleared state machine, dedup), viewable even if the browser was closed
   when the alarm fired.
3. **Board data**: consume `vg/{id}/telemetry` (QoS0, `[{id,value,ok,age_ms}]`) →
   latest values per point + trend history charts.
4. **Point table auto-sync**: consume `vg/{id}/point_table` (QoS1, **retained**, new
   topic defined by this task) carrying the TeamFalcons point-table JSON
   (`{schema_version, bus, hits, points:[...]}`) → points table upserted per device,
   device detail page renders automatically from it.
5. **Raw message debug view**: last N raw MQTT JSON messages for joint debugging.
6. **Synthetic board publisher** for joint debugging/demo/tests without real hardware.
7. Tolerant ingest: malformed payloads are quarantined/logged, never crash the
   collector; device timestamps are preserved (cloud adds `received_ts_ms` only).

## Acceptance Criteria

- [x] With `synthetic_board` running, the dashboard shows: online device card →
      auto-synced point table → live values → trend curve → alarm raised/cleared →
      raw message stream.
      (Verified 2026-09-13 in a real browser against `scripts/demo_dashboard_seed.py`,
      which feeds the collector the exact synthetic_board payloads; all four views
      rendered: fleet cards incl. LWT-offline device, auto-synced point table with
      live values, SVG trend chart (40 samples), active alarm + event history,
      raw messages with quarantine highlight.)
- [x] Alarms produced while the browser is closed are still captured (server-side
      persistence) and visible after reopening. (Collector + SQLite persist
      independently of any browser; alarm API returns stored events after restart.)
- [x] Malformed payloads on all four topics do not crash the collector (quarantined
      and logged). (Unit matrix: non-JSON/non-UTF8/oversize/mismatch/schema-invalid.)
- [x] `pytest tests/unit tests/contract -q` all green (265 passed); existing
      ai_bridge tests do not regress.
- [x] Contract documented in `docs/dashboard-api.md` (Chinese) so the board team can
      implement publishing in the TeamFalcons repo.

## Out of Scope

- Board-side publishing implementation (TeamFalcons repo, its C1 plan).
- Any write/control capability from cloud to device (V5 boundary).
- TLS/HMAC/ACL production hardening (future C2 alignment).
- OTA display (not required).
