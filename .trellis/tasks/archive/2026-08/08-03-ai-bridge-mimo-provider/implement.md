# Implement: Real MiMo provider integration

## Execution Plan

Phase 1: Config + scaffolding (0.5 day)
Phase 2: MiMoProvider HTTP adapter (1 day)
Phase 3: Schema validation + error mapping (0.5 day)
Phase 4: Mock server + tests (1 day)
Phase 5: Docs + regression + live verify (0.5 day)

## Ordered Checklist

1. Add config
   - `MIMO_BASE_URL` (default `https://token-plan-cn.xiaomimimo.com/v1`)
   - `MIMO_MODEL`, `MIMO_API_KEY` (secret), `MIMO_HTTP_TIMEOUT_MS`, `MIMO_MAX_RETRIES`, `MIMO_RETRY_BACKOFF_MS`
   - Validate `MIMO_API_KEY` presence only when `PROVIDER=mimo`

2. `ai_bridge/providers/mimo.py`
   - `MiMoProvider.handle(request, *, deadline_s) -> ProviderResult`
   - Build messages: fixed system prompt (diagnosis JSON schema) + safe bounded user content
   - POST `{base}/chat/completions` with Bearer auth, `response_format=json_object`
   - Per-attempt timeout from remaining budget
   - Bounded retry on 429/5xx/network; no retry on 401/403/400/validation
   - Parse `choices[0].message.content` → JSON → schema validate

3. `ai_bridge/providers/schema.py` (small)
   - `validate_diagnosis_result(data) -> dict | None` or raise typed error
   - Required `diagnosis_summary` non-empty str; optional `reasons`/`recommendations` list[str]; `confidence` float 0..1; pass through unknown keys

4. `ai_bridge/providers/base.py`
   - Wire `build_provider("mimo")`; raise clear ValueError if key missing

5. HTTP client
   - Add `requests` (or `httpx`) to `pyproject.toml` + `requirements.txt`
   - Keep timeout per attempt; never send key in query/body

6. Observability
   - Ensure `mimo_api_key` redacted; log attempt/status/elapsed/outcome only

7. Tests
   - `tests/helpers/mimo_stub_server.py` (OpenAI-compatible stub, configurable responses)
   - Contract/unit: request building, schema matrix, retry matrix, timeout, redaction, no-key startup error
   - Regression: existing `pytest tests/unit tests/contract` stays green; stub default e2e

8. Docs
   - `.env.example`: add MiMo vars (key blank)
   - `README.md`: MiMo usage, live-verify section, secret note

9. Secret handling (security gate)
   - Plaintext `MIMO_API_KEY` only on the deploy server's `/opt/velaguard-ai-bridge/.env` (not in repo, not in git, not in tests, not in README)
   - Verify `git check-ignore .env` stays effective; never `git add` `.env`
   - Live verify step reads the key from server env, never from repo or chat-pasted constants

9. Live verify (optional, server or local with real key)
   - `MIMO_API_KEY=... PROVIDER=mimo python -m ai_bridge` → publish diagnosis request → expect `status=success`, `source=mimo`
   - Do not print the key; use env injection

## Validation Commands

```bash
pytest tests/unit tests/contract -q
# expected: existing 45 + new tests green, no live MiMo needed

# mock-server-backed integration (if added)
pytest tests/integration -q  # needs Mosquitto

# live MiMo (manual, real key):
# MIMO_API_KEY=<key> PROVIDER=mimo REQUEST_TIMEOUT_MS=60000 python -m ai_bridge
# then publish a diagnosis request from MQTTX / synthetic publisher
```

## Rollback Points

- `PROVIDER=stub` stays default; any MiMo regression → revert to stub
- v1 envelope untouched → device contract safe
- Keep the new provider additive (new module + config), no changes to `transport/` or `application/` orchestration

## Quality Gates Before `task.py start`

- All AC1–AC10 in `prd.md` satisfied by tests/docs where automatable
- Redaction test covers `MIMO_API_KEY`
- No secrets in repo/source/tests
- README documents live verify as explicit manual step
- `pytest tests/unit tests/contract` green

## Sub-agent notes

- Curate `implement.jsonl` / `check.jsonl` before final review
- Use `trellis-implement` for code; `trellis-check` for review
