# Database and Persistence Guidelines

> Behavioral persistence contracts for the VelaGuard cloud backend.

---

## Current State

No database, ORM, query library, schema language, or migration tool is confirmed. Do not treat any storage technology as a project requirement.

Persistence must begin from the protocol behavior below. An in-memory implementation may be used only for an explicitly disposable local prototype; it must not be presented as restart-safe production behavior.

## AI Request Idempotency

The AI Bridge uses `req_id + payload_hash` as its idempotency key. Persist or otherwise durably coordinate enough state to distinguish:

- Completed: publish the same response again.
- Processing: return or publish `status=processing`.
- Failed: retain the failure classification needed to decide whether retry is allowed.

Preserve the confirmed request fields: `req_id`, `device_id`, `created_ts_ms`, `type`, and `payload_hash`. Store response data or a reproducible response reference when exact replay is required.

Idempotency claims must be atomic. Two deliveries of the same key must not start duplicate provider work. The exact unique constraint, transaction, compare-and-set, or locking mechanism depends on the selected persistence engine and must be documented with that choice.

## IDs and Time

- Preserve device-generated `event_id` and `alarm_id`; do not replace them with cloud IDs on ingestion.
- Preserve `ts_ms`, `uptime_ms`, and `time_quality` exactly as received.
- Store cloud receipt time separately as `received_ts_ms`.
- Never rewrite historical device time after network recovery.
- Keep enough correlation data to trace retries and duplicates across process restarts.

## Security State

The cloud must support versioned device-token migration and a denylist for a leaked `device_id`. The selected persistence or control-plane design must define consistency, auditability, and update propagation before production use.

Never store plaintext product authentication secrets, MiMo API keys, OTA private keys, or complete device tokens in ordinary records or logs. Secret-storage technology remains undecided.

## Optional Service Data

Persist these only when the corresponding service is implemented:

- Manual upload metadata, `manual_id`, parse state, and `manual_profile`/`sensor_profile` references.
- TTS/ASR session metadata and chunk checksums; large binary data needs a deliberately selected artifact/blob mechanism.
- OTA offer metadata, image checksum/signature metadata, chunk-serving progress, and result/confirmation events.
- Allowed structured device events and key error/warn summaries. Do not ingest or persist complete `latest.log` by default.

## Query and Update Rules

- Look up AI work by the complete idempotency key, not `req_id` alone.
- Scope device-owned data by `device_id` at every access boundary.
- Separate current state from retry-attempt history so operators can reconstruct transitions.
- Bound list and history queries; never load unbounded event, manual, audio, log, or OTA collections.
- Store hashes and metadata needed to verify chunks and artifacts rather than trusting transport completion alone.
- Record completion state before or atomically with making a replayable response visible.

## Migrations and Compatibility

Migration conventions cannot be fixed until persistence technology is selected. The first durable implementation must document:

1. Schema ownership and versioning.
2. Forward and rollback migration commands.
3. Code/schema deployment ordering.
4. Backfill behavior for idempotency and security records.
5. Backup, restore, retention, and deletion policy.

Protocol compatibility is independent of database migrations: confirmed MQTT fields and topic rules remain stable unless the root contract is intentionally revised.

## Forbidden Assumptions

- Do not introduce an ORM merely because this file is named database guidelines.
- Do not infer SQL, PostgreSQL, Redis, document storage, or any cloud-managed product.
- Do not use provider request IDs as substitutes for VelaGuard `req_id`.
- Do not mark a request completed before its replayable response is safely recorded.
- Do not silently rerun a failed non-retryable request.
- Do not put PDFs, images, complete manuals, audio, or firmware into ordinary MQTT JSON records.

## Source References

- `VelaGuard_项目手册.md`: sections 11.2, 16.1, 16.3-16.4, 16.7, and 16.9.
- `VelaGuard_推进方案.md`: sections 6.2, 8.2, 16.2, 16.5, and 16.9-16.10.
