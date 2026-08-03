# Error Handling

> Failure handling for MQTT requests, cloud providers, and backend operations.

---

## Principles

- Fail safely and return a correlatable result; do not turn a known failure into an untracked timeout when a response can be published.
- Preserve `req_id` in every response for a request that reached the bridge.
- Separate validation, authorization, transport, upstream, timeout, retryable, and terminal failures internally. Exact public error codes remain undecided.
- Validate provider output before publishing it as structured success.
- Never allow an AI/provider response to bypass device schema validation, risk checks, test reads, or local confirmation.
- Backend failure is an enhancement failure and must not instruct the device to stop local collection, alarms, UI, logging, or local audio.

## Request Handling

1. Parse the topic and identify `device_id` and request type.
2. Enforce Broker identity assumptions and reject topic/payload identity mismatch.
3. Validate `req_id`, `device_id`, `created_ts_ms`, `type`, and `payload_hash`.
4. Check `req_id + payload_hash` before starting provider work.
5. Apply the task deadline and provider-specific retry policy.
6. Validate and normalize the provider result into the VelaGuard contract.
7. Persist replayable completion or classified failure state.
8. Publish with required QoS and without retained delivery for request/response traffic.

## Duplicate Requests

- Completed duplicate: republish the same response.
- Processing duplicate: return or publish `status=processing`; do not launch duplicate work.
- Failed duplicate: retry only when the recorded failure type and retry budget allow it.
- Same `req_id` with a different `payload_hash`: treat as a conflict/invalid replay. Define the exact wire code with the response schema.

## Timeouts and Retries

| Task | Recommended timeout |
|---|---:|
| Natural-language configuration | 15-30 seconds |
| Manual parsing | 60-180 seconds; prefer asynchronous work |
| ASR/TTS | 15-60 seconds, adjusted for audio length |

- Use bounded retries with backoff and jitter for transient Broker/network/provider failures.
- Do not retry schema-invalid requests, authorization failures, payload-policy violations, or known terminal provider errors without a changed request.
- Keep the overall task deadline distinct from individual HTTP-attempt timeouts.
- Record attempt count and final classification for observability and idempotent replay.
- QoS 1 is at-least-once delivery, so duplicate handling remains mandatory.

Exact retry counts, backoff values, jitter, and provider status mappings are implementation decisions and require tests.

## Large-Payload Failures

- Reject audio, PDF, image, complete-manual, or firmware content sent as one ordinary MQTT message.
- Voice transfer uses 4 KB or 8 KB chunks, QoS 1, preferably binary payloads, and metadata including `total_chunks`, `sha256`, `duration_ms`, and `codec`.
- Manuals/PDFs should upload from phone/Web to the cloud; the device receives a parsed profile.
- OTA remains pull-based, chunked at 4 KB or 8 KB, and bounded in-flight.
- Missing, duplicate, out-of-order, or hash-invalid chunks must produce a correlated recoverable or terminal state; never assemble unverified content silently.

## Security Failures

- Production requires MQTTS, per-device credentials/token, and Broker ACLs.
- The AI Bridge account may only subscribe and publish within its assigned role.
- Denylisted devices fail closed.
- Never include complete tokens, product secrets, MiMo API keys, or OTA private keys in errors, exceptions, logs, or MQTT payloads.
- Controlled-LAN plaintext MQTT must not become a production fallback.

## Error Publication

v1 AI response envelope is implemented (see `mqtt-ai-bridge-contracts.md` Scenario: Minimal AI MQTT loop):

- Always carry `req_id` when known; include `device_id` and `type` when known.
- `status` distinguishes `processing`, `success`, and `error`.
- On `error`, set stable `error_code` from: `validation_error`, `conflict`, `timeout`, `provider_error`, `internal_error`.
- `error_message` is optional safe text; never secrets or raw provider dumps.
- `result` is null on non-success.
- Completed duplicates must republish the **exact** stored envelope, including prior timestamps.

## Source References

- `VelaGuard_项目手册.md`: sections 8.3, 11, 12.1, 12.3, and 16.2-16.4.
- `VelaGuard_推进方案.md`: sections 6.2-6.5, 9.2-9.3, and 16.3-16.4.
