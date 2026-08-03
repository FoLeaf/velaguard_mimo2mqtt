# Logging Guidelines

> Correlated, structured, and secret-safe logging for the cloud backend.

---

## Current State

No backend logging library, formatter, sink, tracing system, or retention policy is selected. Choose them during implementation while preserving the rules below.

The device uses a Log4j2-inspired/Minecraft-like rolling model with `latest.log`, optional `debug.log`, `archive/*.log`, and `events.jsonl`. Those are device-side filenames, not a requirement to reproduce the same filesystem layout on the cloud server.

## Levels

- `debug`: local/test diagnostic detail; disabled or tightly filtered in production.
- `info`: lifecycle transitions and successful high-value operations without payload dumps.
- `warn`: recoverable degradation, retries, duplicate/conflict handling, missing optional data, or suspicious input.
- `error`: terminal request failure, security failure, exhausted retry, corrupt chunk/artifact, or unavailable required dependency.

Exact mapping to a logging library remains undecided.

## Structured Fields

Use structured records. Include fields when applicable:

- `logger` or `category`, `level`, and backend timestamp.
- `device_id`.
- `req_id`, `event_id`, `alarm_id`, or session ID.
- Request `type` and safe `payload_hash`/artifact hash.
- Idempotency state.
- Provider and operation, never provider credentials.
- Attempt number, elapsed time, outcome, and safe error classification.
- Source `ts_ms`, `uptime_ms`, and `time_quality`.
- Cloud `received_ts_ms`.

Preserve device timestamps and store `received_ts_ms` separately. Network recovery must not rewrite historical event time.

## What to Log

- Service startup/shutdown, selected non-secret mode, and Broker connection lifecycle.
- Subscription/publication failures, reconnects, and status/LWT issues.
- Request acceptance, validation failure, idempotency hit/conflict, processing, completion, and classified failure.
- Provider latency, timeout, retry, and normalized outcome.
- Manual, voice, and OTA session lifecycle, chunk verification failure, and final hashes without binary dumps.
- Token-version migration and denylist decisions as redacted audit events.
- Backend-owned configuration and deployment/security policy changes.

## Device Log Ingestion Boundary

By default, the cloud receives only structured events and key `error`/`warn` summaries. Do not request or upload the device's complete `latest.log`.

For ingested events:

- Preserve original IDs and time fields.
- Add `received_ts_ms` on receipt.
- Deduplicate by documented event identity where applicable.
- Keep payloads bounded and schema-validated.

## What Not to Log

Never log:

- Complete device tokens or credentials.
- `PRODUCT_AUTH_SECRET` or any version of the product secret.
- MiMo, TTS, ASR, or manual-service API keys.
- OTA private keys.
- Authorization headers, TLS private material, or unredacted connection strings.
- Complete manuals, PDFs, images, audio, firmware, or arbitrary provider response bodies.
- Secrets echoed by exceptions, SDK debug modes, MQTT dumps, or HTTP tracing.

User-uploaded manuals and diagnosis data are protected. Prefer IDs, hashes, sizes, and outcomes over content.

## Output and Filtering

- Sinks may use different minimum levels and category filters.
- Production favors structured logs and security/audit events; test mode may enable more detail.
- Device `VG_BUILD_MODE=test` debug permission does not authorize backend secret or payload logging.
- Define retention, rotation, access control, and deletion before production; the root documents do not choose values.

## Source References

- `VelaGuard_项目手册.md`: sections 8.3, 9.2, 11.2, 12, 16.3, 16.7, and 16.10.
- `VelaGuard_推进方案.md`: sections 6.2, 9.2, 16.5, and 16.10.
