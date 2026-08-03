# Directory Structure

> Framework-neutral organization for the VelaGuard cloud AI Bridge backend.

---

## Current State

The repository has no business code, so no physical backend structure is established. The language, framework, package system, and source root must be selected during implementation.

The boundaries below are required responsibilities, not a commitment to exact folder names. Map them to the chosen ecosystem without collapsing transport, orchestration, provider integration, persistence, and security into one module.

## Confirmed Backend Boundaries

The cloud backend owns:

- MQTT Broker connectivity for the AI Bridge.
- Request subscription, validation, correlation, idempotency, and response publication.
- Calls to MiMo, TTS, ASR, and manual-parsing services.
- Cloud-only secret handling, including the MiMo API key.
- Support for token-version migration and a single-device denylist at the Broker/backend boundary.
- Cloud receipt timestamps and ingestion of allowed device events or error/warn summaries.
- Cloud-side manual upload/parse flow when implemented.
- Cloud-side OTA offer and chunk-serving behavior when implemented.

The backend does not own device-side Modbus, LVGL, local HTTP APIs, local config commits, local safety confirmation, local event files, staging writes, firmware verification, or rollback execution.

## Logical Layout

Use this responsibility map when creating the first backend structure. Exact names and nesting remain implementation decisions.

```text
<backend-source-root>/                 # exact root is not selected yet
  entrypoints/                         # process startup and lifecycle wiring
  transport/
    mqtt/                              # subscriptions, topic parsing, publishing, QoS/retained policy
    http/                              # cloud upload/health/admin endpoints only if required
  application/                         # request orchestration and use cases
  contracts/                           # MQTT schemas, IDs, statuses, provider-neutral models
  providers/
    mimo/                              # MiMo HTTPS adapter
    tts/                               # TTS adapter
    asr/                               # ASR adapter
    manual_parsing/                    # manual parsing adapter
  persistence/                         # idempotency, request state, denylist, metadata
  security/                            # credentials, redaction, authorization/ACL integration
  observability/                       # logging, metrics, tracing, event ingestion
  configuration/                       # validated runtime configuration
  tests/                               # unit, contract, integration, and failure-path tests
```

Create only modules needed by the implemented slice. Do not scaffold empty framework layers merely to match this map.

## Dependency Direction

- Entrypoints assemble dependencies but contain no business rules.
- MQTT and HTTP handlers translate transport input into contract types, invoke application use cases, and translate results back.
- Application code owns orchestration, deadlines, idempotency decisions, and retry policy; it must not depend on provider-specific response shapes.
- Provider adapters isolate MiMo, TTS, ASR, and manual-service APIs. Provider SDK objects must not leak into MQTT contracts.
- Persistence is accessed through narrow interfaces defined around backend behavior, not around a chosen ORM.
- Security and observability are cross-cutting dependencies, not ad hoc calls scattered through handlers.
- A generic `utils` or `helpers` directory must not become a dumping ground. Put behavior in the domain-responsible module; create a shared utility only after searching for genuine reuse.

## Protocol Placement Rules

- Keep topic definitions, payload fields, QoS, and retained rules centralized under contracts/transport rather than duplicating string literals.
- Keep `req_id + payload_hash` idempotency logic in one application/persistence boundary.
- Keep provider timeout and retry mappings near provider adapters, while the overall request deadline remains an application concern.
- Keep large-payload chunk/session handling separate from ordinary JSON request handlers.
- Keep OTA distribution separate from AI request processing; both use MQTT, but they have different security and lifecycle rules.

## Naming Conventions

No language-specific naming convention is confirmed. Until one is selected:

- Use domain terms from the root documents: `device_id`, `req_id`, `event_id`, `alarm_id`, `payload_hash`, `received_ts_ms`, and `time_quality`.
- Do not rename confirmed wire fields to match framework conventions.
- Use names that distinguish transport requests, application commands, provider requests, and published responses.
- Avoid ambiguous modules such as `common`, `misc`, `manager`, or `service` without a domain qualifier.

## Source References

- `VelaGuard_项目手册.md`: sections 2.1, 4.1, 5.4, 8.3-8.4, 16.2, 16.4, and 16.9.
- `VelaGuard_推进方案.md`: sections 6.2, 8.2, 9.2, and 16.3.
