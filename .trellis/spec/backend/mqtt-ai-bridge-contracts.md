# MQTT and AI Bridge Contracts

> Confirmed cloud/device protocol rules for the VelaGuard AI Bridge.

---

## Architecture Boundary

The fixed communication path is:

```text
VelaGuard -> MQTT Broker -> AI Bridge -> HTTPS -> MiMo / TTS / ASR / manual parsing
```

VelaGuard and the AI Bridge are separate MQTT Broker clients. The backend must not add a direct device-to-bridge socket or expose MiMo's HTTPS API to device business logic.

The AI Bridge account subscribes only to request topics and publishes only to response topics required by its role. Broker deployment and ACL administration may be external infrastructure, but the backend must be designed and tested against that boundary.

## Topics, QoS, and Retained Messages

The topic root is exactly `vg/{device_id}/...`; do not add an environment prefix.

| Message class | QoS | Retained |
|---|---:|---|
| `telemetry` | 0 | No |
| `trend` | 0 | No |
| `status` | 0 | May retain the latest state |
| `alarm` | 1 | No |
| `ai/request`, `ai/response` | 1 | No |
| `config/candidate` | 1 | No |
| `tts/request`, `tts/response` | 1 | No |
| `voice/start`, `voice/chunk`, `voice/end`, `voice/result` | 1 | No |
| OTA offer/chunk/result/confirm messages | 1 | No |
| Acknowledgement/confirmation events | 1 | No |

Relevant documented topic forms include:

```text
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

Exact backend `client_id`, clean-session setting, reconnect intervals, and subscription partitioning are not yet confirmed and must be chosen without breaking the device contract.

## Request Identity and Time

Every AI request contains:

- `req_id`
- `device_id`
- `created_ts_ms`
- `type`
- `payload_hash`

The response returns the same `req_id`. For device events, preserve `event_id` and `alarm_id` when present.

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
- Failed duplicate: retry only when the recorded failure category allows it.
- Same `req_id` with a different `payload_hash`: reject as a conflict/invalid replay; the exact error code remains to be designed.

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

## Scenario: MiMo provider (v1 diagnosis adapter)

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
| `MIMO_MODEL` | `mimo-chat` (confirm live) | no |
| `MIMO_API_KEY` | unset | yes when `PROVIDER=mimo` |
| `MIMO_HTTP_TIMEOUT_MS` | `15000` | no |
| `MIMO_MAX_RETRIES` | `2` | no (bounded 0..5) |
| `MIMO_RETRY_BACKOFF_MS` | `500` | no |

**Request body**: `{"model": MIMO_MODEL, "messages": [{"role":"system",...},{"role":"user",...}], "temperature": 0, "response_format": {"type":"json_object"}}`

**Result schema (v1 diagnosis)** — validated before success:

| Field | Type | Rule |
|---|---|---|
| `diagnosis_summary` | string | required, non-empty |
| `reasons` | list[str] | optional |
| `recommendations` | list[str] | optional |
| `confidence` | number | optional, 0..1 |
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

## Source References

- `VelaGuard_项目手册.md`: sections 2.1-2.2, 5.4-5.5, 8.3-8.4, 12.1, and 16.2-16.5, 16.9.
- `VelaGuard_推进方案.md`: sections 1, 6.2-6.5, 8.2, 9.2, and 16.3-16.5, 16.9.
