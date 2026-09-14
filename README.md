# VelaGuard Cloud

A read-only MQTT cloud dashboard for VelaGuard devices. This repository owns
the **cloud backend only**, not device firmware.

```text
VelaGuard -> MQTT Broker -> Dashboard collector -> SQLite -> Web dashboard
```

The Python collector subscribes to board-published topics, persists device
state, and serves a Chinese web UI. Browsers use HTTP and never connect directly
to the broker.

## Features

- Multi-device fleet view with online/offline status, firmware and network details.
- Point-table auto-sync from device JSON, including names, units and register maps.
- Live values and telemetry trend history.
- Durable alarm history, collected even while no browser is open.
- Raw-message debugging with quarantine reasons for invalid input.
- MQTT reconnect/resubscribe, optional TLS/mTLS and secret-redacted logging.

The dashboard is **read-only end to end**: it never publishes to device-facing
topics, never acknowledges or clears alarms, and exposes GET-only HTTP APIs.

## Quick Start

Requirements: Python 3.12+ and an MQTT broker. Docker is optional for the
development Mosquitto broker.

```bash
pip install -e ".[dev]"
docker compose -f deploy/dev/docker-compose.yml up -d mosquitto
vg-dashboard
# Alternatively: python -m dashboard
```

In another terminal, publish sample device data:

```bash
python -m dashboard.tools.synthetic_board --device-id vg-demo01
```

Open [http://localhost:8080](http://localhost:8080).

For a Docker-only development stack, run
`docker compose -f deploy/dev/docker-compose.yml up -d` instead of starting
`vg-dashboard` on the host. The Compose dashboard uses temporary storage under
`/data`; mount persistent storage before using it for durable deployments.

### No-Broker Demo

```bash
python scripts/demo_dashboard_seed.py
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). This demo seeds a local
`dashboard-demo.db` with sample devices, telemetry and alarms and resets that
demo database on each run.

## MQTT Contract

| Topic | QoS | Retained | Purpose |
|---|---:|---|---|
| `vg/{device_id}/status` | 0 | Yes | Online status, firmware, network and LWT |
| `vg/{device_id}/telemetry` | 0 | No | `[{id, value, ok, age_ms}]` samples |
| `vg/{device_id}/alarm` | 1 | No | Raised/cleared alarm events |
| `vg/{device_id}/point_table` | 1 | Yes | Device point-table snapshot |

Messages are UTF-8 JSON with a 64 KiB limit. Invalid messages are quarantined
without modifying domain state. Device timestamps are preserved; cloud receipt
time is recorded separately.

The complete board-facing payload rules and read-only HTTP API are documented
in [docs/dashboard-api.md](docs/dashboard-api.md).

## Configuration

Settings load from environment variables or a local `.env` file. See
[.env.example](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `MQTT_HOST` | `localhost` | Broker host |
| `MQTT_PORT` | `1883` | Broker port |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | empty | Broker credentials |
| `MQTT_CLIENT_ID` | `vg-dashboard-dev` | Unique collector client ID |
| `MQTT_TLS` | `false` | Enable certificate-verified MQTTS |
| `MQTT_CA_PATH` | empty | CA bundle; empty uses the system trust store |
| `MQTT_CLIENT_CERT_PATH` / `MQTT_CLIENT_KEY_PATH` | empty | Optional mTLS pair |
| `HTTP_HOST` | `0.0.0.0` | HTTP bind address |
| `HTTP_PORT` | `8080` | HTTP port |
| `DB_PATH` | `dashboard.db` | SQLite database path |
| `HISTORY_RETENTION_HOURS` | `24` | Telemetry history cleanup window |
| `MESSAGE_BUFFER_LIMIT` | `500` | Raw-message ring buffer size |
| `ALARM_EVENT_LIMIT` | `5000` | Alarm-event cleanup limit |
| `CLEANUP_INTERVAL_S` | `600` | Retention cleanup timer delay |
| `LOG_LEVEL` | `INFO` | Application log level |

With TLS enabled, configured certificate files must exist and the client
certificate and key must be supplied together. There is no certificate
verification bypass. Certificate settings are ignored in plaintext mode.

The synthetic board is a development publisher. It uses `--host`/`--port`
(or `MQTT_HOST`/`MQTT_PORT`) against a controlled development broker. Run
`python -m dashboard.tools.synthetic_board --help` for finite-cycle, alarm and
offline-status options.

## Tests

Unit and contract tests do not require a broker:

```bash
python -m pytest tests/unit tests/contract -q
```

Integration tests verify retained snapshots, live telemetry, alarm transitions,
offline status and HTTP responses against a local broker:

```bash
docker compose -f deploy/dev/docker-compose.yml up -d mosquitto
python -m pytest tests/integration -q
```

They skip when the broker is unavailable. `TEST_MQTT_HOST` and `TEST_MQTT_PORT`
can select an isolated test broker. Stop the development stack with
`docker compose -f deploy/dev/docker-compose.yml down`.

## Package Layout

```text
dashboard/
  __main__.py        # Process lifecycle
  configuration/     # Validated environment settings
  contracts/         # MQTT topics, QoS and retained policy
  transport/         # MQTT client and read-only subscriber
  application/       # Message validation, ingestion and quarantine
  storage/           # SQLite state, history and raw messages
  observability/     # Logging and secret redaction
  http/              # Read-only API and static file server
  web/               # Chinese vanilla-JS dashboard, no build step
  tools/             # Synthetic board publisher
deploy/dev/          # Development Mosquitto and dashboard Compose stack
docs/                # Board-facing and HTTP API documentation
scripts/             # No-broker demo
tests/               # Unit, contract and broker integration tests
```

## Deployment Boundaries

- Plaintext anonymous MQTT is for controlled development only. Production needs
  MQTTS, device credentials and broker ACLs with subscribe-only dashboard access.
- The HTTP server has no built-in authentication. Put access control and HTTPS
  in front of it before exposing device data outside a trusted network.
- A clean MQTT session cannot recover alarms published while the collector is
  offline. Device-side pending queues are responsible for critical-event replay.
- Device firmware, local configuration writes, alarm acknowledgement and OTA
  distribution are outside this dashboard's implementation.
