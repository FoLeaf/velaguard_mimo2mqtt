# MQTT and AI Bridge Contracts

> Confirmed cloud/device protocol rules for the VelaGuard AI Bridge and the cloud dashboard.

---

## Repository Pivot (2026-09-13)

The primary product of this repository is now the **MQTT cloud dashboard**
(`dashboard/` package): a collector that subscribes to board-published topics,
persists state to SQLite, and serves a read-only web dashboard. The AI Bridge
(`ai_bridge/`) is **deprecated but kept**: its entry point still runs, its tests
stay green, and the dashboard reuses its MQTT client and observability infra.
New device-facing topics must be defined in `dashboard/contracts/topics.py` and
recorded here.

## Architecture Boundary

The fixed communication path is:

```text
VelaGuard -> MQTT Broker -> AI Bridge -> HTTPS -> MiMo / TTS / ASR / manual parsing
VelaGuard -> MQTT Broker -> Dashboard collector -> read-only web dashboard
```

VelaGuard, the AI Bridge, and the dashboard collector are separate MQTT Broker clients. The backend must not add a direct device-to-bridge socket or expose MiMo's HTTPS API to device business logic.

The AI Bridge account subscribes only to request topics and publishes only to response topics required by its role. The dashboard account subscribes only to the device-published topics listed under "Dashboard Consumption Contract". Broker deployment and ACL administration may be external infrastructure, but the backend must be designed and tested against that boundary.

The dashboard is **read-only end to end** (boundary V5): it never publishes to
device-facing topics, never acknowledges or clears alarms, and exposes no write
HTTP endpoint.

## Topics, QoS, and Retained Messages

The topic root is exactly `vg/{device_id}/...`; do not add an environment prefix.

| Message class | QoS | Retained |
|---|---:|---|
| `telemetry` | 0 | No |
| `trend` | 0 | No |
| `status` | 0 | May retain the latest state |
| `point_table` | 1 | **Yes** (amendment 2026-09-13: config-snapshot semantics like `status`, so late-joining dashboards receive the current table; still forbidden for events such as alarms/telemetry) |
| `alarm` | 1 | No |
| `ai/request`, `ai/response` | 1 | No |
| `config/candidate` | 1 | No |
| `tts/request`, `tts/response` | 1 | No |
| `voice/start`, `voice/chunk`, `voice/end`, `voice/result` | 1 | No |
| OTA offer/chunk/result/confirm messages | 1 | No |
| Acknowledgement/confirmation events | 1 | No |

Relevant documented topic forms include:

```text
vg/{device_id}/point_table
vg/{device_id}/ai/request
vg/{device_id}/ai/response/{req_id}
vg/{device_id}/tts/request
vg/{device_id}/tts/response/{req_id}
vg/{device_id}/voice/start
vg/{device_id}/voice/chunk/{session_id}/{seq}
vg/{device_id}/voice/end/{session_id}
vg/{device_id}/voice/result/{session_id}
vg/{device_id}/config/candidate
vg/{device_id}/status
vg/{device_id}/ota/offer
vg/{device_id}/ota/accept
vg/{device_id}/ota/chunk/request
vg/{device_id}/ota/chunk/data
vg/{device_id}/ota/progress
vg/{device_id}/ota/result
vg/{device_id}/ota/confirm
```

Centralize these definitions and reconcile the documented voice-chunk forms before implementation: section 8.3 shows `voice/chunk/{session_id}`, while confirmed section 16.4 gives the sequence-bearing example `voice/chunk/{session_id}/{seq}`. Prefer the section 16.4 form unless the contract is explicitly revised.

## MQTT Session Behavior

The v1 device contract uses a fixed `client_id`, `clean_session=true`, LWT, and resubscription after reconnect. Critical events rely on a local pending queue rather than a persistent MQTT session.

The backend must therefore:

- Be correct under at-least-once delivery and duplicate messages.
- Restore its own subscriptions after reconnect.
- Not assume Broker session persistence will provide application-level durability.
- Treat LWT/status as connectivity signals, not as proof that provider work completed.

Confirmed backend session settings: `MQTT_CLIENT_ID` (default `ai-bridge-dev`), `clean_session=true`, resubscribe `vg/+/ai/request` QoS 1 on every (re)connect, worker-thread dispatch off the network loop. TLS is opt-in via `MQTT_TLS=true` with optional `MQTT_CA_PATH` and the `MQTT_CLIENT_CERT_PATH`/`MQTT_CLIENT_KEY_PATH` mTLS pair; when TLS is on, configured paths must be existing files (startup fails fast) and no insecure skip-verify switch exists. Plaintext remains the dev default.

## Request Identity and Time

Every AI request contains:

- `req_id`
- `device_id`
- `created_ts_ms`
- `type`
- `payload_hash`

The response returns the same `req_id`. For device events, preserve `event_id` and `alarm_id` when present.

`payload_hash` is SHA-256 over the canonical request body (excluding `payload_hash` itself)
serialized as `json.dumps(body, sort_keys=True, separators=(",", ":"))`, matching
`ai_bridge.cli.synthetic_publisher.build_request`. Browser mocks such as
`debug-console/app.js` and `board-sim/board-core.js` must reproduce that canonical form
byte-for-byte for the same body.

Device time fields are Unix milliseconds plus runtime context:

```json
{
  "ts_ms": 1782450000000,
  "uptime_ms": 345678,
  "time_quality": "unknown|rtc|ntp|cloud"
}
```

The cloud adds `received_ts_ms`; it never rewrites historical device timestamps after network recovery.

## Idempotency

Use `req_id + payload_hash` as the AI Bridge idempotency key.

- Completed duplicate: publish the same response again.
- Processing duplicate: return or publish `status=processing` without duplicate provider work.
- Failed duplicate (accepted deviation from the project manual §16.4, recorded 2026-08-16): replay the stored error response; the bridge does not retry per failure category. Callers retry by issuing a new `req_id`.
- Same `req_id` with a different `payload_hash`: reject with `error_code=conflict`.
- The store is process-local and in-memory; restart clears all claim/complete/fail state (documented disposable behavior).

QoS 1 does not remove the need for this logic.

## Timeouts and Retries

Documented recommended task windows are:

| Task | Timeout |
|---|---:|
| Natural-language configuration | 15-30 seconds |
| Manual parsing | 60-180 seconds; prefer asynchronous work |
| ASR/TTS | 15-60 seconds, adjusted for audio length |

The backend supports timeout, retry, and error-code handling. Exact attempt counts and backoff values are not confirmed. Implement bounded retries only for transient failures, retain idempotency across retries, and keep provider-attempt timeouts inside the overall task deadline.

## Payload Boundaries

MQTT normally carries control JSON, small text, and short results. Do not place audio, PDF, images, complete manuals, or firmware in one ordinary MQTT message.

Voice upload rules:

- 4 KB or 8 KB per chunk.
- QoS 1.
- Prefer binary payloads.
- Include `total_chunks`, `sha256`, `duration_ms`, and `codec` metadata.
- Correlate chunks by session and sequence.

Manual/PDF flow:

- Prefer phone/Web upload to the cloud.
- Parse in a cloud service.
- Return `manual_profile`/`sensor_profile` rather than the complete document to the device.

OTA exception:

- MQTT/MQTTS is both control and data plane; do not require a device-side HTTPS firmware downloader.
- The cloud publishes only an OTA Offer; the locally confirmed device pulls chunks.
- Chunks are 4 KB or 8 KB with bounded in-flight count.
- The device owns staging writes, SHA-256 and digital-signature verification, self-test confirmation, and rollback.
- Backend serving must support interruption/failure without endangering the device's local collection, alarms, UI, or logging.

## AI Result Boundary

The bridge may publish structured diagnosis or candidate configuration output, but it never authorizes direct device control. Device-side schema validation, risk checks, preview/test-read flow, and local confirmation remain mandatory before applying write-like changes.

Provider output that is malformed, missing required fields, or not valid JSON must not be presented as a successful structured result.

## Scenario: Minimal AI MQTT loop (v1 implemented)

### 1. Scope / Trigger

Cross-layer MQTT request/response contract for the first `ai_bridge` slice. Any change to topics, required fields, envelope, error codes, or QoS/retain policy must update this section and tests together.

### 2. Signatures

- Subscribe filter: `vg/+/ai/request` (QoS 1)
- Publish topic: `vg/{device_id}/ai/response/{req_id}` (QoS 1, retain=false)
- Process entry: `python -m ai_bridge` / console script `ai-bridge`
- Package helpers: `ai_bridge.contracts.topics`, `request.parse_request`, `envelope.build_response`

### 3. Contracts

**Request required fields**

| Field | Type | Constraints |
|---|---|---|
| `req_id` | string | non-empty; echoed in every response when known |
| `device_id` | string | non-empty; must equal topic `{device_id}` |
| `created_ts_ms` | int | non-negative Unix ms; not bool |
| `type` | string | first slice supports `diagnosis` only |
| `payload_hash` | string | non-empty; part of idempotency key |

Ordinary AI JSON payload soft limit in code: **64 KiB**. Larger content does not belong on this topic.

**Response v1 envelope**

| Field | Type | Rules |
|---|---|---|
| `req_id` | string | always when known |
| `device_id` | string | when known |
| `type` | string | when known |
| `status` | string | `processing` \| `success` \| `error` |
| `error_code` | string\|null | required on `error`; null otherwise |
| `error_message` | string\|null | safe human text; null on non-error |
| `result` | object\|null | required on `success`; null otherwise |
| `received_ts_ms` | int | cloud receipt time |
| `bridge_ts_ms` | int | bridge decision/publish time |

**Error codes**: `validation_error`, `conflict`, `timeout`, `provider_error`, `internal_error`.

**Env keys (dev worker)**

| Key | Default | Required |
|---|---|---|
| `MQTT_HOST` | `localhost` | no |
| `MQTT_PORT` | `1883` | no |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | empty | no |
| `MQTT_CLIENT_ID` | `ai-bridge-dev` | no |
| `REQUEST_TIMEOUT_MS` | `30000` | no |
| `PROVIDER` | `stub` | no (`mimo` reserved) |
| `LOG_LEVEL` | `INFO` | no |
| `STUB_DELAY_MS` | `0` | no (test aid) |
| `SKILLS_DIR` | package `ai_bridge/skills` | no (skill markdown directory) |
| `DIAGNOSIS_SKILL` | `industrial_fault_diagnosis` | no (`^[a-z0-9_]+$`) |
| `FALLBACK_ENABLED` | `true` | no (degraded fallback switch) |

### 4. Validation & Error Matrix

| Condition | Provider called? | status | error_code |
|---|---|---|---|
| non-JSON / oversize / missing fields | no | error | validation_error |
| topic/payload `device_id` mismatch | no | error | validation_error |
| unsupported `type` | no | error | validation_error |
| processing duplicate | no (2nd) | processing | null |
| completed duplicate | no | replay stored envelope exactly | as stored |
| same `req_id`, different `payload_hash` | no | error | conflict |
| overall deadline exceeded | maybe | error | timeout |
| provider failure / invalid structured output | yes | error | provider_error |
| unexpected exception | maybe | error | internal_error |

### 5. Good / Base / Bad Cases

- **Good**: valid `diagnosis` request → `status=success`, structured object under `result`, same `req_id`.
- **Base**: completed duplicate → exact same stored response republished; provider not called again.
- **Bad**: same `req_id` new `payload_hash` → `conflict`; missing `payload_hash` → `validation_error` without provider work.

### 6. Tests Required

- Contract: topic parse/format; QoS/retain constants; request validation; envelope field rules.
- Unit: idempotency new/processing/completed/conflict; handle_request paths; stub result; secret redaction.
- Integration (optional broker): synthetic publish → response on response topic.
- Assertions must include: no second provider call on duplicates; exact completed replay; timeout code; secrets absent from logs/payloads.

### 7. Wrong vs Correct

#### Wrong

- Treating handbook local diagnosis **log** JSON as the MQTT response wire contract.
- Rebuilding a “similar” success response on completed duplicate instead of replaying the stored envelope.
- Handling provider work on the paho network-loop thread so duplicates cannot be observed as `processing`.

#### Correct

- Keep a stable v1 envelope; put diagnosis content under `result`.
- Store the published response dict and replay it byte-for-byte for completed duplicates.
- Dispatch inbound MQTT messages to worker threads; keep claim/complete under one idempotency lock.

## Scenario: MiMo provider (diagnosis adapter)

### 1. Scope / Trigger

Real MiMo HTTPS adapter behind the `Provider` seam. MQTT v1 envelope unchanged. Any change to the OpenAI-compatible call, result schema, retry policy, or env keys must update this section and tests.

### 2. Signatures

- Provider: `MiMoProvider.handle(request: AiRequest, *, deadline_s: float) -> ProviderResult`
- Wire call: `POST {MIMO_BASE_URL}/chat/completions` with `Authorization: Bearer <MIMO_API_KEY>`
- Build: `build_provider("mimo")` (raises `ValueError` if `MIMO_API_KEY` unset)

### 3. Contracts

**Env keys**

| Key | Default | Required |
|---|---|---|
| `MIMO_BASE_URL` | `https://token-plan-cn.xiaomimimo.com/v1` | no |
| `MIMO_MODEL` | `mimo-v2.5` (confirmed live) | no |
| `MIMO_API_KEY` | unset | yes when `PROVIDER=mimo` |
| `MIMO_HTTP_TIMEOUT_MS` | `15000` | no |
| `MIMO_MAX_RETRIES` | `2` | no (bounded 0..5) |
| `MIMO_RETRY_BACKOFF_MS` | `500` | no |

**Request body**: `{"model": MIMO_MODEL, "messages": [{"role":"system",...},{"role":"user",...}], "temperature": 0, "response_format": {"type":"json_object"}}`

**Result schema (v2 diagnosis)** — validated before success:

| Field | Type | Rule |
|---|---|---|
| `diagnosis_summary` | string | required, non-empty |
| `risk_level` | string | required, `low` \| `medium` \| `high` |
| `possible_causes` | list[string] | required, empty allowed |
| `recommended_actions` | list[string] | required, empty allowed |
| `need_shutdown` | boolean | required; bool-like ints rejected |
| `reasons` | list[str] | optional |
| `recommendations` | list[str] | optional |
| `confidence` | number | optional, 0..1; bool rejected |
| (unknown keys) | any | passed through |

Adapter adds `"source": "mimo"` on success.

### 4. Validation & Error Matrix

| MiMo condition | Action | ProviderFailure code |
|---|---|---|
| 200 + valid schema | normalize + `source=mimo` | success |
| 200 + invalid JSON / missing summary / bad types | no retry | provider_error |
| 401/403/400 | no retry | provider_error |
| 429 / 5xx / network | bounded retry with backoff+jitter | exhausted → provider_error |
| deadline exceeded at any point | abort | timeout |
| unexpected exception | abort | timeout (bounded by deadline) |

Never map provider failure to `internal_error`. On the final retry attempt, do **not** sleep past the remaining deadline (otherwise `provider_error` flips to `timeout`).

Failure classification for fallback: schema-invalid output has `fallback_eligible=False`; 401/403/400, exhausted 429/5xx, and network failures have `fallback_eligible=True`. Timeout always has `fallback_eligible=False`.

### 5. Good / Base / Bad Cases

- **Good**: valid JSON schema → `status=success`, `result.diagnosis_summary` + `source=mimo`, same `req_id`.
- **Base**: 429 once then 200 → success after one retry; exhausted 5xx → `provider_error`.
- **Bad**: MiMo returns `{"foo": 1}` → `provider_error`; slow past deadline → `timeout`; key missing → startup `ValueError`.

### 6. Tests Required

- Wire-shape (request body, headers, Bearer auth), schema matrix, retry matrix, timeout path, no-key startup error, redaction of `mimo_api_key` in logs.
- Regression: existing stub provider tests stay green; `pytest tests/unit tests/contract`.

### 7. Wrong vs Correct

#### Wrong

- Sleeping full backoff on the final attempt, then reporting `timeout` for an exhausted transient failure.
- Retrying 4xx/validation failures, or leaking `MIMO_API_KEY` into logs/error messages.

#### Correct

- Sleep backoff only when a further attempt is possible; exhausted transients → `provider_error`.
- `provider_error` for any MiMo output that fails the fixed JSON schema; no success without validation.

## Scenario: Diagnosis context + v2 result + fallback

### 1. Scope / Trigger

`type=diagnosis` requests may carry an optional structured `context` payload.
The bridge normalizes that context into a bounded prompt, loads a diagnosis
Skill file, and, when MiMo fails for an eligible transport reason, publishes a
schema-valid degraded fallback result instead of only an error envelope.

### 2. Signatures

- Request: v1 fields + optional top-level `context` object.
- Context normalization: `ai_bridge.runtime.json_validator.normalize_diagnosis_context(raw_context) -> ContextBundle`
- Prompt: `ai_bridge.runtime.prompt_builder.build_diagnosis_messages(request, skill_text)`
- Skill: `ai_bridge.runtime.skill_manager.SkillManager(skills_dir).load(DIAGNOSIS_SKILL)`
- Fallback: `ai_bridge.runtime.fallback.build_fallback_diagnosis(request, reason) -> dict`
- Assembly: `build_provider("mimo")` injects `system_prompt` + `user_content_builder` into `MiMoProvider`.

### 3. Contracts

**Request `context` (optional)**

| Field | Type | Rule |
|---|---|---|
| `context` | object | present but non-object → `validation_error` |
| `context.event` | object | non-object → warn + drop |
| `context.device` | object | non-object → warn + drop |
| `context.history` | array | max 50 entries; non-object entries dropped; oversized serialization truncated |
| `context.rules` | array | max 20 entries; non-object entries dropped; oversized serialization truncated |
| `context.sensor_config` | object | sensor register map; non-object → warn + drop |
| `context.manual_summary` | string | manual digest; non-string → warn + drop |

Section serialization limits: event 4096 chars, device 2048 chars, rules 8192
chars, history 16384 chars, sensor_config 4096 chars, manual_summary 2048
chars. Truncation appends a `...[truncated]` marker and
logs a warning. Missing sections are reported as `context_notes` in the user
prompt. History entries missing `ts_ms`/`values` are kept with an explicit
`__missing__` marker list and a warning. The single user message is bounded to
8192 chars (identity fields are truncated if needed so the bound holds
unconditionally).

**Result schema v2** — shared by MiMo, stub, and fallback:

| Field | Type | Rule |
|---|---|---|
| `diagnosis_summary` | string | required, non-empty |
| `risk_level` | string | required, `low` \| `medium` \| `high` |
| `possible_causes` | list[string] | required, empty allowed |
| `recommended_actions` | list[string] | required, empty allowed |
| `need_shutdown` | boolean | required; bool-like ints rejected |
| `confidence` | number | optional, `[0, 1]`; bool rejected; range check must compare directly (`0.0 <= x <= 1.0`), never via `float(x)` conversion |
| `reasons` / `recommendations` | list[string] | optional, legacy |
| (unknown keys) | any | passed through |

`ai_bridge/providers/schema.py::validate_diagnosis_result` is the single
validation owner for provider/fallback/stub output.

**Language contract:** Explanatory diagnosis fields (`diagnosis_summary`, `possible_causes`, `recommended_actions`, `reasons`, and `recommendations`) should use Simplified Chinese as the primary language. Device IDs, field names, units, error codes, model/product names, code expressions, and necessary technical terms may remain in their original form. This is a prompt/fixed-template contract; schema validation must remain language-agnostic.

**Fallback semantics**

- Trigger: `ProviderFailure(code="provider_error")` with `fallback_eligible=True`,
  `FALLBACK_ENABLED=true`, and remaining request budget > 0.
- Result: `status=success`, `result.source="fallback"`,
  `result.advisory_only=true`, `result.confidence=0.0`, plus
  `result.fallback_reason`; passes v2 schema.
- The fallback response is stored like any success and replayed exactly on
  duplicate requests.
- No new envelope status (`degraded` is not added).

**Error matrix**

| Scenario | Published |
|---|---|
| MiMo success (v2 valid) | `success` + `source=mimo` |
| MiMo schema-invalid | `error` + `provider_error` (no fallback) |
| MiMo HTTP/network failure, budget remains, fallback enabled | `success` + `source=fallback` |
| Deadline exceeded | `error` + `timeout` (no fallback) |
| `FALLBACK_ENABLED=false` | `error` + `provider_error` |

### 4. Tests Required

- Context normalization: non-object drop (including sensor_config object rule
  and manual_summary string rule), history 50 / rules 20 limits, marker
  truncation, missing-section notes, total user-content bound.
- Skill manager: load/cache, missing/empty fallback, name whitelist.
- Fallback builder: v2 schema validity, severity→risk mapping, fixed template.
- Application: fallback trigger, disabled/ineligible/timeout/budget-exhausted
  non-trigger, exact replay, builder failure → `internal_error`.
- MiMo: injected prompt contains context, `fallback_eligible` classification,
  no API key in prompt/logs.

### 5. Wrong vs Correct

#### Wrong

- Falling back on schema-invalid MiMo output or after the deadline.
- Publishing fallback when `FALLBACK_ENABLED=false`.
- Letting fallback echo arbitrary raw payload into the summary.
- Truncating the user message into invalid JSON.
- Validating numeric ranges with `float(x)` — huge integers (e.g. `10**1000`)
  raise `OverflowError`, which escapes the schema-invalid path and surfaces as
  `internal_error` instead of `provider_error`.

#### Correct

- Fallback only for eligible transport/provider failures inside the budget.
- Template-based, schema-validated fallback result with `source=fallback`.
- Bounded, valid-JSON prompt; missing context explicitly marked.
- Idempotent replay for fallback responses identical to normal success.
- Compare numeric fields directly against the range so out-of-range values are
  rejected as `provider_error` without conversion or overflow.

## Scenario: Dashboard consumption contract (v1, implemented)

### 1. Scope / Trigger

The dashboard collector consumes board-published topics. Any change to the
subscribed filters, payload field rules, or persistence semantics below must
update this section, `dashboard/contracts/topics.py`, and tests together.
Board-side publishing lives in the TeamFalcons firmware repo (its C1 plan); the
collector must stay tolerant of fields it does not know.

### 2. Signatures

- Subscribe filters (all from one collector client, QoS per table above):
  `vg/+/status`, `vg/+/telemetry`, `vg/+/alarm`, `vg/+/point_table`
- Process entry: `python -m dashboard` / console script `vg-dashboard`
- Synthetic board for tests/demo: `python -m dashboard.tools.synthetic_board`

### 3. Contracts

**status** (QoS 0, retained; LWT publishes `{"device_id":"...","online":false}`
retained on the same topic):

| Field | Type | Rule |
|---|---|---|
| `device_id` | string | non-empty; must equal topic `{device_id}`; mismatch → quarantine |
| `online` | boolean | required; bool-like ints rejected |
| `firmware` | string | optional |
| `build_mode` | string | optional |
| `network` | string | optional (`rj45\|esp01\|none` expected, unknown tolerated) |
| `uptime_ms`, `ts_ms` | int | preserved as received |
| `time_quality` | string | preserved (`unknown\|rtc\|ntp\|cloud` expected) |
| (unknown keys) | any | preserved in `last_status_json` |

**telemetry** (QoS 0, not retained; TeamFalcons C1 format):

- Top-level JSON array of `{id, value, ok, age_ms}` objects; `id` string non-empty,
  `ok` boolean (missing → `true`), `age_ms` non-negative int (missing → null).
- The collector records `received_ts_ms` separately; it never rewrites device time.
- Point ids not present in the synced point table are still stored and shown raw.

**alarm** (QoS 1, not retained):

- Tolerant field aliases: `ts` or `ts_ms` (device time, preserved);
  `id` or `sensor_id` (point id); `kind`, `value`, `thr` optional.
- `state` required: `raised` or `cleared` (unknown state values quarantined).
- `alarm_id` preserved when present. Dedup/state key: `alarm_id` if present,
  else `(device_id, point id, kind)`. Duplicate `raised` for an active alarm
  updates `last_seen` only; `cleared` closes it; `cleared` without an open
  alarm is recorded as an event only.
- The dashboard never acknowledges or clears alarms (V5). `ack` fields are
  display-only passthrough.

**point_table** (QoS 1, **retained**; new topic defined by this task):

- Payload is the TeamFalcons device point-table JSON:
  `{schema_version, bus, hits, points:[...]}`.
- `schema_version` must be `1` (int). `points` must be a non-empty array; each
  point requires `id` matching `[A-Za-z0-9_]{1,23}` and tolerates
  `name, addr, fc, reg, qty, dtype, scale, unit, cmp, warn, crit, fail_n`.
  Unknown fields are preserved in `spec_json`.
- Constraint values (`warn`/`crit`) may be omitted but never `null` (TeamFalcons rule).
- On ingest, the collector upserts the device's points, records a version row
  (full table JSON) in the sync history, and the UI renders from it.

**Quarantine rule**: any message that is non-JSON, oversized (> 64 KiB soft cap),
schema-invalid per above, or has a topic/payload `device_id` mismatch is stored
in the raw-message buffer with a quarantine reason and logged at `warn`; it
never crashes the collector and never enters the domain tables.

### 4. Validation & Error Matrix

| Condition | Domain tables updated? | Log level |
|---|---|---|
| valid message | yes | info |
| non-JSON / oversize / schema-invalid | no (raw buffer only) | warn |
| `device_id` topic/payload mismatch | no (raw buffer only) | warn |
| duplicate retained `status`/`point_table` delivery | yes (idempotent upsert) | info |
| duplicate `alarm` raised for open alarm | `last_seen_ts_ms` only | info |
| `cleared` without open alarm | event log only | info |

### 5. Good / Base / Bad Cases

- **Good**: retained `point_table` arrives before any telemetry → device detail
  page renders names/units from the table; later `telemetry` values map by `id`.
- **Base**: collector restart → retained `status` and `point_table` restore the
  fleet view; in-flight alarms published while offline are lost (documented
  limitation; board pending queue is the device-side remedy).
- **Bad**: alarm QoS 0 or retained alarm/telemetry is a forbidden-pattern
  violation; oversized JSON must be quarantined, not stored.

### 6. Tests Required

- Contract: filter list, QoS/retain constants, point-table schema matrix,
  device-id mismatch quarantine, 64 KiB cap.
- Unit: status/telemetry/alarm normalization matrix, alarm state machine
  (open/refresh/clear/orphan-clear), SQLite upsert idempotency, retention cleanup.
- Integration (optional broker): synthetic_board → collector → HTTP API.

### 7. Wrong vs Correct

#### Wrong

- Publishing anything from the dashboard to `vg/{device_id}/...` (V5 violation).
- Retaining alarms or telemetry, or lowering alarm QoS to 0.
- Rewriting `ts_ms`/`uptime_ms`/`time_quality` on ingest.
- Trusting QoS 1 to deduplicate alarms without an application-level key.

#### Correct

- Read-only collector: subscribe four filters, upsert idempotently, add
  `received_ts_ms` alongside preserved device time.
- Quarantine invalid input with a reason; keep serving the rest of the fleet.
- Treat retained `status`/`point_table` as state snapshots, events never retained.

## Source References

- `VelaGuard_项目手册.md`: sections 2.1-2.2, 5.4-5.5, 8.3-8.4, 12.1, and 16.2-16.5, 16.9.
- `VelaGuard_推进方案.md`: sections 1, 6.2-6.5, 8.2, 9.2, and 16.3-16.5, 16.9.
