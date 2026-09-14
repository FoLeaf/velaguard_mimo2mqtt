# Error Handling

## Ingestion

`application/ingest.py` raises `IngestError(reason)` for invalid input.
`Collector.handle_message` validates topic/encoding/size, invokes the parser,
and stores accepted records or quarantines rejected input.

Stable quarantine categories include `non_json_payload`, `non_utf8_payload`,
`payload_too_large`, `unknown_topic`, `unknown_kind`, `device_id_mismatch`,
`unsupported_schema_version`, and `missing_field:*`/`invalid_field:*`/`null_field:*`.

- Invalid input must not update domain state.
- Record a bounded raw message and its reason for inspection.
- Unexpected ingestion/storage errors are logged as exceptions and classified
  as `internal_error`; the network handler contains uncaught handler failures.
- Quarantine itself needs writable storage; disk failures must be treated as
  operational faults, not silently described as successfully persisted.

## MQTT Lifecycle

- Keep database/ingestion work off the paho network thread.
- Failed connect must not mark the client connected or subscribe.
- Disconnect clears connectivity; successful reconnect restores explicit filters.
- Startup waits at most 15 seconds for the dashboard connection, then exits
  nonzero on timeout.
- The dashboard never publishes an error response or device command.
- Development publishing returns `MQTTMessageInfo` so callers can wait for delivery.

## HTTP Errors

The server exposes only whitelisted static files and read-only GET endpoints:

- Missing history point parameter: HTTP 400.
- Unknown device or route: HTTP 404.
- Unexpected API/storage error: HTTP 500 with `internal_error`.
- Missing static asset: HTTP 500 with `static_file_missing`.
- Unsupported write methods: stdlib HTTP 501; no state mutation.

Never expose raw exceptions, credentials or database internals in HTTP errors.
Cloud failure must not interfere with the device's independent local safety loop.
