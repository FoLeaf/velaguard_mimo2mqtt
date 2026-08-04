# VelaGuard board HMI web simulator

## Goal

在 Web 上**忠实复刻** 480×272 的 VelaGuard 板端 HMI（参考 LVGL 工程 `D:/Study/Embeded/Velaguard/GUI`），可以像点真实屏幕一样操作首页、设备详情、趋势、告警、诊断、日志；点击“AI 诊断”时默认走**真实后端**：浏览器经 MQTT WebSocket 连接 dev broker，发布真实诊断请求，由真实 AI Bridge/MiMo 处理，并把 processing/终态结果实时渲染到复刻的诊断页。Mock 模型保留用于离线演示。仅用于开发与演示，不是产品前端。

## Confirmed Facts

来源：`D:/Study/Embeded/Velaguard/GUI`（`main/ui/` 源码、`README_CN.md`、QA 截图）、`.trellis/spec/backend/mqtt-ai-bridge-contracts.md`、本仓库 `debug-console/`（已实现并验证）。

- 板端 UI：LVGL 9.1 + SDL 模拟器，480×272；shell（状态栏 28px + content host + 返回栈 + toast）；页面 home/device/trend/alarm/diagnosis/logs（add_sensor/system/ota 为预留入口）；widgets：status chip、device card、sensor tile、metric row、risk badge。
- 主题 token：bg `#1A1D21`、surface `#24292E`、border `#3A424A`、text `#E8ECF0`、muted `#9AA3AD`、ok `#2F9E44`、warn `#F0A202`、crit `#E03131`、offline `#6C757D`、info/accent `#1C7ED6`；卡片圆角 4px；触摸目标 ≥36×40px；列表行高 40px。
- 模型（`vg_model`）：六场景 normal/warn/crit/offline/ai_down/ota（C 版用数字键 1-6 切换）；传感器（值/阈值/单位/质量/历史 60 点）；告警（severity/title/acked/muted）；网络状态（net/mimo/acq/aud/ota/ip/latency）；诊断四态 idle/loading/ok/error（summary/risk/causes[3]/actions[3]/confidence_pct/error_msg/alarm_title）；日志五类（alarm/diag/sys/ota/ui）。当前全部为 mock，无网络层。
- 诊断页交互：进入诊断页 → `vg_model_request_diagnosis()` → LOADING → OK/ERROR；有重试按钮；风险徽标 low/medium/high → ok/warn/crit 色。
- 后端契约（与 `debug-console` 相同）：请求 topic `vg/{device_id}/ai/request`、响应 `vg/{device_id}/ai/response/{req_id}`，QoS 1；必填字段 + 可选 `context`（event/history/rules/device）；`payload_hash` = SHA-256(递归排序键 JSON，`,`/`:` 分隔，排除 hash 自身)；v2 结果（`diagnosis_summary`/`risk_level`/`possible_causes`/`recommended_actions`/`need_shutdown`/`confidence`）；fallback 为 `success`+`source=fallback`+`advisory_only=true`；`validation_error`/`conflict` 无 processing。
- 服务器已部署：dev broker 9001 WebSocket（`ws://107.174.123.74:9001`，已验证 101 握手）、AI Bridge `PROVIDER=mimo`（真实 key）；真实 E2E 已通过。
- `debug-console/` 已有可复用资产：vendored `mqtt.min.js`（5.15.2）、Python 兼容 canonical JSON + SHA-256、六场景契约 mock、单屏 16:9 布局经验。

## Key Decisions

1. **方案 A（用户确认）**：HTML/CSS/JS 忠实复刻，不跑真实 C 代码；`main/ui/` 源码与 `bin/qa/*.png` 截图作为复刻基准。
2. **存放位置**：本仓库 `board-sim/`（与 `debug-console/` 并列，保持静态三件套 + `vendor/mqtt.min.js` 自包含复制）。
3. **真实范围**：仅 AI 诊断请求/响应真实；传感器值、趋势、告警、日志、网络状态仍为 mock（与板端当前能力一致）。alarm 确认/静音保持板端 mock 行为。
4. **双模式**：真实（默认）/ Mock（离线演示），连接面板模式复用 `debug-console` 的经验（broker URL、client_id、状态徽标、断连恢复）。
5. **单屏 16:9**：页面 `100dvh` 网格，左侧 480×272 板端框（等比缩放、可点），右侧开发工具栏（场景切换、模式/连接、原始流量日志）；页面级不滚动。
6. **设计**：以板端 token 为准（不是新设计）；单一强调色 `#1C7ED6`、统一圆角 4px、CJK 系统字体栈；design-taste 预检仍适用（对比度、reduced-motion、零 em-dash、状态完整）。

## Requirements

- R1. `board-sim/index.html` 单页，`file://` 可打开；mock 模式离线可用；真实模式依赖可配置 MQTT WebSocket。
- R2. 板端框内页面与 C 版一致：home（状态栏 + 设备卡/瓷砖 + 告警摘要 + 快捷操作）、device（详情/寄存器/阈值/质量/周期）、trend（最近 60 点曲线 + 阈值线）、alarm（列表/详情 + 确认/静音）、diagnosis（loading/ok/error + 重试）、logs（五类日志）；返回栈、toast、状态栏字段（NET/MiMo/采集/音频/OTA/IP/延迟）一致。
- R3. 场景系统：六场景 + 首页筛选（全部/告警/离线/正常），与 `vg_model` 语义一致；场景切换入口在右侧工具栏（等价 C 版 1-6 键），不侵入板端框。
- R4. 真实诊断流：连接面板（默认 `ws://107.174.123.74:9001`、client_id、可选用户名/密码、连接状态）；点击 AI 诊断 → 用当前模型状态构建 `context`（选中传感器、活动告警、历史 60→50 点、规则由阈值生成、设备说明）→ 先订阅 `vg/{device_id}/ai/response/{req_id}`（QoS 1）再发布请求 → 实时渲染 processing → 终态；`source=mimo` 显示 OK，`source=fallback` 显示降级提示，`error` 显示错误 + 重试；断连/发布失败就地报错并可切 mock。
- R5. Mock 诊断：保留板端预设（LOADING → OK/ERROR 场景可配），与 C 版 `vg_model_request_diagnosis` 行为一致。
- R6. 开发工具栏：场景按钮、真实/Mock 切换、连接状态徽标、原始流量日志（请求/响应 JSON，可折叠、可清空）；工具栏不进入板端框。
- R7. 契约保真：`payload_hash` 与 `build_request` 逐字节一致；`context` 字段结构符合契约；响应信封/错误码/v2 字段/fallback 语义不变。
- R8. 设计约束：板端色板/圆角/间距精确复刻；状态/风险徽标用板端语义色；零 em-dash；`prefers-reduced-motion`；文本对比度 WCAG AA（板端 token 不满足处可在工具栏区域调整，板端框内保持原色）。
- R9. README 增加 Board Simulator 章节：打开方式、模式说明、默认连接、安全注意、与板端 C 工程的关系（复刻基准 + 同步提示）。

## Acceptance Criteria

- [ ] AC1. `file://` 打开零报错；mock 离线可用；板端框保持 480×272 比例并随窗口等比缩放。
- [ ] AC2. 六个页面元素与 C 版源码对应（逐页核对：标题、字段、按钮、toast、返回）；导航/返回栈行为一致。
- [ ] AC3. 六场景切换正确改变状态栏/设备卡/告警/诊断可用性；首页筛选（全部/告警/离线/正常）生效。
- [ ] AC4. 真实模式：点击 AI 诊断收到真实 `processing` 与终态，`req_id` 一致；`source=mimo` 渲染 OK 页，`source=fallback` 渲染降级提示，`error` 渲染错误 + 重试可用。
- [ ] AC5. 请求契约：`payload_hash` 与 `build_request` 逐字节一致；`context` 含 event/history/rules/device 且结构合法。
- [ ] AC6. 断连/连接失败/发布失败就地报错不崩溃；可切 mock 继续；mock 诊断六场景可用。
- [ ] AC7. 单屏 16:9：1366×768 与 1920×1080 无页面级滚动；板端框与工具栏同屏可见。
- [ ] AC8. 设计：板端 token 一致（色板/圆角/间距）、零 em-dash、reduced-motion、对比度、empty/loading/error/connecting 状态齐全。
- [ ] AC9. README 说明齐全；后端回归 `pytest tests/unit tests/contract` 全绿；`node --check` 通过；hash 契约测试纳入现有测试（或等价验证）。

## Out of Scope

- 运行真实 C/LVGL 代码（WASM/Emscripten）
- 板端 UI 之外的硬件交互（真实触摸、按键、蜂鸣器）
- 非 `diagnosis` 的真实请求类型
- 生产 MQTTS/鉴权
- 修改板端 C 工程
