# Backend Development Guidelines

> Project-specific rules for the VelaGuard cloud AI Bridge and adjacent cloud services.

---

## Repository Scope

This is a **backend-only repository**. It is responsible for the cloud AI Bridge and related cloud services used by VelaGuard.

The confirmed cloud role is to connect to the MQTT Broker as an independent client, receive device requests, call MiMo and optional TTS, ASR, and manual-parsing services, and publish results through MQTT. The STM32H750B-DK/openvela firmware, LVGL UI, Modbus collector, local HTTP API, local filesystem, and device safety confirmation flow are outside this repository; their documented behavior is an external contract for this backend.

Frontend specs are intentionally absent because this repository owns backend cloud services only.

There is no business code yet. No backend language, web framework, MQTT client, database, ORM, migration tool, test framework, deployment platform, or code-style tool has been selected. Do not infer FastAPI, SQLAlchemy, PostgreSQL, or equivalent technologies as project conventions.

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

## Undecided Implementation Choices

Decide and document these when implementation starts:

- Runtime language and supported version.
- Application framework, if any.
- MQTT and HTTP client libraries.
- Physical source root and language-specific naming style.
- Database or other persistence engine, ORM/query layer, and migration mechanism.
- Exact request/response schemas and backend error-code vocabulary beyond fields already confirmed in the root documents.
- Logging, tracing, metrics, retention, formatting, linting, testing, packaging, and deployment tools.

An implementation choice is not a project convention until it is reflected in these files or another approved design record.

## Guidelines Index

| Guide | Description | Status |
|---|---|---|
| [Directory Structure](./directory-structure.md) | Framework-neutral service boundaries and placement rules | Filled |
| [MQTT and AI Bridge Contracts](./mqtt-ai-bridge-contracts.md) | Topics, QoS, IDs, idempotency, retries, and payload boundaries | Filled |
| [Security Guidelines](./security-guidelines.md) | Identity, Broker permissions, secrets, AI safety, and environment boundaries | Filled |
| [Database Guidelines](./database-guidelines.md) | Persistence contracts without assuming a database | Filled |
| [Error Handling](./error-handling.md) | Provider failures, retries, publication, and degradation | Filled |
| [Logging Guidelines](./logging-guidelines.md) | Correlation, event ingestion, levels, and redaction | Filled |
| [Quality Guidelines](./quality-guidelines.md) | Review gates and protocol-focused testing | Filled |

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
