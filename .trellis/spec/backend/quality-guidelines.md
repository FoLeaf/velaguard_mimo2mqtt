# Quality Guidelines

> Review and test standards for the VelaGuard cloud backend.

---

## Current State

First-slice toolchain:

- Language: Python 3.12+
- Test runner: `pytest`
- Package: `pip install -e ".[dev]"` from repo root (`pyproject.toml`)
- Default verification: `pytest tests/unit tests/contract -q`
- Integration: `pytest tests/integration -q` (requires local Mosquitto; skips if broker down)
- Local Broker: `docker compose -f deploy/dev/docker-compose.yml up -d`

Formatter/linter/typechecker/CI remain optional until configured. Quality is still defined primarily by protocol correctness, safe failure, security boundaries, and provider isolation.

## Required Patterns

- Separate MQTT transport, application orchestration, provider adapters, persistence, security, and observability.
- Centralize topics, QoS, retained policy, and confirmed wire fields.
- Validate all external input and provider output against explicit schemas.
- Make QoS 1 handlers idempotent; AI requests use `req_id + payload_hash`.
- Preserve device IDs and timestamps; add `received_ts_ms` instead of rewriting source time.
- Bound deadlines, retries, payload sizes, chunk sizes, and in-flight work.
- Keep MiMo API keys and all cloud secrets server-side and redacted.
- Treat AI output as advice requiring device-side validation and local confirmation.
- Design cloud failures so the device can continue its local safety loop and fallback behavior.
- Document every selected framework/library as a new implementation choice.

## Forbidden Patterns

- Direct device-to-provider calls or direct bridge-to-device sockets that bypass the Broker.
- Environment-prefixed topic roots replacing `vg/{device_id}/...`.
- Retained requests, responses, alarms, telemetry, or trend messages; only current status may be retained.
- QoS 0 for alarm, AI request/response, candidate config, TTS, voice, OTA, or confirmation events.
- Trusting QoS 1 to prevent duplicates.
- Sending audio, PDF, images, complete manuals, or firmware as one ordinary MQTT message.
- Exposing complete tokens, product secrets, MiMo API keys, or OTA private keys.
- Representing AI-generated configuration as active without device validation and confirmation.
- Treating `VG_BUILD_MODE=test|production` as a confirmed backend variable. It is a device build boundary; the backend's configuration mechanism remains undecided.
- Adding FastAPI, SQLAlchemy, PostgreSQL, or another unconfirmed stack as a documented requirement beyond the selected Python MQTT worker.
- Blocking the paho network loop with provider work (duplicates and other devices must still be serviced).
- Claiming in-memory idempotency is restart-safe.

## Minimum Test Coverage

### Contract Tests

- Topic parsing/generation under `vg/{device_id}/...`.
- QoS and retained policy for each message class.
- Required AI fields and response `req_id` correlation.
- Schema rejection for malformed or oversized payloads.
- Preservation of `ts_ms`, `uptime_ms`, and `time_quality`, plus separate `received_ts_ms`.

### Idempotency and Retry Tests

- First delivery claims processing exactly once.
- Completed duplicate republishes the same response.
- Processing duplicate does not start duplicate provider work.
- Failed duplicate follows retryable/non-retryable classification.
- Same `req_id` with different `payload_hash` is rejected.
- Restart does not lose production-required deduplication state.
- Provider timeout, transient failure, exhausted retry, and late response paths.

### Security Tests

- Production Broker policy requires MQTTS, per-device credential/token, and ACL isolation.
- AI Bridge account cannot exceed its subscribe/publish scope.
- Topic/payload device mismatch and denylisted devices fail closed.
- Logs and errors redact tokens, product secrets, provider keys, OTA private keys, and sensitive headers.
- Controlled-LAN plaintext MQTT is impossible under production policy.

### Large-Payload Tests

- Ordinary MQTT rejects complete audio/manual/image/firmware payloads.
- Voice chunks cover 4 KB/8 KB sizing, metadata, duplicates, missing sequence, and SHA-256 mismatch.
- Manual parsing covers asynchronous timeout windows and returns profiles rather than documents.
- OTA serving is pull-based, bounded in-flight, interruption-safe, and separate from ordinary AI processing.

### Degradation and Integration Tests

- Broker disconnect/reconnect and resubscription.
- MiMo/TTS/ASR/manual-service timeout and unavailable paths.
- Invalid provider JSON is not published as success.
- Backend failure returns a bounded, correlated result permitting device fallback.
- Delayed device events preserve original timestamps and deduplicate correctly.

Use fakes or contract fixtures for unit tests. Run integration tests against a controlled Broker and provider test doubles before real external services. Exact tooling remains undecided.

## Build and Deployment Boundary

- Test policy may interoperate with development device IDs, controlled-LAN plaintext MQTT, detailed debug logs, and development-signed OTA.
- Production policy requires MQTTS, token/credential validation, Broker ACLs, secret redaction, and production OTA signatures.
- The backend must never silently fall back from production security to test policy.
- Build/package/deployment commands cannot be prescribed until the backend stack is selected.

## Review Checklist

- Does the change match both root documents and confirmed section 16 decisions?
- Does it alter a topic, field, QoS, retained rule, timeout, chunk size, ID, or timestamp contract?
- Are retries bounded and idempotent under at-least-once delivery?
- Are provider details isolated from device-facing contracts?
- Are secrets and protected data absent from logs and payloads?
- Does failure preserve device autonomy and local safety behavior?
- Are test and production policies explicitly separated?
- Are new implementation choices documented instead of implied?

## Source References

- `VelaGuard_项目手册.md`: sections 2.1-2.2, 8.3, 11-12, and 16.1-16.10.
- `VelaGuard_推进方案.md`: sections 1, 6.3-6.5, 9.2-9.3, and 16.1-16.10.
