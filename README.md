# VelaGuard Cloud (MQTT dashboard + legacy AI Bridge)

Cloud-side services for VelaGuard. This repository owns the **cloud backend only** (no device firmware).

```text
VelaGuard -> MQTT Broker -> Dashboard collector -> read-only web dashboard   (primary, 2026-09)
VelaGuard -> MQTT Broker -> AI Bridge -> HTTPS providers (MiMo)              (deprecated, kept)
```

## MQTT Cloud Dashboard (primary)

A read-only cloud dashboard: a Python collector subscribes to board-published
topics, persists state to SQLite, and serves a Chinese web UI over stdlib HTTP.

```text
vg/{device_id}/status        QoS 0, retained  -> device online/firmware/network (incl. LWT)
vg/{device_id}/telemetry     QoS 0            -> [{id, value, ok, age_ms}] + trend history
vg/{device_id}/alarm         QoS 1            -> raised/cleared events, durable alarm log
vg/{device_id}/point_table   QoS 1, retained  -> device point table, auto-synced in the UI
```

Features: multi-device fleet view, point-table auto-sync (rendered straight from
the board JSON), live values, trend charts, durable alarm history (captured even
while no browser is open), raw-message debug view with quarantine reasons.

The dashboard is **read-only end to end**: it never publishes to
`vg/{device_id}/...`, never acknowledges or clears alarms, and exposes GET-only
HTTP endpoints (boundary V5).

```bash
pip install -e .
docker compose -f deploy/dev/docker-compose.yml up -d     # dev Mosquitto
vg-dashboard                                              # or: python -m dashboard
python -m dashboard.tools.synthetic_board --device-id vg-demo01   # simulated board
# open http://localhost:8080
```

No-broker demo (seeds sample data directly): `python scripts/demo_dashboard_seed.py` → http://127.0.0.1:8765

Contract details for the board team (topics, payload JSON, quarantine rules,
HTTP API): [docs/dashboard-api.md](docs/dashboard-api.md) (Chinese).

## AI Bridge (deprecated, kept)

The original cloud AI Bridge remains runnable and tested, but is no longer the
primary product; the dashboard reuses its MQTT client and observability infra.

This first slice proves one end-to-end MQTT AI request/response loop with a pluggable provider (default **stub**, no live MiMo credentials required). A real OpenAI-compatible **MiMo** HTTPS provider is included behind the same seam and is opt-in via `PROVIDER=mimo`. `type=diagnosis` requests carry an optional structured `context` object (event, history, rules, device description, sensor register map, manual summary) that the bridge normalizes into a bounded prompt, and provider failures fall back to a schema-valid degraded result instead of a bare error.

For the current MQTT request/response contract, field rules, error codes, idempotency behavior, runtime configuration, and MiMo upstream details, see [docs/backend-api.md](docs/backend-api.md).

## Features

- Independent MQTT client (paho-mqtt)
- Subscribe `vg/+/ai/request` QoS 1, not retained
- Validate required fields: `req_id`, `device_id`, `created_ts_ms`, `type`, `payload_hash`
- Topic/payload `device_id` consistency check
- In-memory idempotency on `req_id + payload_hash`
- Pluggable `Provider` interface with default `StubProvider`
- Publish v1 response envelope on `vg/{device_id}/ai/response/{req_id}` QoS 1, not retained
- Normalize diagnosis context (`event` / `history` / `rules` / `device` / `sensor_config` / `manual_summary`) with tolerant drop/truncate rules
- Load `industrial_fault_diagnosis` skill markdown with built-in fallback prompt
- Fallback to `status=success` + `result.source="fallback"` when MiMo fails but the request budget remains
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
| `MQTT_TLS` | `false` | Enable MQTT over TLS (MQTTS); cert path config is ignored when `false` |
| `MQTT_CA_PATH` | *(none)* | CA bundle file path; empty uses the system CA store |
| `MQTT_CLIENT_CERT_PATH` | *(none)* | mTLS client certificate; must be paired with `MQTT_CLIENT_KEY_PATH` |
| `MQTT_CLIENT_KEY_PATH` | *(none)* | mTLS client private key; must be paired with `MQTT_CLIENT_CERT_PATH` |
| `REQUEST_TIMEOUT_MS` | `30000` | Overall request deadline |
| `PROVIDER` | `stub` | Provider selection (`stub` or `mimo`) |
| `STUB_DELAY_MS` | `0` | Artificial stub delay (timeout tests) |
| `LOG_LEVEL` | `INFO` | Logging level |
| `SKILLS_DIR` | *(package `ai_bridge/skills`)* | Directory with skill markdown files |
| `DIAGNOSIS_SKILL` | `industrial_fault_diagnosis` | Diagnosis skill file name (`^[a-z0-9_]+$`) |
| `FALLBACK_ENABLED` | `true` | Publish degraded fallback success on eligible provider failures |

### Diagnosis context contract

`type=diagnosis` requests may include an optional top-level `context` object:

```json
{
  "context": {
    "event": {"event_id": "evt_1", "severity": "warning", "title": "...", "current_value": 82.4},
    "history": [{"ts_ms": 1782450000000, "values": {"temperature": 72.8}}],
    "rules": [{"rule_id": "r1", "expr": "temperature > 70"}],
    "device": {"name": "Motor Temp", "model": "RS485-TH-1", "description": "..."},
    "sensor_config": {"registers": [{"key": "temperature", "addr": 40001}]},
    "manual_summary": "Temperature sensor lives in holding register 40001."
  }
}
```

Rules:

- `context` present but not an object → `validation_error`.
- `event` / `device` not objects, `history` / `rules` not arrays → dropped with a warning; the request still processes.
- `sensor_config` not an object → dropped with a warning (bounded to ~4,096 chars).
- `manual_summary` not a string → dropped with a warning (bounded to ~2,048 chars).
- `history` keeps the first 50 entries, `rules` keeps the first 20; non-object entries are dropped.
- Oversized sections are truncated with a `...[truncated]` marker.
- Missing sections are explicitly listed as `context_notes` in the provider prompt.
- History entries missing `ts_ms`/`values` are kept with an explicit `__missing__` marker.

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
`"source": "mimo"`. When MiMo fails with an HTTP/network error (not schema
invalid, not a deadline breach) and the request budget still has time, the
bridge publishes `status=success` with a degraded fallback result
(`source="fallback"`, `advisory_only=true`). Disable this with
`FALLBACK_ENABLED=false` to restore the plain `provider_error` behavior.
The HTTPS adapter uses `requests` as its synchronous HTTP client (blocking call
on MQTT worker threads), added to `pyproject.toml`.

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

## Unified board simulator and debug console

The two developer pages are now combined into one static page:

`board-sim/index.html` is the canonical entry point. It keeps the faithful 480x272 VelaGuard board HMI as the main workspace and exposes the full request debug console in an expandable right-side drawer. The board controls, request editor, MQTT connection, Mock engine, response viewer, timeline, history, and traffic log share one browser runtime and one MQTT client.

Open it directly:

- Double-click `board-sim/index.html`, or
- run `start board-sim/index.html` on Windows.

The old `debug-console/index.html` path is retained as a lightweight compatibility page that redirects to the unified entry point. It no longer loads a second debug application.

No build step, no npm, and no CDN are required. The only runtime mqtt.js copy is vendored under `board-sim/vendor/mqtt.min.js` (MIT).

### Modes and connection

- **Real mode (default).** Configure the broker WebSocket URL, client_id, optional username/password, and connect from the drawer. The page subscribes to `vg/{device_id}/ai/response/{req_id}` (QoS 1) before publishing to `vg/{device_id}/ai/request` (QoS 1, not retained). The bridge's processing and terminal envelopes are rendered in the same response viewer used by both board and debug requests.
- **Mock mode.** Fully offline. The board model keeps its six HMI scenarios (正常/预警/严重/离线/AI不可用/OTA中), while the request editor keeps its six protocol scenarios (v2 MiMo success, fallback, provider_error, timeout, validation_error, and conflict). Both flows use the same request event stream and can be inspected in history and traffic.
- Switching mode cancels incompatible pending requests. Connection, subscribe, publish, timeout, and invalid-response failures are shown inline without crashing the page.

### Request editor and response viewer

The drawer preserves the former debug-console capabilities:

- Edit `device_id`, `req_id`, `created_ts_ms`, fixed `type=diagnosis`, and read-only `payload_hash`.
- Edit `context.event`, `history`, `rules`, and `device` using form or JSON mode, with temperature, humidity, and empty-context presets. Invalid JSON blocks sending.
- Preview and export request JSON, import a request, copy the hash or complete response, clear history, and inspect the latest 50 requests.
- View response envelope fields, result tree/JSON, processing and terminal timeline events, and safe MQTT/Mock traffic. Passwords never enter the traffic log.

The board's AI diagnosis action builds context from the current board model (active alarm, selected sensor history up to 50 points, threshold rules up to 20, and device description) and sends through the same service. Requests sent from the drawer can update the board diagnosis when their device_id matches the current board device, without forcing a page navigation.

### payload_hash parity

The unified page computes the hash with the same algorithm as `ai_bridge.cli.synthetic_publisher.build_request`:

`sha256(json.dumps(body, sort_keys=True, separators=(",", ":")))`

The browser preserves the int/float distinction of JSON number tokens while hashing, so `1` and `1.0` remain different like Python. Values beyond the safe integer range may be rounded when displayed in the browser.

To verify an exported request:

```python
import json
from ai_bridge.cli.synthetic_publisher import build_request

exported = json.load(open("velaguard-request-....json"))
body = {k: v for k, v in exported.items() if k != "payload_hash"}
built = build_request(device_id=body["device_id"], extra=body)
assert built["payload_hash"] == exported["payload_hash"]
```

### Board replica relationship

The board frame remains a page-for-page replica of the current `main/ui/` sources: shell layout (`vg_shell.c`), model semantics (`vg_model.c`, including fleet seeding, scenario changes, home filters, alarm ack/mute, and log rotation), theme tokens, and page copy/behavior. When the C UI changes, sync `board-sim/` accordingly.

### Contract and browser checks

- `tests/contract/test_debug_console_hash_parity.py` checks the unified protocol core against Python.
- `tests/contract/test_board_sim_core.py` checks board context shape, v2 result mapping, Mock diagnosis outcomes, and real request construction.
- `python board-sim/e2e_smoke.py` checks the unified entry over `file://`, board Mock flows, drawer layout, and 1366x768 / 1920x1080 page-level scrolling. Add `--real` to send one live diagnosis when the dev broker and bridge are available.

### Security note

The default dev broker (`ws://107.174.123.74:9001`) is anonymous plaintext and publicly reachable; it is the existing dev posture and is **not** production-safe. Production must use MQTTS, per-device credentials/tokens, and Broker ACLs. A password entered in the browser stays in browser memory only: it is never echoed back, printed, or written into the traffic log.

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
  "diagnosis_summary": "本地 StubProvider 未调用在线 MiMo。",
  "risk_level": "low",
  "possible_causes": [],
  "recommended_actions": ["将 PROVIDER 设置为 mimo 以执行在线诊断。"],
  "need_shutdown": false,
  "confidence": 0.0,
  "source": "stub",
  "advisory_only": true
}
```

### v2 diagnosis result schema (MiMo / stub / fallback)

| Field | Type | Rule |
|---|---|---|
| `diagnosis_summary` | string | required, non-empty |
| `risk_level` | string | required, `low` \| `medium` \| `high` |
| `possible_causes` | list[string] | required, empty allowed |
| `recommended_actions` | list[string] | required, empty allowed |
| `need_shutdown` | boolean | required, bool-like ints rejected |
| `confidence` | number | optional, `[0, 1]`, bool rejected |
| `reasons` / `recommendations` | list[string] | optional, legacy compatibility |
| `source` | string | bridge-added: `mimo` \| `stub` \| `fallback` |
| `advisory_only` | boolean | stub/fallback only |
| `fallback_reason` | string | fallback only |

Unknown extra keys pass through. AI output is advisory only; the bridge never
authorizes device writes.

## Package layout

```text
ai_bridge/
  configuration/   # env settings
  contracts/       # topics, request/response models
  transport/mqtt/  # paho client, subscribe/publish
  application/     # orchestration + deadline + idempotency decisions
  providers/       # Provider protocol + StubProvider + MiMoProvider
  runtime/         # skill_manager, prompt_builder, json_validator, fallback
  skills/          # industrial_fault_diagnosis.md (packaged skill data)
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
- Natural-language sensor config generation (`type=sensor_config`) and inspection reports (roadmap items, see [docs/backend-api.md](docs/backend-api.md#101-路线图规划中未实现))
- SQL / Redis durable idempotency
- Production broker administration: token verification and Broker ACL management (bridge-side TLS client config via `MQTT_TLS` is implemented)
