# Implement: AI Bridge minimal MQTT loop

## Execution Plan

Phase 1: Setup & protocol proof (1-2 days)
Phase 2: Broker + basic transport (1 day)
Phase 3: Request validation + idempotency (1 day)
Phase 4: Provider interface + stub (1 day)
Phase 5: Response publishing & envelope (0.5 day)
Phase 6: Testing & verification (1 day)

## Ordered Checklist

1. Create project structure
   - `pyproject.toml` or `setup.py` (Python 3.12)
   - Folder layout as in `design.md`
   - `README.md` with dev setup

2. Configuration & validation
   - Pydantic settings model for env vars
   - Validation for MQTT connection, timeouts, provider choice

3. MQTT transport layer
   - Choose MQTT client (paho-mqtt recommended for simplicity; or aiomqtt)
   - Implement reconnect + resubscribe logic
   - Topic parsing helpers (centralized)
   - Publish response with QoS 1, retain=false

4. Core application layer
   - Request validator (Pydantic model + field rules)
   - Idempotency store (in-memory with thread/process safety)
   - Deadline / timeout management
   - Provider interface definition (ABC or protocol)

5. Provider layer
   - Stub provider implementation (deterministic diagnosis result)
   - Config seam (`PROVIDER=stub` default)
   - Error classification mapping

6. Response envelope builder
   - Build v1 JSON envelope (required fields + status + error_code)
   - Structured result shape for success
   - Error code mapping

7. Startup & lifecycle
   - Entry point (`__main__.py`)
   - Logging setup (structlog or standard logging + redaction)
   - Signal handling for graceful shutdown
   - Docker Compose Mosquitto integration

8. Testing
   - Unit/contract tests for envelope, validation, idempotency, topic parse
   - Integration tests against local Mosquitto
   - Synthetic publisher script
   - Test double for provider

9. Documentation
   - Update `README.md` with dev commands
   - Add `deploy/dev/docker-compose.yml`
   - Document disposable idempotency behavior

10. Review gates
    - Protocol envelope review against spec
    - Idempotency test with duplicate requests
    - Local Mosquitto end-to-end test

## Validation Commands

```bash
# Run tests (pytest or unittest)
pytest tests/

# Local verification (Mosquitto + synthetic publisher)
docker compose -f deploy/dev/docker-compose.yml up -d
python -m ai_bridge.cli.synthetic_publisher --help
python -m ai_bridge.cli.synthetic_publisher  # interactive or scripted test
```

## Rollback Points

- Any change that breaks v1 envelope (req_id, status, error_code) must be reverted
- In-memory store must be clearly marked as disposable in README
- If MiMo seam added too early, scope creeps into later tasks

## Quality Gates Before `task.py start`

- All acceptance criteria in `prd.md` pass (manual + automated tests)
- README is clear about disposable idempotency
- Docker Compose Mosquitto starts and accepts bridge client
- No secrets in source or default config
- Contract tests cover topic parse, envelope, idempotency state machine, validation

## Sub-agent notes (if used)

- Use `trellis-implement` skill for code changes
- Curate `implement.jsonl` with spec/research entries before final review

This plan keeps the slice minimal and focused on proving the MQTT loop while respecting all frozen protocol contracts.
