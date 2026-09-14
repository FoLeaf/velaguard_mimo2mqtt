# Logging Guidelines

## Implementation

Use `dashboard.observability.logging.get_logger(__name__)`.
`configure_logging(LOG_LEVEL)` installs a stdlib stream handler with timestamp,
level, logger name and `RedactingFilter`. No external logging framework is needed.

## Levels and Fields

- DEBUG: successful ingestion and HTTP access detail.
- INFO: startup, shutdown and broker connection/subscription lifecycle.
- WARNING: reconnects, recoverable malformed input and dropped deliveries.
- ERROR: terminal startup, transport, storage or unexpected handler failures.

Include `topic`, `device_id`, kind, operation and safe reason where available.
Preserve device timestamps and record cloud receipt time separately; do not
invent a synchronized timestamp from device uptime.

## Redaction

`redact_secrets` handles nested dicts/lists and strings. Protect passwords,
tokens, API keys, authorization values, product secrets and prefixed credential
keys case-insensitively. Bearer tokens and `key=value` text are redacted too.

Do not log full MQTT payloads, credentials, TLS private keys or configuration
dumps. Redaction is defense in depth, not permission to log sensitive input.
Test both nested structures and text patterns when changing redaction.

The raw-message debug buffer is stored device data, not a sanitized log sink.
Device payloads must not carry secrets, and deployment must restrict database
and HTTP access.

Production retention, rotation, access controls and log sinks remain deployment
decisions. Device `latest.log` files are not automatically collected by this service.
