# Journal - 19y (Part 1)

> AI development session journal
> Started: 2026-08-03

---



## Session 1: Finish bootstrap guidelines

**Date**: 2026-08-03
**Task**: Finish bootstrap guidelines
**Branch**: `main`

### Summary

Confirmed backend-only Trellis specs for VelaGuard AI Bridge were already filled and committed. Archived 00-bootstrap-guidelines. Next active work is planning 08-03-ai-bridge-mqtt-minimal.

### Git Commits

| Hash | Message |
|------|---------|
| `13bda1e` | (see git log) |

### Status

[OK] **Completed**


## Session 2: AI Bridge minimal MQTT loop

**Date**: 2026-08-03
**Task**: AI Bridge minimal MQTT loop
**Branch**: `main`

### Summary

Planned, implemented, checked and deployed the first AI Bridge slice: Python 3.12 paho-mqtt worker, v1 response envelope, in-memory disposable idempotency, pluggable stub provider, Docker Mosquitto dev stack. Verified end-to-end on server 107.174.123.74 (mosquitto + bridge), 45 unit/contract + 1 integration tests passed. Specs updated in .trellis/spec/backend.

### Git Commits

| Hash | Message |
|------|---------|
| `fb124c5` | (see git log) |
| `027bb89` | (see git log) |
| `a63c841` | (see git log) |

### Status

[OK] **Completed**


## Session 3: Real MiMo provider integration

**Date**: 2026-08-03
**Task**: Real MiMo provider integration
**Branch**: `main`

### Summary

Added MiMoProvider (OpenAI-compatible chat completions) behind the Provider seam: schema-validated diagnosis result, bounded retry, per-attempt timeout, key via MIMO_API_KEY env only (never committed). 91 tests pass (mock-based). Deployed to server 107.174.123.74 and verified live MiMo call with mimo-v2.5 model; corrected default model after /models check. Specs updated.

### Git Commits

| Hash | Message |
|------|---------|
| `a0f35b4` | (see git log) |
| `527a4af` | (see git log) |
| `b4214c6` | (see git log) |
| `d0085b5` | (see git log) |

### Status

[OK] **Completed**


## Session 4: AI 诊断 Skill 与 fallback 闭环

**Date**: 2026-08-04
**Task**: AI 诊断 Skill 与 fallback 闭环
**Branch**: `main`

### Summary

实现云端诊断闭环：Agent Runtime（skill_manager/prompt_builder/json_validator/fallback）+ industrial_fault_diagnosis Skill + v2 结果 schema；fallback 语义为 status=success + source=fallback + advisory_only（用户确认），timeout/schema 非法不进 fallback。156 单测/契约通过，ruff+mypy 干净；检查代理修复 confidence 大整数溢出、user 消息 8192 上限兜底等。已部署到 107.174.123.74:42387（/opt/velaguard-ai-bridge，旧版已备份），实机验证 live MiMo v2 成功 + fallback 降级成功，服务已恢复。任务已归档。

### Git Commits

| Hash | Message |
|------|---------|
| `824002e` | (see git log) |
| `4a5abf3` | (see git log) |
| `6a681a4` | (see git log) |
| `967083a` | (see git log) |

### Status

[OK] **Completed**


## Session 5: VelaGuard debug console：真实后端 + 单屏布局

**Date**: 2026-08-04
**Task**: VelaGuard debug console：真实后端 + 单屏布局
**Branch**: `main`

### Summary

新增 debug-console（零依赖静态页）：请求编辑器自动算 payload_hash（与 Python build_request 逐字节一致，新增 13 组契约测试）、context 四段编辑器与预设、6 个契约保真 mock 场景；v2 改版接入真实后端（MQTT over WebSocket，vendored mqtt.js 5.15.2），默认连 ws://107.174.123.74:9001，订阅响应 topic 实时展示 processing/终态，断连/错误可恢复并可切 mock；UI 重构为单屏 16:9（100dvh 左右分栏，1366x768/1920x1080 无页面滚动）；服务器 mosquitto 增加 9001 WebSocket 监听并已部署验证（101 握手、bridge 自动重连、1883 不变），真实 E2E 经 bridge 日志确认 success 与 conflict；trellis-check 修复 pending 卡死、dvh 高度，159 测试全绿，ruff/mypy 干净。任务已归档。

### Git Commits

| Hash | Message |
|------|---------|
| `3ee134d` | (see git log) |
| `d964e64` | (see git log) |
| `1573d2f` | (see git log) |

### Status

[OK] **Completed**


## Session 6: VelaGuard 板端 HMI Web 模拟器（真实后端）

**Date**: 2026-08-04
**Task**: VelaGuard 板端 HMI Web 模拟器（真实后端）
**Branch**: `main`

### Summary

新增 board-sim/：480×272 板端 HMI 忠实复刻（home/device/trend/alarm/diagnosis/logs + shell/toast/返回栈，逐页对照 LVGL C 源码与 token），六场景/首页筛选与 vg_model 语义一致；真实模式经 MQTT WebSocket 连 ws://107.174.123.74:9001，点击 AI 诊断由模型构建 context（event/history≤50/rules≤20/device）发真实请求，processing/终态实时渲染（mimo OK、fallback 降级、error 重试），60s watchdog 与断连恢复；工具栏含场景切换/模式切换/连接面板/流量日志；16:9 单屏无页面滚动；board-core.js 纯逻辑双用并新增契约测试（payload_hash 双工具参数化），168 测试全绿；trellis-check 修复 watchdog 死代码与 mock 取消挂起；真实 E2E 多次验证 source=mimo。任务已归档。

### Git Commits

| Hash | Message |
|------|---------|
| `8a01dca` | (see git log) |
| `9e6b032` | (see git log) |
| `bd8df09` | (see git log) |

### Status

[OK] **Completed**


## Session 7: Unify board simulator and debug console

**Date**: 2026-08-04
**Task**: Unify board simulator and debug console
**Branch**: `main`

### Summary

Merged board-sim and debug-console into one static board-centered page with a shared MQTT/Mock request service, request/response drawer, compatibility redirect, contract and browser smoke coverage, and wider response/timeline/history areas with a one-click collapse button. Committed as eede8f3 and archived Trellis task 6083d56.

### Git Commits

| Hash | Message |
|------|---------|
| `eede8f3` | (see git log) |

### Status

[OK] **Completed**


## Session 8: Prefer Chinese diagnosis output

**Date**: 2026-08-04
**Task**: Prefer Chinese diagnosis output
**Branch**: `main`

### Summary

Added Chinese-first language instructions to diagnosis prompts and skills, localized fallback and StubProvider results, updated backend language contract and regression tests. Full pytest, ruff, mypy, and compileall passed. Remote MiMo Bridge still needs this commit deployed and restarted.

### Git Commits

| Hash | Message |
|------|---------|
| `fe64234` | (see git log) |

### Status

[OK] **Completed**


## Session 9: Backend acceptance against project manual + deploy

**Date**: 2026-08-17
**Task**: Backend acceptance against project manual + deploy
**Branch**: `main`

### Summary

对照项目手册验收后端：核心契约符合，记录 8 项差距（G1-G8）。按决策（手册采纳 diagnosis_summary、sensor_config 拆后续任务）实现 MQTTS 支持（MQTT_TLS/CA/mTLS）与 context 扩展（sensor_config/manual_summary 六段容错），文档记录已验收偏差与路线图。191 测试全绿。已部署到 107.174.123.74:42387 /opt/velaguard-ai-bridge 并端到端验证 MiMo status=success。

### Git Commits

| Hash | Message |
|------|---------|
| `42e0ca0` | (see git log) |
| `6e28e2e` | (see git log) |

### Status

[OK] **Completed**


## Session 10: MQTT cloud dashboard: collector + SQLite + web UI (AI Bridge deprecated)

**Date**: 2026-09-13
**Task**: MQTT cloud dashboard: collector + SQLite + web UI (AI Bridge deprecated)
**Branch**: `main`

### Summary

Pivoted repo primary product to a read-only MQTT cloud dashboard per user request (AI Bridge no longer needed but kept and reused). New dashboard/ package: collector subscribes vg/+/status|telemetry|alarm|point_table (reusing generalized ai_bridge MqttBridgeClient with subscribe_filters param), tolerant ingest with quarantine ring buffer, sqlite3 store (devices/points/point_syncs/telemetry latest+history/alarms+events/raw_messages with retention), stdlib ThreadingHTTPServer with GET-only API and Chinese vanilla-JS UI (fleet view, point-table auto-sync from board JSON, live values, SVG trend charts, durable alarm log, raw-message debug view). Defined new topic vg/{id}/point_table (QoS1 retained, spec amendment) adopting TeamFalcons point-table schema; documented full board-facing contract in docs/dashboard-api.md for the TeamFalcons C1 implementation. Verified in a real browser end-to-end (scripts/demo_dashboard_seed.py, no broker needed): all four views render incl. LWT offline device, alarm raise, trend wave, quarantined message. 265 unit/contract tests green (ai_bridge regression-free); integration test added (broker-gated). Fixed during check: raw buffer now records valid messages too; oversize payloads stored truncated; per-message log demoted to debug; UI skip-rerender-when-unchanged to keep click targets stable.

### Git Commits

| Hash | Message |
|------|---------|
| `c9a06fe` | (see git log) |

### Status

[OK] **Completed**
