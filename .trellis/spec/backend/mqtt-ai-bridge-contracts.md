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

## Source References

- `VelaGuard_项目手册.md`: sections 2.1-2.2, 5.4-5.5, 8.3-8.4, 12.1, and 16.2-16.5, 16.9.
- `VelaGuard_推进方案.md`: sections 1, 6.2-6.5, 8.2, 9.2, and 16.3-16.5, 16.9.
