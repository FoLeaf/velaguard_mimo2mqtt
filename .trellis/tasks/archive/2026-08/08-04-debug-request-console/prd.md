# VelaGuard board request debug console

## Goal

提供一个**仅用于 debug** 的 Web 控制台，模拟 VelaGuard 板端向 AI Bridge 发送诊断请求。默认走**真实后端**：浏览器通过 MQTT over WebSocket 连接 dev broker，把请求发布到 `vg/{device_id}/ai/request`，由真实 AI Bridge 处理（服务器 `PROVIDER=mimo` 时即真实 MiMo 调用），并订阅 `vg/{device_id}/ai/response/{req_id}` 实时展示响应。内置 mock 响应引擎保留为离线/演示 fallback。界面优化为**单屏 16:9 布局**：请求编辑、发送、响应、时间线、历史在同一个视口内全部可见，无需上下滚动。

## Confirmed Facts

来源：`.trellis/spec/backend/mqtt-ai-bridge-contracts.md`（v1/v2 场景）、`ai_bridge/contracts/request.py`、`ai_bridge/cli/synthetic_publisher.py`、归档任务 `08-04-ai-bridge-diagnosis-skill`、服务器勘察（2026-08-04）。

- 请求 topic：`vg/{device_id}/ai/request`；响应 topic：`vg/{device_id}/ai/response/{req_id}`；QoS 1、不 retained。
- 请求必填字段：`req_id`、`device_id`、`created_ts_ms`（Unix 毫秒）、`type`（当前仅 `diagnosis`）、`payload_hash`；可选 `context` 对象（`event`、`history`、`rules`、`device`）。
- `payload_hash` = SHA-256(`json.dumps(body, sort_keys=True, separators=(",", ":"))`)（与 `synthetic_publisher.build_request` 一致，hash 字段自身排除）。
- 响应信封：`processing` / `success` / `error`；错误码 `validation_error`、`conflict`、`timeout`、`provider_error`、`internal_error`。
- v2 诊断结果必填字段：`diagnosis_summary`、`risk_level`（low|medium|high）、`possible_causes`、`recommended_actions`、`need_shutdown`；可选 `confidence`、`reasons`、`recommendations`；`source`（mimo|fallback|stub）；fallback 加 `advisory_only=true`、`fallback_reason`。
- 真实桥接行为：正常路径先发 `processing` 再发终态；schema 非法 → `provider_error`（不 fallback）；HTTP/网络失败且预算剩余 → `success` + `source=fallback`；整体超时 → `timeout`；重复 `req_id` + 不同 `payload_hash` → `conflict`；`validation_error`/`conflict` 不先发 `processing`。
- 服务器部署：AI Bridge 在 `/opt/velaguard-ai-bridge`（`PROVIDER=mimo`，有真实 `MIMO_API_KEY`）；broker 为 Docker `dev-mosquitto-1`（eclipse-mosquitto:2），配置 bind-mount 自仓库 `deploy/dev/mosquitto/mosquitto.conf`，当前仅 `listener 1883` + `allow_anonymous true`，0.0.0.0 公网暴露（既有 dev 姿态）。
- 浏览器无法直连 TCP 1883，必须依赖 broker 的 WebSocket listener（mqtt.js）。

## Key Decisions

1. **默认真实后端**：页面连接可配置的 MQTT WebSocket broker（默认 `ws://107.174.123.74:9001`），发布/订阅真实 topic；连接失败或离线时提供明确错误，并可切换 Mock 模式离线演示。v1 的纯 mock 版本作为内置 fallback 保留。
2. **broker 增加 WebSocket 监听**：修改仓库 `deploy/dev/mosquitto/mosquitto.conf` 增加 `listener 9001` + `protocol websockets`，同步到服务器并重启 `dev-mosquitto-1` 容器。保持与现有 1883 一致的 dev 姿态（匿名、明文）；公网暴露属既有风险，本任务不引入生产级 MQTTS/ACL（范围外）。
3. **mqtt.js 本地 vendored**：`debug-console/vendor/mqtt.min.js` 随仓库提交（MIT），不用 CDN，保证 `file://` 打开时 mock 模式仍可离线使用、真实模式不依赖第三方 CDN 可用性。
4. **单屏 16:9 布局**：页面 `height: 100dvh`，CSS Grid 左右分栏（左：请求编辑 + 发送；右：响应 + 时间线 + 历史），面板内部各自滚动，页面级不滚动；发送按钮常驻可见，响应区域与请求区域同屏。
5. **设计走 design-taste 原则**：design read = "developer debug console for the VelaGuard team, dark tech / instrument-panel language, native CSS + mono type + one accent, restrained motion"。全局单主题（暗色）、单强调色、统一圆角；状态完整（empty/loading/error/connecting/connected/disconnected）。
6. **界面语言中文**；请求/响应 JSON 原文展示。

## Requirements

- R1. `debug-console/index.html` 单页应用，`file://` 可打开；mock 模式零网络依赖，真实模式依赖可配置的 MQTT WebSocket 连接。
- R2. 请求编辑器：`device_id`、`req_id`（默认 UUID）、`created_ts_ms`（默认当前毫秒，可覆盖）、`type` 固定 `diagnosis`、只读自动 `payload_hash` + 刷新按钮。
- R3. 上下文编辑器：`event`/`history`/`rules`/`device` 四段，表单或 JSON 编辑；2-3 个预设（温度超限、湿度低、空上下文）；非法 JSON 就地报错并阻止发送。
- R4. 真实发送模式：连接面板（broker URL、client_id、可选用户名/密码、连接/断开状态徽标）；发送时自动订阅 `vg/{device_id}/ai/response/{req_id}` 再发布请求（QoS 1）；实时展示 processing 与终态；连接失败/发布失败就地报错；重复发送同一 `req_id` 会触发真实幂等/冲突行为。
- R5. Mock 响应引擎（离线 fallback）：保留 v2 MiMo 成功、fallback 降级、schema 非法 provider_error、整体 timeout、validation_error、conflict 六个场景，可配置延迟，先 processing 再终态（validation_error/conflict 除外，与真实行为一致）。
- R6. 响应查看器：信封字段 + result 树/JSON 双视图、状态/错误码徽标、复制 JSON；时间线显示 `received_ts_ms`/`bridge_ts_ms` 与相对耗时。
- R7. 单屏布局：16:9 浏览器视口（至少 1920x1080 与 1366x768）下无需页面级滚动即可完成“填数据 → 发送 → 看响应”；面板内部溢出可滚动。
- R8. Debug 辅助：请求历史（倒序、最近 50 条）、清空、导出/导入单个请求 JSON。
- R9. README 更新：真实模式连接说明（默认 broker URL、如何改、与 dev broker 的安全注意）、mock 场景含义、`payload_hash` 一致性说明、未来生产 MQTTS 方向。

## Acceptance Criteria

- [ ] AC1. `file://` 打开页面无报错；mock 模式无网络依赖可用。
- [ ] AC2. `payload_hash` 与 `synthetic_publisher.build_request` 算法逐字节一致（含非 ASCII、嵌套对象、int/float 边界）。
- [ ] AC3. 真实模式：服务器 broker（9001 WS）+ AI Bridge 运行中，页面发送诊断请求后收到真实 `processing` 与终态响应，`req_id` 一致；MiMo 可用时 `source=mimo`，不可用时 `source=fallback`（与服务器实测一致）。
- [ ] AC4. 连接失败/发布失败在页面内就地显示错误，不黑屏不崩溃；Mock 模式可一键切换继续演示。
- [ ] AC5. 六个 mock 场景响应符合契约（成功 v2 必填字段；fallback `success`+`source=fallback`+`advisory_only`；schema 非法 `provider_error`；timeout；validation_error/conflict 无 processing）。
- [ ] AC6. 16:9 单屏验收：1920x1080 与 1366x768 下，请求编辑、发送按钮、响应区、时间线、历史同屏可见，页面级无滚动。
- [ ] AC7. 非法上下文 JSON 就地报错并阻止发送；复制/导出/导入/清空历史可用，历史倒序保留 50 条。
- [ ] AC8. 服务器 mosquitto 配置同步后 9001 WS 监听生效，容器重启后 bridge 自动重连，1883 行为不变。
- [ ] AC9. 设计预检：单一强调色、统一圆角、暗色主题、对比度 WCAG AA、reduced-motion、empty/loading/error/connecting 状态齐全、页面零 em-dash。
- [ ] AC10. README 包含真实模式与 mock 模式说明、默认连接参数、安全注意。

## Out of Scope

- 生产级 MQTTS、设备 token、Broker ACL、鉴权体系（dev 匿名姿态维持现状）
- 任何后端/桥接代码改动（除 dev broker 配置文件）
- 持久化存储、多人协作、移动端适配（以 16:9 桌面为主）
- 非 `diagnosis` 请求类型
