# MQTT Dashboard Contracts

## Architecture Boundary

```text
VelaGuard -> MQTT Broker -> Dashboard collector -> SQLite -> HTTP -> Browser
```

The dashboard is read-only end to end (boundary V5): no device-facing MQTT
publishes, no configuration writes, no alarm acknowledgement or clearance, and
no HTTP write endpoint. The synthetic board is a separate development tool.

## Topics and Sessions

The root is `vg/{device_id}/...` without an environment prefix.

| Topic | QoS | Retained |
|---|---:|---|
| `vg/{device_id}/status` | 0 | Yes, including LWT |
| `vg/{device_id}/telemetry` | 0 | No |
| `vg/{device_id}/alarm` | 1 | No |
| `vg/{device_id}/point_table` | 1 | Yes |

`dashboard/contracts/topics.py` owns these definitions. State snapshots are
retained so late subscribers recover them; events are never retained.

The collector uses a fixed, unique `MQTT_CLIENT_ID` (default `vg-dashboard-dev`)
with `clean_session=true`. Every successful connect resubscribes to the four
filters. Critical events published during collector outages require a device
pending queue; the MQTT session does not provide application durability.

## Scenario: Dashboard Consumption Contract

### 1. Scope / Trigger

Any change to board payloads, filters, persistence semantics or runtime wiring
must update this contract, `docs/dashboard-api.md`, code and tests together.
Board publishing is implemented in the external TeamFalcons firmware repository.

### 2. Signatures

- `MqttClient(..., subscribe_filters: Sequence[tuple[str, int]] | None = None)`
  in `dashboard.transport.mqtt`. Omitted or empty filters mean no subscriptions.
- `MqttClient.publish_json(topic, payload, *, qos, retain) -> MQTTMessageInfo`
  supports JSON objects and telemetry arrays; callers specify wire policy.
- `build_subscriber(..., on_message) -> MqttClient` supplies exactly
  `vg/+/status`, `vg/+/telemetry`, `vg/+/alarm`, `vg/+/point_table`.
- `Collector.handle_message(topic: str, payload: bytes) -> None`.
- Entrypoints: `python -m dashboard`, `vg-dashboard`.
- Development publisher: `python -m dashboard.tools.synthetic_board`.

### 3. Contracts

All payloads are UTF-8 JSON with a **64 KiB** limit.

**status**:

- Requires non-empty `device_id` equal to the topic identity and boolean `online`.
- LWT minimum: `{"device_id":"dev01","online":false}`.
- Optional `firmware`, `build_mode`, `network`, `ts_ms`, `uptime_ms` and
  `time_quality` are preserved with unknown fields in the stored status.

**telemetry**:

- Top-level array of `{id, value, ok, age_ms}`.
- `id` is non-empty; `value` is numeric, text or null.
- Invalid entries are skipped. Missing/non-boolean `ok` becomes true;
  missing/invalid `age_ms` becomes null.
- Unknown point IDs are still stored and shown as unsynced values.

**alarm**:

- Requires `state=raised|cleared` and `id` (or alias `sensor_id`).
- Device time accepts `ts` or `ts_ms`; original payload is preserved.
- `alarm_id` is preferred for the state key; otherwise use device, point and kind.
- Duplicate raised events refresh an open alarm; cleared closes it.
  Orphan cleared messages only append an event.
- `ack` is display-only data. Only device reports change the cloud alarm state.

**point_table**:

- TeamFalcons JSON: `{schema_version, bus, hits, points:[...]}`.
- `schema_version` is integer `1`; `points` is non-empty.
- Point IDs match `[A-Za-z0-9_]{1,23}` and are unique per table.
- Preserve supported fields (`name`, `addr`, `fc`, `reg`, `qty`, `dtype`,
  `scale`, `unit`, `cmp`, `warn`, `crit`, `fail_n`) and unknown fields in `spec_json`.
- `warn` and `crit` may be absent but never null.
- Replace the current point set and append a full JSON sync-version record.

Device time is never rewritten after network recovery. Store cloud receipt
time separately as `received_ts_ms`.

**Runtime configuration**:

- MQTT: `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_CLIENT_ID`.
- TLS: `MQTT_TLS`, `MQTT_CA_PATH`, `MQTT_CLIENT_CERT_PATH`, `MQTT_CLIENT_KEY_PATH`.
  Blank paths mean unset; TLS requires existing files and a paired client cert/key.
  Certificate verification cannot be disabled. Plaintext ignores certificate paths.
- HTTP/storage: `HTTP_HOST`, `HTTP_PORT`, `DB_PATH`, `HISTORY_RETENTION_HOURS`,
  `MESSAGE_BUFFER_LIMIT`, `ALARM_EVENT_LIMIT`, `CLEANUP_INTERVAL_S`.
- `LOG_LEVEL` is normalized and validated. Defaults are in `.env.example`.
- Ports must be 1..65535; history/buffer/event/cleanup values must be positive.

### 4. Validation & Error Matrix

| Condition | Outcome |
|---|---|
| Valid message | Update domain state and record recent raw traffic |
| Non-JSON or non-UTF-8 | Quarantine with parse reason |
| Payload exceeds 64 KiB | Quarantine; retain only a bounded text preview |
| Schema violation or status identity mismatch | Quarantine; no domain update |
| Unsupported topic/kind | Quarantine as `unknown_topic`/`unknown_kind` |
| Duplicate retained snapshot | Update current state; table sync records may repeat |
| Duplicate raised alarm | Refresh last-seen/payload without another raise event |
| Orphan cleared alarm | Append event without opening an alarm |
| MQTT reconnect | Restore the same four subscriptions; publish nothing |
| Startup MQTT connection timeout | Nonzero process exit |
| Unexpected HTTP failure | Safe `500 {"error":"internal_error"}` |

Quarantine records keep the reason and receipt time in the bounded raw buffer.
Successful ingestion is debug-level logging; parser failures are warning-level,
unexpected processing/storage failures are error-level. Not every quarantine
branch emits a separate warning.

### 5. Good / Base / Bad Cases

- **Good**: Retained point table arrives before telemetry; the UI shows point
  names/units, and later samples map by ID.
- **Base**: Restart with the same SQLite file and restore retained snapshots;
  previous alarm history remains available.
- **Bad**: Malformed device JSON must not modify domain state or stop ingestion
  for another device. Never retain alarm/telemetry events.

### 6. Tests Required

- Contract: four filters, exact QoS/retain policy, payload cap and point schema.
- Unit: subscriber reconnects without publishes, publisher has no implicit
  subscriptions, JSON arrays remain arrays, TLS/mTLS validation and redaction.
- Unit: quarantine, timestamp preservation, alarm transitions, SQLite reopening
  and cleanup.
- HTTP: actual bound port, static assets, data API and rejected write methods.
- Integration: retained snapshots published before collector startup, live
  telemetry, alarm raise/clear, offline status and HTTP retrieval.
  Broker settings: `TEST_MQTT_HOST` and `TEST_MQTT_PORT`.

### 7. Wrong vs Correct

**Wrong**: Give a generic publisher an implicit topic subscription, or publish
device controls from a read-only dashboard.

**Correct**: `MqttClient` defaults to zero subscriptions; `build_subscriber`
explicitly selects the four dashboard filters, and all dashboard handlers stay
read-only.

**Wrong**: Assume QoS 1 prevents repeated alarm events or infer cloud time from
device uptime.

**Correct**: Apply the documented alarm state key and transitions; preserve
source time and store a separate receipt timestamp.
