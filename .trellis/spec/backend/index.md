# Backend Development Guidelines

> Project-specific rules for the VelaGuard cloud AI Bridge and adjacent cloud services.

---

## Repository Scope

This is a **backend-only repository**. It is responsible for the cloud AI Bridge and related cloud services used by VelaGuard.

The confirmed cloud role is to connect to the MQTT Broker as an independent client, receive device requests, call MiMo and optional TTS, ASR, and manual-parsing services, and publish results through MQTT. The STM32H750B-DK/openvela firmware, LVGL UI, Modbus collector, local HTTP API, local filesystem, and device safety confirmation flow are outside this repository; their documented behavior is an external contract for this backend.

Frontend specs are intentionally absent because this repository owns backend cloud services only.

The first business slice exists under `ai_bridge/`. Selected implementation choices for that slice are listed below. Unlisted tools remain undecided; do not invent FastAPI, SQLAlchemy, PostgreSQL, or other stacks as project conventions.

## Sources of Truth

These guidelines derive only from:

- `VelaGuard_项目手册.md`, especially sections 2.1-2.2, 8.3-8.4, 11-12, and 16.1-16.10.
- `VelaGuard_推进方案.md`, especially sections 6, 8-9, and 16.1-16.10.

When these guidelines and either root document disagree, stop and resolve the discrepancy instead of silently choosing an interpretation. Section 16 of `VelaGuard_项目手册.md` records confirmed architecture decisions and takes priority over earlier recommendations in that document.

## Confirmed Architecture Constraints

- Communication is `VelaGuard -> MQTT Broker -> AI Bridge -> HTTPS cloud providers`; the device and AI Bridge do not connect directly.
- The AI Bridge subscribes to request topics and publishes response topics using its own Broker account and least-privilege ACL.
- The topic root is `vg/{device_id}/...` without an environment prefix.
- Production uses MQTTS, per-device credentials or tokens, Broker ACLs, and secret redaction. Controlled-LAN testing may use plaintext MQTT.
- The bridge handles MiMo, TTS, ASR, and manual parsing. MiMo API keys remain on the cloud server.
- AI requests carry `req_id`, `device_id`, `created_ts_ms`, `type`, and `payload_hash`; bridge idempotency is keyed by `req_id + payload_hash`.
- QoS, retained-message, reconnect, timeout, retry, and large-payload rules are protocol contracts, not library defaults.
- MQTT carries control JSON, short text, and short results. Audio, PDF, images, and complete manuals must not be placed in one MQTT message.
- AI output is advisory. The device performs schema validation, risk checks, test reads where applicable, and local user confirmation before applying write-like changes.
- Cloud processing failures must not compromise the gateway's independent local collection, alarm, UI, logging, or local-audio loop.

## Selected Implementation Choices (minimal MQTT loop)

| Choice | Selection | Notes |
|---|---|---|
| Runtime | Python **3.12+** | Package `ai-bridge` / import root `ai_bridge` |
| Process shape | MQTT worker (`python -m ai_bridge`) | No web framework in the first slice |
| MQTT client | `paho-mqtt` ≥ 2.1 | `clean_session`/`clean_start` true; resubscribe on connect |
| Config | `pydantic-settings` env vars | See contracts below / `.env.example` |
| Persistence | In-memory idempotency only | Explicitly disposable; not restart-safe production |
| Default provider | `StubProvider` via `PROVIDER=stub` | `PROVIDER=mimo` reserved, not implemented |
| Tests | `pytest` | `pytest tests/unit tests/contract`; integration needs Mosquitto |
| Local Broker | Docker Compose Mosquitto | `deploy/dev/docker-compose.yml`; plaintext localhost only |

## Still Undecided

- Production durable store, ORM/migrations
- Real MiMo HTTPS client details and auth storage
- Tracing/metrics backends, lint/typecheck CI, production packaging/deploy
- Production MQTTS, token verification, and Broker ACL administration product features

An implementation choice is not a project convention until it is reflected in these files or another approved design record.

## Guidelines Index

| Guide | Description | Status |
|---|---|---|
| [Directory Structure](./directory-structure.md) | `ai_bridge/` layout and responsibility boundaries | Filled |
| [MQTT and AI Bridge Contracts](./mqtt-ai-bridge-contracts.md) | Topics, QoS, v1 envelope, idempotency, payload boundaries | Filled |
| [Security Guidelines](./security-guidelines.md) | Identity, Broker permissions, secrets, AI safety, and environment boundaries | Filled |
| [Database Guidelines](./database-guidelines.md) | Persistence contracts; disposable in-memory first store | Filled |
| [Error Handling](./error-handling.md) | Provider failures, retries, v1 error publication | Filled |
| [Logging Guidelines](./logging-guidelines.md) | Correlation, event ingestion, levels, and redaction | Filled |
| [Quality Guidelines](./quality-guidelines.md) | pytest gates and protocol-focused testing | Filled |

## Pre-Development Checklist

Before implementing backend code:

1. Read both root source documents and the guideline relevant to the change.
2. Read `mqtt-ai-bridge-contracts.md` for every MQTT or provider-facing change.
3. Read `security-guidelines.md` for every identity, credential, upload, OTA, logging, or deployment change.
4. Search all contracts and tests before changing a topic, field, status, timeout, or security rule.
5. State which implementation choices are still undecided; do not hide them behind framework defaults.
6. Keep provider credentials and cloud-only capabilities outside device-facing payloads.
7. Plan failure behavior so the device can degrade safely and continue its local loop.

---

**Language**: All documentation in this directory must be written in **English**.
