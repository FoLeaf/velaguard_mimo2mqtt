# Quality Guidelines

## Commands

```bash
pip install -e ".[dev]"
python -m pytest tests/unit tests/contract -q
docker compose -f deploy/dev/docker-compose.yml up -d mosquitto
python -m pytest tests/integration -q
```

Integration skips if no broker is reachable. Use `TEST_MQTT_HOST` and
`TEST_MQTT_PORT` for an isolated development broker. Lint/type-check tooling is
optional until configured; report exactly which checks ran.

## Required Coverage

- Contract: four topic filters, QoS/retain policy, 64 KiB cap and point-table schema.
- Ingestion: identity mismatch, malformed JSON/types, quarantine and unknown fields.
- Storage: status updates, point-table replacement, telemetry history, alarm
  raise/refresh/clear/orphan-clear, database reopening and cleanup.
- Transport: explicit subscriptions, reconnect, publisher with zero subscriptions,
  background message dispatch, failure containment and correct JSON/wire policy.
- Security: TLS defaults, existing certificate pairs, missing/blank paths,
  unpaired cert/key rejection and nested/text secret redaction.
- HTTP: usable ephemeral test port, static assets, API state and rejected writes.
- Integration: actual subscriber connected to a broker, retained snapshots
  published before startup, telemetry, alarm transitions and offline status.
- Packaging: `dashboard` imports from an installed wheel and web assets are included.

## Forbidden Patterns

- Device-facing publishes from the collector or write APIs in the dashboard.
- Implicit business-topic subscriptions in the shared MQTT transport.
- Retained alarm/telemetry messages or QoS 0 alarms.
- Treating QoS 1 as application deduplication or persistent MQTT history.
- Blocking the paho network loop with ingestion/storage work.
- Overwriting device timestamps with cloud time.
- Logging secrets or presenting the development stack as production-ready.
- Restoring obsolete runtime packages through imports, metadata or docs.

## Cross-Layer Review

Trace board JSON through MQTT, parsing, storage, HTTP and the browser.
Use one owner for each parser, topic definition and alarm-state transition.
Do not assert point-table order unless it is a documented contract; the current
store sorts by address and point ID.

After moving shared modules, update every consumer, patch target, package entry,
test and active spec link. Historical journals/task archives are not runtime
contracts. Run `git diff --check` and inspect the installed package before
declaring a removal complete.
