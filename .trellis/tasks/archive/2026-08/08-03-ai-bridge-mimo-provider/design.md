# Design: Real MiMo provider integration

## Summary

Add `MiMoProvider` behind the existing `Provider` seam. It calls an OpenAI-compatible chat completions endpoint, extracts `choices[0].message.content`, validates it against the v1 diagnosis schema, and returns `ProviderSuccess` / `ProviderFailure`. The MQTT v1 envelope, idempotency, and orchestration layers stay unchanged.

## Architecture Boundaries

New module: `ai_bridge/providers/mimo.py`. Modified files:

- `ai_bridge/providers/mimo.py` (new) — `MiMoProvider`
- `ai_bridge/providers/schema.py` (new, optional small module) — diagnosis result schema validation helpers
- `ai_bridge/providers/base.py` — `build_provider("mimo")` returns `MiMoProvider`
- `ai_bridge/configuration/settings.py` — add `MIMO_BASE_URL`, `MIMO_MODEL`, `MIMO_API_KEY` (secret), optional `MIMO_HTTP_TIMEOUT_MS`, retry knobs
- `ai_bridge/observability/logging.py` — ensure `mimo_api_key` is in redaction set (already matches `api_key` pattern; keep explicit)
- `.env.example`, `README.md` — document MiMo env vars, blank key, live-verify steps

Dependency direction preserved: providers depend on `contracts` models only; no MQTT/application imports. HTTP client is chosen inside the provider module.

## Data Flow

```text
HandleAiRequest (unchanged)
  → remaining deadline_s
  → MiMoProvider.handle(request, deadline_s)
       build messages [system: fixed diagnosis prompt, user: request summary]
       attempt := HTTP POST {base}/chat/completions
         headers: Authorization: Bearer <key>, Content-Type: application/json
         body: {"model": MIMO_MODEL, "messages": [...], "temperature": 0, "response_format": {"type":"json_object"}}
         timeout: min(MIMO_HTTP_TIMEOUT_MS, remaining)
         on transient/429/5xx: bounded retry with backoff inside remaining budget
         on non-transient (401/403/400): ProviderFailure(provider_error)
       parse JSON response; extract choices[0].message.content
       parse content as JSON → validate against v1 diagnosis schema
         invalid → ProviderFailure(provider_error)
       valid → ProviderSuccess({"diagnosis_summary": ..., "reasons": ..., "recommendations": ..., "confidence": ..., "source": "mimo"})
  → HandleAiRequest publishes success/error with v1 envelope (unchanged)
```

## Contracts

### Config additions

| Env | Type | Default | Notes |
|---|---|---|---|
| `MIMO_BASE_URL` | str | `https://token-plan-cn.xiaomimimo.com/v1` | no trailing slash handling; join `/chat/completions` |
| `MIMO_MODEL` | str | `mimo-v2.5` (confirmed live 2026-08-03) | actual MiMo model id |
| `MIMO_API_KEY` | str (secret) | unset | required for `PROVIDER=mimo`; validated at build time |
| `MIMO_HTTP_TIMEOUT_MS` | int | e.g. `15000` | per-attempt timeout < overall deadline |
| `MIMO_MAX_RETRIES` | int | e.g. `2` | bounded; only transient statuses |
| `MIMO_RETRY_BACKOFF_MS` | int | e.g. `500` | with jitter |

`build_provider("mimo")` raises a clear `ValueError` at startup if `MIMO_API_KEY` is unset (fail fast, not mid-request).

### Result schema validation (v1)

```text
diagnosis_summary: required, str, non-empty (strip)
reasons:          optional, list[str] (each str)
recommendations:  optional, list[str]
confidence:       optional, float in [0,1]
extra keys:       allowed, passed through? -> design: pass through (forward-compatible), or drop? 
                  Decision: pass through unknown keys as-is (forward-compatible); schema only validates known fields' types.
```

Return normalized dict; reject with `ProviderFailure(code="provider_error", message="provider output failed schema validation")` (message without secrets).

### Prompt (system)

For `type=diagnosis`, fixed system prompt template (module constant, no secrets, no device data beyond safe summary):

```text
You are a VelaGuard industrial diagnosis assistant. Analyze the device request and return ONLY a JSON object with this schema:
{"diagnosis_summary": string, "reasons": [string], "recommendations": [string], "confidence": number 0..1}
```

User message: safe summary of request fields (`device_id`, `type`, bounded request body size cap — do not dump full arbitrary payload; include a truncated JSON body, e.g. first 2 KB).

## Error Classification (mapping to v1 codes)

| MiMo HTTP / parse condition | ProviderFailure code | Published status |
|---|---|---|
| 200 + valid schema | success | success |
| 200 + invalid JSON / missing summary / bad types | provider_error | error |
| 401 / 403 (auth) | provider_error (non-retryable) | error |
| 400 (bad request / schema reject) | provider_error | error |
| 429 / 5xx / network transient | retry up to MIMO_MAX_RETRIES; if exhausted → provider_error | error |
| deadline exceeded at any point | timeout | error |

Do not map MiMo failures to `internal_error`; that is reserved for unexpected bridge exceptions.

## Retry Policy

- Retry only transient: 429, 5xx, connection errors, timeouts of a single attempt
- Do not retry 4xx except 429; do not retry validation failures
- Keep total attempts × per-attempt timeout + backoff inside `REQUEST_TIMEOUT_MS`
- Idempotency already prevents duplicate work on retried MQTT deliveries; MiMo retries within one request are just attempt-level

## HTTP Client Choice

Use `requests` (sync, simple) or `httpx`. Since `HandleAiRequest` runs on MQTT worker threads, a blocking client is acceptable. Prefer `requests` for minimal deps unless `httpx` already present. Add to `pyproject.toml` dependencies.

Exact choice recorded at implementation; keep timeout set per attempt.

## Observability

- Log: attempt number, HTTP status (not headers/body secrets), elapsed ms, outcome, error_code
- Redact: `Authorization` header value, `MIMO_API_KEY`, any key-like strings
- Never log raw MiMo response bodies beyond a bounded safe excerpt (or not at all — prefer not at all for v1)
- Include `device_id` / `req_id` correlation from the request

## Testing Strategy

### Mock server

`tests/helpers/mimo_stub_server.py` — small `http.server`-based OpenAI-compatible stub:

- `/chat/completions` returns configurable content:
  - valid JSON schema
  - invalid JSON
  - missing `diagnosis_summary`
  - wrong types
  - HTTP 429 then success (retry path)
  - HTTP 500 always (exhausted retries)
  - slow response (timeout path)
- Verifies `Authorization: Bearer <key>` header present (no key assertion on content)

### Unit/contract tests (no live MiMo)

- `build_provider("mimo")` without key → raises
- request building: messages shape, model, response_format
- schema validation matrix (good/bad cases above)
- retry logic on 429/5xx, no retry on 4xx
- timeout path
- secret redaction for `mimo_api_key`

### Live verify (optional, manual)

```bash
MIMO_API_KEY=<key> MIMO_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1 PROVIDER=mimo python -m ai_bridge
# then publish a request via MQTTX / synthetic publisher; expect success result with source=mimo
```

## Compatibility / Rollout

- v1 MQTT envelope unchanged → device-facing contract untouched
- `PROVIDER=stub` default unchanged → regression safe
- `PROVIDER=mimo` is opt-in via env
- Greenfield addition; rollback = set `PROVIDER=stub` (or revert commit)

## Explicit Non-Goals

- No streaming / tools / multi-turn
- No Anthropic adapter
- No durable storage
- No device-side skill management
- No auto-fallback to stub when MiMo fails (that stays a future product decision; current behavior publishes provider_error so device can fall back locally)
