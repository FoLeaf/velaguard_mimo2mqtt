# Design: AI Bridge minimal MQTT loop

## Summary

Build a Python 3.12+ cloud AI Bridge process that:

1. Connects to MQTT Broker as an independent client
2. Subscribes to `vg/+/ai/request`
3. Validates request envelope fields
4. Applies in-memory `req_id + payload_hash` idempotency
5. Calls a pluggable Provider (default stub)
6. Publishes v1 response envelope on `vg/{device_id}/ai/response/{req_id}`

This slice proves protocol correctness. It does not deliver durable storage, production MQTTS/token/ACL, or live MiMo by default.

## Architecture Boundaries

Map to `.trellis/spec/backend/directory-structure.md` responsibilities; create only modules needed by this slice.

```text
ai_bridge/                         # Python package root (exact physical path decided in implement)
  __init__.py
  __main__.py / entrypoints/       # process startup, wiring
  configuration/                   # env/config validation
  contracts/                       # topics, request/response models, error codes
  transport/mqtt/                  # client, subscribe, publish, reconnect resubscribe
  application/                     # orchestration, deadline, idempotency decisions
  providers/                       # Provider protocol + stub (+ optional mimo seam)
  persistence/                     # in-memory idempotency store
  observability/                   # structured logging + redaction helpers
tests/
  contract/
  unit/
  integration/                     # needs local Mosquitto
deploy/dev/
  docker-compose.yml               # Mosquitto for local verification
  mosquitto/                       # minimal conf (plaintext, controlled-LAN)
```

Dependency direction:

- entrypoint → wires config, mqtt, store, provider, use case
- mqtt transport → parses topics/payloads into contracts, calls application, publishes results
- application → owns validation orchestration, idempotency, deadline, provider call, response shaping
- providers → isolate external AI; no MQTT knowledge
- persistence → narrow interface for claim/get/complete/fail
- contracts → shared wire models only; no I/O

## Data Flow

```text
MQTT message on vg/{device_id}/ai/request
  → parse JSON
  → validate required fields + topic/payload device_id match
  → received_ts_ms = now
  → idempotency.claim(req_id, payload_hash)
      processing hit  → publish status=processing; stop
      completed hit   → republish stored response; stop
      conflict        → publish status=error error_code=conflict; stop
      new claim       → continue
  → (optional) publish status=processing
  → provider.generate(request) under remaining deadline
  → on success: store completed response; publish status=success + result
  → on provider/invalid output: store failed; publish status=error provider_error
  → on deadline: store failed; publish status=error timeout
  → on unexpected: store failed; publish status=error internal_error
```

At-least-once delivery means duplicates are normal. QoS 1 does not remove idempotency.

## Contracts

### Topics

| Direction | Topic | QoS | Retained |
|---|---|---:|---|
| subscribe | `vg/+/ai/request` | 1 | no |
| publish | `vg/{device_id}/ai/response/{req_id}` | 1 | no |

Centralize topic parse/format helpers; do not scatter string literals.

### Request model

Required:

- `req_id: str`
- `device_id: str`
- `created_ts_ms: int`
- `type: str`
- `payload_hash: str`

First-slice supported `type`: `diagnosis` (other types may be rejected as `validation_error` or accepted with stub generic result — prefer reject unknown types as validation_error for a tight contract).

### Response model (v1)

```json
{
  "req_id": "...",
  "device_id": "...",
  "type": "...",
  "status": "processing|success|error",
  "error_code": null,
  "error_message": null,
  "result": null,
  "received_ts_ms": 0,
  "bridge_ts_ms": 0
}
```

Error codes: `validation_error`, `conflict`, `timeout`, `provider_error`, `internal_error`.

### Idempotency store interface

```text
claim(key) -> New | Processing | Completed(response) | Conflict
complete(key, response) -> None
fail(key, response) -> None   # terminal classified failure for this attempt policy
```

Key = `(req_id, payload_hash)` conceptually; conflict detection also needs index by `req_id` alone.

In-memory implementation:

- dict / lock-protected structure
- process lifetime only
- document disposable behavior in README

## Provider Seam

```text
protocol Provider:
  async/sync handle(request, deadline) -> ProviderSuccess(result) | ProviderFailure(code, message)
```

- `StubProvider`: deterministic diagnosis result; optional artificial delay for timeout tests
- `MiMoProvider`: optional later; not required for default acceptance; config may reserve `PROVIDER=stub|mimo` without implementing full MiMo HTTP now if time-boxed — **minimum for this task is the interface + stub**. A thin real adapter may be added only if it does not expand scope past MQTT loop proof.

Application must not depend on provider-specific response shapes; normalize into `result` object before publish.

## Configuration

Env-driven, validated at startup (names illustrative):

| Variable | Purpose | Default (dev) |
|---|---|---|
| `MQTT_HOST` | Broker host | `localhost` |
| `MQTT_PORT` | Broker port | `1883` |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | optional auth | empty |
| `MQTT_CLIENT_ID` | bridge client id | `ai-bridge-dev` |
| `REQUEST_TIMEOUT_MS` | overall deadline | e.g. `30000` |
| `PROVIDER` | `stub` (default) | `stub` |
| `LOG_LEVEL` | logging | `INFO` |

No production secrets in repo. If MiMo later: key via env only, never logged.

## MQTT Client Behavior

- Independent bridge client (not device)
- On connect/reconnect: resubscribe `vg/+/ai/request` QoS 1
- Publish responses QoS 1, retain=false
- Do not assume Broker session durability (`clean_session`/equivalent true is acceptable for v1 bridge)
- Exact library: prefer a maintained Python MQTT client (e.g. `paho-mqtt` or `aiomqtt`); final pick recorded in implement notes / README when coded

Sync vs async: either is fine if boundaries stay clean. Prefer the simpler path that still supports deadline cancellation and reconnect.

## Error Handling Mapping

Align with `.trellis/spec/backend/error-handling.md`:

| Condition | Provider called? | status | error_code |
|---|---|---|---|
| bad JSON / missing fields | no | error | validation_error |
| topic/payload device_id mismatch | no | error | validation_error |
| unknown type (first slice) | no | error | validation_error |
| processing duplicate | no (second) | processing | null |
| completed duplicate | no | (replay stored) | as stored |
| req_id reuse different hash | no | error | conflict |
| provider timeout / deadline | maybe partial | error | timeout |
| provider bad output | yes | error | provider_error |
| unexpected exception | maybe | error | internal_error |

Publish correlatable errors when `req_id` (and ideally `device_id`) are known. If topic `device_id` exists but body is garbage, still attempt best-effort response only when safe; otherwise log and drop with error metric/log.

## Observability

Structured logs with:

- `device_id`, `req_id`, `type`, `payload_hash` (safe), idempotency outcome, elapsed ms, status, error_code

Never log:

- passwords, tokens, API keys, full provider bodies, complete diagnosis dumps beyond short safe summaries

## Local Dev Broker

`deploy/dev/docker-compose.yml` runs Eclipse Mosquitto:

- plaintext `1883` bound to localhost (document controlled-LAN only)
- allow anonymous or single test user
- optional simple ACL allowing bridge subscribe `vg/+/ai/request` and publish `vg/+/ai/response/#`

Not a production ACL product.

## Testing Strategy

### Contract / unit (no Broker required)

- topic parse/format
- request validation
- response envelope serialization
- idempotency state machine (new / processing / completed / conflict)
- timeout classification
- stub provider result shape
- secret redaction helper

### Integration (Mosquitto required)

- publish valid request → receive success response
- duplicate completed → same response, provider once
- processing duplicate behavior (with delayed stub)
- conflict path
- validation_error path
- timeout path

Use a synthetic publisher script or test client in-repo.

## Compatibility / Rollout

- Greenfield: no migration
- Wire contract introduced here becomes the device-facing baseline for later firmware `ai_bridge_client`
- Durable store later must preserve the same external envelope and idempotency semantics

## Rollback

- Slice is additive greenfield code; rollback = do not deploy / revert commit
- Dev compose stack is local-only

## Explicit Non-Goals in Design

- No FastAPI/web admin unless needed for health; prefer pure MQTT worker for minimal loop
- No SQL/Redis
- No TTS/ASR/manual/OTA modules
- No production TLS termination design beyond “not in this slice”
