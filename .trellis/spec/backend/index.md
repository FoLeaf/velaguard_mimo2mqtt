# Backend Development Guidelines

## Repository Scope

This repository implements the VelaGuard **read-only MQTT cloud dashboard**.
The single runtime package is `dashboard`, distributed as `velaguard-cloud`.
It collects device `status`, `telemetry`, `alarm` and `point_table` messages,
persists them in SQLite, and serves a Chinese web dashboard and GET-only API.

```text
Device -> MQTT Broker -> Collector -> SQLite -> HTTP API -> Browser
```

The collector and device are separate broker clients. The collector never
publishes device-facing messages (boundary V5). Firmware, Modbus acquisition,
LVGL, device configuration writes, local confirmation and OTA are external
device contracts, not implemented cloud features.

The web frontend is `dashboard/web/`: vanilla JS, no build step, no browser
broker credentials. Its contracts are covered by these backend guidelines.

## Selected Implementation Choices

| Area | Selection | Owner |
|---|---|---|
| Runtime | Python 3.12+, setuptools | `pyproject.toml` |
| Entrypoints | `python -m dashboard`, `vg-dashboard` | `dashboard/__main__.py` |
| MQTT | paho-mqtt 2.1+, clean session, resubscribe on reconnect | `dashboard/transport/mqtt.py` |
| Subscriptions | Four explicit device-topic filters | `dashboard/transport/subscriber.py` |
| Configuration | pydantic-settings, environment/local `.env` | `dashboard/configuration/settings.py` |
| Storage | stdlib sqlite3, shared connection protected by RLock | `dashboard/storage/db.py` |
| HTTP | stdlib ThreadingHTTPServer, read-only API/static files | `dashboard/http/server.py` |
| Logging | stdlib logging with secret redaction | `dashboard/observability/logging.py` |
| Tests | pytest; broker-free unit/contract tests | `tests/` |
| Dev broker | Mosquitto via Docker Compose | `deploy/dev/` |

Production authentication, broker administration, migration tooling, metrics
and CI are not implemented conventions. Do not invent frameworks or introduce
an ORM as an implicit project requirement.

## Guidelines Index

| Guide | Description |
|---|---|
| [Directory Structure](./directory-structure.md) | Package layout and dependency boundaries |
| [MQTT Dashboard Contracts](./mqtt-dashboard-contracts.md) | Topics, payloads, session behavior and validation |
| [Security Guidelines](./security-guidelines.md) | Credentials, TLS, ACLs and read-only access |
| [Database Guidelines](./database-guidelines.md) | SQLite state, alarm transitions and bounded history |
| [Error Handling](./error-handling.md) | Quarantine, transport errors and HTTP failures |
| [Logging Guidelines](./logging-guidelines.md) | Levels, correlation and secret redaction |
| [Quality Guidelines](./quality-guidelines.md) | Verification commands and regression coverage |

## Pre-Development Checklist

1. Read the relevant guides and `mqtt-dashboard-contracts.md` for MQTT changes.
2. Read `security-guidelines.md` for configuration, logging and deployment work.
3. Search existing contracts, consumers and tests before changing fields or defaults.
4. Preserve topic root `vg/{device_id}/...`, QoS/retain policy and device timestamps.
5. Keep `docs/dashboard-api.md` and both root project documents consistent with
   the current executable contracts. The root documents also describe external
   firmware requirements; do not present those as dashboard features.
6. Keep the dashboard read-only and device local safety independent of the cloud.

## Quality Check

Follow `quality-guidelines.md`. At minimum run unit/contract tests, check package
imports and data assets, and verify the broker integration when MQTT changes.

All documentation in this directory must be written in English. Archived tasks
and developer journals record historical decisions, not current requirements.
