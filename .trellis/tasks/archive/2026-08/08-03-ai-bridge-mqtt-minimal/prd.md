# AI Bridge minimal MQTT loop

## Goal

Deliver the first cloud-side AI Bridge slice that completes one end-to-end MQTT AI request/response loop for VelaGuard, without device firmware work in this repository.

## Background

This repository owns the cloud AI Bridge only. Confirmed path:

```text
VelaGuard -> MQTT Broker -> AI Bridge -> HTTPS providers (MiMo / later TTS/ASR/manual)
```

Frozen protocol boundary (root docs + `.trellis/spec/backend/`):

- Topic root: `vg/{device_id}/...` (no environment prefix)
- Request: `vg/{device_id}/ai/request`
- Response: `vg/{device_id}/ai/response/{req_id}`
- AI request/response: QoS 1, not retained
- Required request fields: `req_id`, `device_id`, `created_ts_ms`, `type`, `payload_hash`
- Idempotency key: `req_id + payload_hash`
- MQTT carries control JSON / short text / short results only
- Provider secrets stay on the cloud server
- AI output is advisory; device-side safety confirmation is out of this repo

There is currently no business code.

## Confirmed Facts

- Repo is backend-only; frontend and device firmware are out of scope.
- Bootstrap backend guidelines are complete and archived.
- Protocol contracts live in `.trellis/spec/backend/mqtt-ai-bridge-contracts.md` and related guides.
- This task targets a **minimal MQTT loop**, not full Stage 3 AI diagnosis product surface.

## Scope Decision

**First slice = contract loop + pluggable provider**

Included:

- Subscribe to `vg/{device_id}/ai/request`
- Validate required request fields
- Apply idempotency key `req_id + payload_hash`
- Invoke a Provider interface (default stub/mock; switchable to real MiMo later)
- Publish `vg/{device_id}/ai/response/{req_id}` for `processing` / `success` / `error`
- Bound overall request deadline and stable error codes
- Keep provider secrets server-side only
- Local verification with Docker Compose Mosquitto + synthetic publisher

Runtime / storage decisions for this task:

- Runtime: **Python 3.12+**
- Idempotency: **in-memory, explicitly disposable** (not restart-safe production behavior)
- Dev Broker: **Docker Compose Mosquitto**, controlled-LAN plaintext MQTT
- Default provider path does **not** require live MiMo credentials

## Wire Contract (v1 minimal envelope)

### Request (device → bridge)

Required fields already frozen:

| Field | Notes |
|---|---|
| `req_id` | Originator-generated; echoed in every response |
| `device_id` | Must match topic `device_id` |
| `created_ts_ms` | Device-side create time (ms) |
| `type` | e.g. `diagnosis` for the first slice |
| `payload_hash` | Part of idempotency key |

Additional payload body fields may exist per `type`; first-slice validation focuses on the required envelope fields above.

### Response (bridge → device)

Common envelope for all statuses:

```json
{
  "req_id": "...",
  "device_id": "...",
  "type": "...",
  "status": "processing|success|error",
  "error_code": null,
  "error_message": null,
  "result": null,
  "received_ts_ms": 1782450000123,
  "bridge_ts_ms": 1782450000456
}
```

Rules:

- Always echo `req_id` when known.
- Echo `device_id` and `type` when known from a parsed request.
- `status` is one of: `processing`, `success`, `error`.
- `error_code` / `error_message` are null on non-error statuses.
- `result` is null unless `status=success`.
- `received_ts_ms` is cloud receipt time; never rewrite device historical timestamps.
- `bridge_ts_ms` is bridge publish/decision time.
- Local device diagnosis **log** examples in the handbook are not the MQTT wire contract.

### v1 error codes

| Code | When |
|---|---|
| `validation_error` | Missing/invalid required fields, non-JSON, oversized ordinary payload |
| `conflict` | Same `req_id` with different `payload_hash` |
| `timeout` | Overall request deadline exceeded |
| `provider_error` | Provider returned failure / invalid structured output |
| `internal_error` | Unexpected bridge failure |

Exact retry counts/backoff remain design details; public codes above are frozen for this slice.

### Success `result` shape (stub diagnosis)

For `type=diagnosis` and `status=success`, stub provider returns a small structured object, for example:

```json
{
  "diagnosis_summary": "stub: no live MiMo call",
  "source": "stub",
  "advisory_only": true
}
```

This is advisory structured output only; it never authorizes device writes.

## Requirements

- R1. Bridge connects to MQTT Broker as an independent client and restores AI request subscriptions after reconnect.
- R2. Bridge accepts AI requests on `vg/{device_id}/ai/request` with QoS 1, not retained.
- R3. Bridge validates required fields and topic/payload device_id consistency; rejects malformed input without provider work when possible.
- R4. Bridge uses `req_id + payload_hash` idempotency while the process is alive:
  - completed duplicate → republish same response
  - processing duplicate → publish `status=processing` without second provider call
  - same `req_id`, different `payload_hash` → `error` + `conflict`
- R5. Bridge orchestrates through a Provider interface; default is stub/mock with contract-valid output.
- R6. Bridge publishes on `vg/{device_id}/ai/response/{req_id}` using the v1 envelope, QoS 1, not retained.
- R7. Bridge enforces a bounded overall request deadline; timeout publishes `error` + `timeout` rather than silent drop.
- R8. Secrets never appear in MQTT payloads, logs, or error bodies.
- R9. End-to-end verification needs no device firmware: local Mosquitto + synthetic publisher.
- R10. Docs state that in-memory idempotency is disposable and not production restart-safe.
- R11. Repo provides Docker Compose Mosquitto for local verification and documents how to run it.

## Acceptance Criteria

- [ ] AC1. Valid synthetic request on `vg/{device_id}/ai/request` yields a response on `vg/{device_id}/ai/response/{req_id}` with the same `req_id` and v1 envelope fields.
- [ ] AC2. Malformed requests missing required fields do not call the provider; publishable failures use `status=error` and `error_code=validation_error` when correlation is possible.
- [ ] AC3. Completed duplicate (`same req_id + payload_hash`) republishes the same response and does not re-invoke the provider while the process is alive.
- [ ] AC4. Processing duplicate does not start a second provider call while the process is alive; response uses `status=processing`.
- [ ] AC5. Same `req_id` with different `payload_hash` yields `status=error` and `error_code=conflict`.
- [ ] AC6. Default stub provider path completes the loop without real MiMo credentials.
- [ ] AC7. Provider interface is switchable by config/code seam so a real MiMo adapter can be added without changing MQTT contracts.
- [ ] AC8. Timeout path publishes `status=error` and `error_code=timeout` with `req_id` correlation.
- [ ] AC9. Secrets are absent from published payloads and redacted from logs on the verification path.
- [ ] AC10. End-to-end verification runs against local/dev Mosquitto with a synthetic publisher; no device firmware required.
- [ ] AC11. README states clearly that in-memory idempotency is disposable / not restart-safe production behavior.
- [ ] AC12. README documents Docker Compose command(s) to start Mosquitto for local verification.
- [ ] AC13. Success diagnosis responses put structured content under `result`, not as ad-hoc top-level-only fields outside the envelope.

## Out of Scope

- Device firmware `ai_bridge_client`, LVGL AI diagnosis UI, local fallback templates
- TTS / ASR / manual parsing / OTA
- Production Broker ACL administration as a product feature
- Mobile/Web remote configuration
- Full Stage 3 diagnosis product polish
- Mandatory live MiMo call on the default verification path
- Durable idempotency storage
- Production MQTTS / token / ACL enforcement

## Open Questions

None blocking planning. Library choices (MQTT client, test runner, packaging layout) are design/implement details.

## Notes

- Complex task: `design.md` and `implement.md` are required before `task.py start`.
- Keep technical library and module layout decisions in `design.md`, not here.
