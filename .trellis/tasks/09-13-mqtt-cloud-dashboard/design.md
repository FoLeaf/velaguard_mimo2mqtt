# Design: MQTT cloud dashboard

## Architecture

```text
VelaGuard board / synthetic_board  --MQTT-->  Mosquitto broker
                                                |
                                                v
                        dashboard collector (paho, reuses ai_bridge MqttBridgeClient)
                                                |
                                       SQLite (devices/points/telemetry/alarms/raw)
                                                |
                                    stdlib ThreadingHTTPServer (read-only API)
                                                |
                                     static web page (vanilla JS, polling)
```

- One collector process: MQTT subscriber thread(s) + sqlite3 (stdlib) + HTTP server.
- Browser never talks to the broker; it polls the collector HTTP API every 2-3 s.
- Cloud is read-only end to end (V5): the HTTP API exposes GET endpoints only.

## Topic contract (consumed)

| Topic | QoS | Retained | Payload |
|---|---:|---|---|
| `vg/{id}/status` | 0 | yes (LWT `{"online":false}`) | `{device_id, online, firmware, build_mode, network, uptime_ms, ts_ms, time_quality}` |
| `vg/{id}/telemetry` | 0 | no | array `[{id, value, ok, age_ms}]` (TeamFalcons C1 format) |
| `vg/{id}/alarm` | 1 | no | `{ts\|ts_ms, id\|sensor_id, kind, value, thr, state: raised\|cleared, ...}` tolerant parse, unknown fields preserved |
| `vg/{id}/point_table` | 1 | **yes (new; config-snapshot semantics, needs spec amendment)** | TeamFalcons point table `{schema_version, bus, hits, points:[{id,name,addr,fc,reg,qty,dtype,scale,unit,cmp,warn,crit,fail_n}]}` |

Rules: tolerate unknown fields; never rewrite device timestamps; collector adds
`received_ts_ms`; 64 KiB soft cap per message (align with existing envelope rule).

## Modules

- `dashboard/configuration/settings.py` — pydantic-settings:
  `MQTT_HOST/PORT/USERNAME/PASSWORD/CLIENT_ID(default vg-dashboard-dev)/TLS/CA_PATH/CLIENT_CERT_PATH/CLIENT_KEY_PATH`,
  `HTTP_HOST/HTTP_PORT`, `DB_PATH`, `HISTORY_RETENTION_HOURS`, `MESSAGE_BUFFER_LIMIT`,
  `LOG_LEVEL`.
- `dashboard/contracts/topics.py` — the four subscribe filters + QoS/retain constants
  (single topic-definition owner, mirroring `ai_bridge.contracts.topics`).
- `dashboard/transport/subscriber.py` — uses generalized
  `ai_bridge.transport.mqtt.client.MqttBridgeClient` (new optional
  `subscribe_filters` param; default behavior unchanged so ai_bridge tests stay green).
- `dashboard/application/ingest.py` — parse/validate/normalize four message classes;
  returns normalized records or a quarantine record (reason + raw payload); never raises.
- `dashboard/storage/db.py` — sqlite3 stdlib:
  - `devices(device_id PK, ..., last_status_json, online, received_ts_ms)`
  - `points(device_id, point_id, name, unit, scale, addr, fc, reg, qty, dtype, cmp, warn, crit, spec_json, synced_ts_ms, PK(device_id, point_id))`
  - `point_syncs(device_id, seq, points_json, received_ts_ms)` (version history)
  - `telemetry_latest(device_id, point_id, value, ok, age_ms, received_ts_ms, PK(device_id, point_id))`
  - `telemetry_history(device_id, point_id, value, ok, received_ts_ms)` + retention cleanup
  - `alarms(id INTEGER PK, device_id, alarm_key, state, first_seen_ts_ms, last_seen_ts_ms, last_json)` —
    `alarm_key` = `alarm_id` if present else `(device_id, point_id, kind)`; state
    transitions raised/cleared appended as event log rows (`alarm_events`).
  - `raw_messages(seq PK AUTOINCREMENT, topic, payload, received_ts_ms)` ring buffer
    (cap `MESSAGE_BUFFER_LIMIT`).
- `dashboard/http/server.py` — ThreadingHTTPServer serving `dashboard/web/` static
  files and `GET /api/devices`, `GET /api/devices/{id}`, `GET /api/devices/{id}/history?point=&minutes=`,
  `GET /api/alarms`, `GET /api/messages`. No write endpoints.
- `dashboard/web/` — `index.html` + `app.js` + `styles.css`, Chinese UI, tabs:
  设备总览 / 设备详情（点表+实时值+SVG 趋势）/ 告警 / 原始报文.
- `dashboard/__main__.py` — assemble settings → db → subscriber → http server;
  console script `vg-dashboard`.
- `dashboard/tools/synthetic_board.py` — publishes retained status (+LWT-style
  offline demo), periodic telemetry, alarm raise/clear sequence, retained point table.

## Reuse map (ai_bridge infra)

- `ai_bridge.transport.mqtt.client.MqttBridgeClient` — generalized with
  `subscribe_filters`; reconnect-resubscribe + worker dispatch reused as-is.
- `ai_bridge.observability.logging` — structured logging + secret redaction.
- Settings/TLS env-key conventions mirrored (not imported) to keep dashboard
  independently configurable while staying consistent.

## Test plan

- unit: ingest matrix (good/base/bad per class), alarm state machine + dedup,
  db upsert/retention cleanup.
- contract: topic filters/QoS/retain constants; point-table schema validation against
  TeamFalcons example fixture (`tests/contract/fixtures/vgpoint_demo_points.json`).
- integration (optional, Mosquitto): synthetic_board → collector → HTTP API.
- Regression: `pytest tests/unit tests/contract -q` must stay green for ai_bridge.
