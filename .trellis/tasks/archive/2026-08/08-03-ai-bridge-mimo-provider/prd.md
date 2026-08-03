# Real MiMo provider integration

## Goal

Replace the stub provider in the AI Bridge with a real MiMo HTTPS adapter (OpenAI-compatible), keeping the v1 MQTT contract unchanged. The bridge must call MiMo, schema-validate its structured output, and publish success/failure responses with the frozen v1 envelope and error codes.

## Background

Previous task `08-03-ai-bridge-mqtt-minimal` (archived) delivered the minimal MQTT loop with a pluggable `Provider` seam and default `StubProvider`. This task adds the real MiMo path behind that seam.

Current state:

- `ai_bridge/providers/base.py` defines `Provider` protocol: `handle(request, *, deadline_s) -> ProviderResult`
- `ai_bridge/providers/stub.py` is the default `StubProvider`
- `build_provider("mimo")` raises `NotImplementedError`
- Config: `PROVIDER=stub|mimo`, `REQUEST_TIMEOUT_MS`, `MQTT_*` (pydantic-settings)
- v1 envelope/error codes frozen: `validation_error`, `conflict`, `timeout`, `provider_error`, `internal_error`
- Tests: 45 unit/contract + 1 integration passing

## Confirmed Facts (root docs + specs)

- Path: `VelaGuard -> MQTT Broker -> AI Bridge -> HTTPS MiMo`
- MiMo API key stays on the cloud server only; never in MQTT payloads, logs, or errors
- MiMo used for: abnormal diagnosis, natural-language config, manual register-table parsing, inspection reports, TTS
- MiMo output must be fixed JSON and schema-validated before publishing as success
- Malformed / missing-required-field / non-JSON provider output must not be published as success
- AI output is advisory; never authorizes device writes
- Bounded retries for transient failures; idempotency across retries retained
- Provider-attempt timeout stays inside overall request deadline
- Skill files (`industrial_fault_diagnosis.md`, `sensor_config_generator.md`) are device-side concepts; cloud prompt strategy is flexible

## Confirmed Implementation Decisions

- **Protocol**: OpenAI-compatible `{base_url}/chat/completions`, `Authorization: Bearer <key>`, messages array, response `choices[0].message.content`
  - Rationale: lighter than Anthropic (single auth header, flat response), widest ecosystem
- **Base URL**: `https://token-plan-cn.xiaomimimo.com/v1` (env `MIMO_BASE_URL`, default above)
- **Model**: env `MIMO_MODEL` (configurable; default chosen at implementation)
- **Credentials**: `MIMO_API_KEY` env var only. Never in repo, chat, MQTT payloads, or logs. Existing redaction covers `api_key`/`bearer` patterns; keep any new key name in the redaction set.
- **Secret isolation (mandatory)**: the plaintext MiMo API key must never be committed to this repository or any remote. It is injected only at deploy time on the server via a local `.env` (already gitignored, `.env.example` stays blank). CI, tests, fixtures, README, and chat artifacts must contain no plaintext key. Any accidental key commit requires rotation.
- **Automated tests**: mock/contract-based against a local OpenAI-compatible stub HTTP server; live MiMo call is an optional manual verification step with a real key
- **Result schema (v1)**: minimal-extensible diagnosis object, see Wire Contract below

## Wire Contract: MiMo diagnosis result (v1)

`result` object published on `status=success` for `type=diagnosis`:

```json
{
  "diagnosis_summary": "string (required, non-empty)",
  "reasons": ["string"],
  "recommendations": ["string"],
  "confidence": 0.0
}
```

Rules:

- `diagnosis_summary`: required, non-empty string → missing/invalid ⇒ `provider_error`, not success
- `reasons` / `recommendations`: optional arrays of strings; wrong types rejected
- `confidence`: optional number in `[0,1]`; out-of-range rejected
- Unknown extra keys: allowed (forward-compatible), not validated away
- `source` field: bridge adds `"source": "mimo"` when the adapter produced the result

## Requirements

- R1. `PROVIDER=mimo` builds a real `MiMoProvider` implementing the existing `Provider` protocol (no MQTT changes).
- R2. Provider calls `{MIMO_BASE_URL}/chat/completions` with `Authorization: Bearer <MIMO_API_KEY>` and a messages payload constrained to produce JSON.
- R3. Provider sends a bounded system prompt for `type=diagnosis` requesting the fixed JSON schema; prompt is configurable and never includes secrets.
- R4. Provider enforces its own HTTP-attempt timeout inside the overall request deadline (`REQUEST_TIMEOUT_MS`); returns `ProviderFailure(code="timeout")` on deadline breach.
- R5. Provider validates MiMo raw output: valid JSON + v1 diagnosis schema. Invalid ⇒ `ProviderFailure(code="provider_error")`, never success.
- R6. Provider normalizes a valid schema into `result` and adds `source=mimo`; returns `ProviderSuccess`.
- R7. Credentials never leak: no key in MQTT payloads, logs, error bodies, or test fixtures.
- R8. Default automated tests run without a live MiMo key (mock server + contract fixtures); live call is an explicit optional verify step.
- R9. `PROVIDER=stub` remains the default and unchanged behavior for local verification.
- R10. HTTP transport and response parsing are isolated in the provider module; no provider SDK objects leak into MQTT contracts.

## Acceptance Criteria

- [ ] AC1. `PROVIDER=mimo` + valid key + mock-compatible MiMo server yields `status=success` with a schema-valid `result` (contains `diagnosis_summary`, `source=mimo`) and same `req_id`.
- [ ] AC2. MiMo returns invalid JSON or missing `diagnosis_summary` ⇒ `status=error`, `error_code=provider_error`, no success published.
- [ ] AC3. MiMo returns malformed array/confidence types ⇒ `provider_error`.
- [ ] AC4. MiMo is slow past the deadline ⇒ `status=error`, `error_code=timeout`, correlatable `req_id`.
- [ ] AC5. MiMo returns HTTP 401/429/5xx ⇒ classified as provider error (or retryable transient per design), never internal_error, never success.
- [ ] AC6. Secrets absent: full key never in logs/payloads/tests; redaction test covers `MIMO_API_KEY` style name.
- [ ] AC7. Mock/contract tests pass without a live key (`pytest tests/unit tests/contract`); existing 45 + new tests green.
- [ ] AC8. `PROVIDER=stub` default still works end-to-end (regression).
- [ ] AC9. Live MiMo verification documented as an explicit step (env vars + command), not part of default `pytest`.
- [ ] AC10. README + `.env.example` updated with `MIMO_BASE_URL`, `MIMO_MODEL`, `MIMO_API_KEY` (blank) and a note that the key never ships in repo.

## Out of Scope

- TTS / ASR / manual parsing
- Durable idempotency storage
- Device firmware / skill_manager / local fallback template engine
- Anthropic protocol adapter (protocol choice fixed to OpenAI-compatible)
- Streaming, tool/function-calling, multi-turn conversation
- Non-diagnosis request types beyond `diagnosis` (later types follow the same seam)

## Open Questions

None blocking planning.

## Notes

- Complex task: `design.md` + `implement.md` required before `task.py start`.
- Keep technical HTTP/retry details in `design.md`, not here.
