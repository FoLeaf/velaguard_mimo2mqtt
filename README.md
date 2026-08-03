# VelaGuard AI Bridge (minimal MQTT loop)

Cloud-side AI Bridge for VelaGuard. This repository owns the **backend bridge only** (no device firmware).

```text
VelaGuard -> MQTT Broker -> AI Bridge -> HTTPS providers (MiMo later)
```

This first slice proves one end-to-end MQTT AI request/response loop with a pluggable provider (default **stub**, no live MiMo credentials required). A real OpenAI-compatible **MiMo** HTTPS provider is included behind the same seam and is opt-in via `PROVIDER=mimo`.

## Features

- Independent MQTT client (paho-mqtt)
- Subscribe `vg/+/ai/request` QoS 1, not retained
- Validate required fields: `req_id`, `device_id`, `created_ts_ms`, `type`, `payload_hash`
- Topic/payload `device_id` consistency check
- In-memory idempotency on `req_id + payload_hash`
- Pluggable `Provider` interface with default `StubProvider`
- Publish v1 response envelope on `vg/{device_id}/ai/response/{req_id}` QoS 1, not retained
- Bounded request deadline → `status=error`, `error_code=timeout`
- Secrets never written into MQTT payloads or plain logs

## Important: disposable idempotency

**In-memory idempotency is process-lifetime only.**

- Restarting the bridge **clears** all claim/complete/fail state
- This is **not** restart-safe production behavior
- A durable store is intentionally out of scope for this slice

Do not treat local verification success as production readiness for deduplication.

## Requirements

- Python 3.12+
- Docker (optional, for local Mosquitto)

## Setup

```bash
python -m venv .venv
# Windows Git Bash / Linux / macOS
source .venv/bin/activate   # or: .venv\Scripts\activate on Windows cmd
pip install -e ".[dev]"
# or: pip install -r requirements.txt
```

## Local Mosquitto

Start a plaintext broker on `localhost:1883` (controlled-LAN / local verification only):

```bash
docker compose -f deploy/dev/docker-compose.yml up -d
```

Stop:

```bash
docker compose -f deploy/dev/docker-compose.yml down
```

Production requires MQTTS, per-device credentials/tokens, and Broker ACLs. Plaintext anonymous MQTT must never be a production fallback.

## Run the bridge

```bash
# defaults: MQTT_HOST=localhost MQTT_PORT=1883 PROVIDER=stub REQUEST_TIMEOUT_MS=30000
python -m ai_bridge
```

Useful environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `MQTT_HOST` | `localhost` | Broker host |
| `MQTT_PORT` | `1883` | Broker port |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | empty | Optional auth |
| `MQTT_CLIENT_ID` | `ai-bridge-dev` | Bridge client id |
| `REQUEST_TIMEOUT_MS` | `30000` | Overall request deadline |
| `PROVIDER` | `stub` | Provider selection (`stub` or `mimo`) |
| `STUB_DELAY_MS` | `0` | Artificial stub delay (timeout tests) |
| `LOG_LEVEL` | `INFO` | Logging level |

### MiMo provider (optional, `PROVIDER=mimo`)

| Variable | Default | Purpose |
|---|---|---|
| `MIMO_BASE_URL` | `https://token-plan-cn.xiaomimimo.com/v1` | MiMo API base; provider calls `{base}/chat/completions` |
| `MIMO_MODEL` | `mimo-v2.5` | MiMo model id (confirmed live) |
| `MIMO_API_KEY` | *(none)* | **Secret.** Required for `PROVIDER=mimo`; startup fails fast if unset |
| `MIMO_HTTP_TIMEOUT_MS` | `15000` | Per-HTTP-attempt timeout (kept inside `REQUEST_TIMEOUT_MS`) |
| `MIMO_MAX_RETRIES` | `2` | Retry budget for transient failures (429/5xx/network) |
| `MIMO_RETRY_BACKOFF_MS` | `500` | Base backoff between retries (with jitter) |

MiMo responses are forced to JSON (`response_format={"type":"json_object"}`) and
schema-validated before being published as success. Invalid output is published
as `status=error`, `error_code=provider_error`, never success. The result carries
`"source": "mimo"`. The HTTPS adapter uses `requests` as its synchronous HTTP
client (blocking call on MQTT worker threads), added to `pyproject.toml`.

**Secret note (mandatory).** `MIMO_API_KEY` is a live credential. It is injected
only via the deploy-time server environment (server-local `.env`, gitignored).
It must **never** be committed to this repo, added to tests/fixtures, pasted
into the README, or shared in chat. `.env.example` keeps the value blank. The
bridge redacts `mimo_api_key` from every log and MQTT payload.

## Synthetic publisher

With Mosquitto and the bridge running:

```bash
python -m ai_bridge.cli.synthetic_publisher --device-id dev01
python -m ai_bridge.cli.synthetic_publisher --help
```

## Tests

Unit/contract tests do **not** require a live broker or MiMo key. The MiMo
adapter tests run against a local OpenAI-compatible stub HTTP server
(`tests/helpers/mimo_stub_server.py`):

```bash
pytest tests/unit tests/contract -q
```

Integration tests (optional; need Mosquitto on `localhost:1883`):

```bash
docker compose -f deploy/dev/docker-compose.yml up -d
pytest tests/integration -q
```

## Live MiMo verification (manual, optional)

The default test suite never calls the real MiMo API. To verify against the
live service, you need a real key on the server environment **and a running
Mosquitto broker**:

```bash
# On the deploy server only: inject the key from server-local .env, never from
# the repo or chat. Do not echo or commit the key.
MIMO_API_KEY=<your-server-key> \
MIMO_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1 \
MIMO_MODEL=mimo-v2.5 \
PROVIDER=mimo REQUEST_TIMEOUT_MS=60000 python -m ai_bridge
```

Then publish a diagnosis request (e.g. via MQTTX or the synthetic publisher):

```bash
python -m ai_bridge.cli.synthetic_publisher --device-id dev01
```

Expect a `status=success` response whose `result` contains a
`diagnosis_summary` and `"source": "mimo"`. This is an explicit manual step, not
part of `pytest`.

## v1 response envelope

```json
{
  "req_id": "...",
  "device_id": "...",
  "type": "...",
  "status": "processing|success|error",
  "error_code": null,
  "error_message": null,
  "result": null,
  "received_ts_ms": 0,
  "bridge_ts_ms": 0
}
```

Error codes: `validation_error`, `conflict`, `timeout`, `provider_error`, `internal_error`.

Stub diagnosis success places structured content under `result`:

```json
{
  "diagnosis_summary": "stub: no live MiMo call",
  "source": "stub",
  "advisory_only": true
}
```

AI output is advisory only; the bridge never authorizes device writes.

## Package layout

```text
ai_bridge/
  configuration/   # env settings
  contracts/       # topics, request/response models
  transport/mqtt/  # paho client, subscribe/publish
  application/     # orchestration + deadline + idempotency decisions
  providers/       # Provider protocol + StubProvider + MiMoProvider
  persistence/     # in-memory disposable idempotency store
  observability/   # logging + redaction
  cli/             # synthetic publisher
deploy/dev/        # Docker Compose Mosquitto
tests/
```

## Out of scope (this slice)

- Device firmware / LVGL UI
- Live MiMo verification is manual (see above); the automated suite uses a stub
- TTS / ASR / manual parsing / OTA
- SQL / Redis durable idempotency
- Production MQTTS / token / ACL product features
