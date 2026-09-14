# Directory Structure

## Layout

```text
dashboard/
  __main__.py            # Lifecycle and dependency assembly
  configuration/        # Environment parsing and validation
  contracts/topics.py   # Topic filters, QoS, retain policy, payload limit
  transport/mqtt.py     # Generic MQTT transport; no implicit subscriptions
  transport/subscriber.py # Explicit read-only collector subscriptions
  application/          # Payload parsers and collector orchestration
  storage/db.py         # SQLite schema, writes and read projections
  observability/        # Logging configuration and redaction
  http/                 # GET API and whitelisted static files
  web/                  # Browser UI served by the collector
  tools/                # Development-only synthetic board
tests/
  unit/
  contract/
  integration/
deploy/dev/             # Local broker and dashboard Compose stack
docs/dashboard-api.md   # Board and browser API contract
scripts/                # Local no-broker demo
```

## Dependency Rules

- Entrypoints assemble dependencies; they do not parse payloads or build SQL.
- `MqttClient` dispatches `(topic, bytes)` off the network thread. It has no
  domain defaults; `build_subscriber` supplies `SUBSCRIBE_FILTERS`.
- `application/ingest.py` owns external payload validation and normalization.
  `Collector` routes parsed records into storage or quarantine.
- `DashboardStore` owns SQL, alarm-state transitions and read projections.
  HTTP handlers do not issue SQL directly.
- The browser consumes HTTP JSON and does not connect to MQTT.
- Logging is shared through `dashboard.observability`, not copied per layer.
- The development publisher is not part of the read-only collector runtime.

## Naming and Placement

Preserve wire names such as `device_id`, `alarm_id`, `ts_ms`, `uptime_ms`,
`time_quality` and `received_ts_ms`. Topic constants belong in
`dashboard/contracts/topics.py`. Avoid generic utility directories and
duplicated parsers or state machines.

Only `dashboard*` packages and `dashboard/web/*` runtime assets are distributed.
Do not scaffold modules for unimplemented firmware or cloud capabilities.
