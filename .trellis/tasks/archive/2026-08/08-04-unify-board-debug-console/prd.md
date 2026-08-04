# 合并板端模拟器与请求调试台

## Goal

将目前分开的 `board-sim/` 板端 HMI 模拟器与 `debug-console/` 请求调试台合并为一个可直接打开的开发页面。用户应能在同一页面中操作 480×272 板端 UI、切换 Mock/真实 MQTT 模式、编辑完整诊断请求、发送请求，并查看 processing/终态响应、时间线、请求历史和原始流量，不必在两个网页之间切换。

## User value

开发和联调板端 AI 诊断流程时，板端交互、请求构造和后端响应查看应处于同一个工作上下文中；这样既能保持板端体验验证，又能在需要时检查完整协议字段和响应细节。

## Confirmed facts from repository

- `board-sim/index.html:15-107` 是当前板端模拟器入口，包含 480×272 可缩放板框、状态栏、页面内容、Mock/真实模式切换、MQTT 连接配置、六个场景按钮、设备 ID 和流量日志。
- `board-sim/index.html:7-10` 加载 `styles.css`、`vendor/mqtt.min.js`、`board-core.js`、`app.js`；`board-sim/app.js` 负责板端页面渲染、模型交互、Mock/真实诊断发送和流量日志，并暴露 `window.__boardSim` 供 `board-sim/e2e_smoke.py` 使用。
- `debug-console/index.html:14-312` 是另一套独立入口，包含请求编辑器、MQTT 连接、基础请求字段、`context.event/history/rules/device` 表单/JSON 编辑、六个 Mock 场景、请求预览、响应树/JSON 查看器、时间线、导入/导出和最近 50 条历史。
- `debug-console/index.html:7-9` 加载自己的 `styles.css`、`vendor/mqtt.min.js` 和 `app.js`；`debug-console/app.js` 独立维护请求状态、MQTT 生命周期、Mock 响应、响应事件和历史。
- 两套实现存在重复协议基础设施：canonical JSON/整数保留与 SHA-256、MQTT 默认参数、连接/订阅/发布/超时逻辑和 Mock 诊断场景。合并时需要确定单一事实来源，避免继续让两个页面各自漂移。
- 现有契约测试覆盖两套哈希实现：`tests/contract/test_debug_console_hash_parity.py`、`tests/contract/test_board_sim_core.py`；板端浏览器烟测位于 `board-sim/e2e_smoke.py`，验证 `file://`、Mock、无页面级滚动、1366×768 与 1920×1080 布局，并可选做真实诊断。
- README 目前分别描述两个入口：`README.md:151-204` 的 Debug console 和 `README.md:206-269` 的 Board simulator。
- 当前工作区已有用户未提交变更：`.trellis/.template-hashes.json` 被修改，`.reasonix/` 与 `.zcode/` 为未跟踪目录；本任务不应覆盖或清理这些变更。

## Requirements

### Functional

- R1. 提供一个统一入口页面，可通过 `file://` 直接打开；Mock 模式仍完全离线可用，真实模式仍可配置 MQTT WebSocket。
- R2. 保留板端 HMI 的核心行为和视觉约束：480×272 等比缩放、home/device/trend/alarm/diagnosis/logs 页面、返回栈、状态栏、toast、六个场景、传感器/告警/日志 Mock 状态，以及从板端入口发起 AI 诊断。
- R3. 在同一页面中保留调试台能力：编辑 `device_id`、`req_id`、`created_ts_ms`、`type`、`payload_hash`，编辑四段 context 的表单/JSON，载入 Mock 预设，选择 Mock 场景和延迟，预览/导出请求 JSON。
- R4. 在同一页面中保留真实 MQTT 诊断能力：连接/断开、可配置 broker URL/client_id/用户名/密码、先订阅响应主题再发布请求、处理 processing 与终态响应、显示连接/发送/订阅/发布错误，并允许切换 Mock 继续演示。
- R5. 在同一页面中保留响应查看器能力：信封字段、result 树/JSON 双视图、复制完整 JSON、时间线、最近 50 条请求历史、导入请求 JSON、清空历史和原始 MQTT/Mock 流量。
- R6. 板端“AI 诊断”与调试台“发送请求”应使用一致的请求/响应状态和 MQTT 连接，避免同页出现两个互相独立的连接客户端或相互覆盖的 pending 请求；板端视图能够反映调试台发起的诊断结果，调试台能够显示板端发起的可追踪请求。
- R7. 合并后维护一套协议核心实现（至少 canonical JSON、哈希、MQTT 常量/连接与 Mock 契约），并保留现有 Python 合约测试和浏览器自动化入口的可验证性。
- R8. 更新 README，说明统一入口、页面内板端/调试功能的使用方式、真实/Mock 模式、默认 broker 与开发环境安全注意；旧 `debug-console/index.html` 按兼容页处理，不再保留第二套功能实现。

### Compatibility and quality

- R9. 不修改 AI Bridge、MQTT topic 契约、payload_hash 算法或 dev broker 行为。
- R10. 合并后的页面在 1366×768 与 1920×1080 下可完成主要操作；页面级滚动策略和内部面板滚动应明确且可测试，不应因新增调试能力破坏板框可用性。
- R11. 真实模式连接失败、发布失败、响应超时、非法 JSON 等错误必须就地展示，不黑屏、不抛出未处理异常；Mock 模式不依赖网络。

## Acceptance criteria

- [x] AC1. 用户只打开统一入口 `board-sim/index.html`，就能从板端 UI 进入诊断，也能编辑并发送完整诊断请求并查看响应详情。
- [x] AC2. 板端页面与原有 `board-sim/e2e_smoke.py` 的 Mock、场景、诊断和状态栏检查保持通过；`window.__boardSim` 或等价自动化接口继续可用。
- [x] AC3. 调试台原有六个 Mock 场景、processing/终态时序、非法 JSON 阻止发送、响应树/JSON、时间线、历史、导入/导出/复制能力在统一页面中可用。
- [x] AC4. 板端入口与调试台入口共享同一 MQTT 连接与请求事件流；同一页面不会因为双重客户端导致重复订阅、状态错乱或 pending 请求丢失。
- [x] AC5. 现有哈希 parity、board core contract 测试继续通过；统一页面在 1366×768 与 1920×1080 下无控制台错误，布局满足任务确定的滚动/可见性策略。
- [x] AC6. README 只把 `board-sim/index.html` 作为统一入口；`debug-console/index.html` 不再包含第二套功能实现，而是提供兼容跳转/说明。
- [x] AC7. 统一调试抽屉在桌面视口下提供更宽的内容列；流量日志、响应查看、时间线和请求历史拥有更大的可见区域并支持内部滚动，抽屉顶部提供始终可见的一键收起按钮。

## Out of scope

- 不修改后端 AI Bridge、Python MQTT 业务逻辑、MQTT topic 或协议字段。
- 不把板端 HMI 改造成产品级前端，不改变 LVGL 复刻的核心视觉和交互语义。
- 不引入 npm、构建链、CDN 或新的运行时服务；继续支持静态文件直接打开，除非后续设计明确证明必须例外。
- 不扩展到非 `diagnosis` 请求类型，不增加持久化数据库、用户登录或多人协作。

## Key decisions

- **主布局采用方案 A。** `board-sim/index.html` 是统一页面和主入口；板端模拟器保持主工作区，完整请求调试台放在右侧可展开的开发抽屉/侧栏中。
- **单一运行实例。** 合并后只保留一套页面状态、MQTT 客户端、pending 请求和诊断事件总线；板端入口与调试台入口都通过同一套请求服务发起和接收诊断。
- **兼容旧路径。** 为保持现有 README、自动化和用户书签可用，`debug-console/index.html` 保留为轻量兼容页，跳转或引导到 `board-sim/index.html`，不再维护第二套调试应用；`board-sim/index.html` 继续作为 `board-sim/e2e_smoke.py` 的目标路径。
- **静态运行约束不变。** 不引入构建步骤、npm、CDN 或后端服务；统一入口继续支持 `file://`，vendor 依赖只保留一份实际运行副本。

## Notes

- 当前任务仅处于 Trellis planning 状态；布局决策已确认；复杂任务所需的 `design.md`、`implement.md` 与研究记录已补齐；本项目采用 Codex inline workflow，`implement.jsonl` / `check.jsonl` 保持 Trellis 创建时的空上下文清单。实现、契约测试、浏览器 Mock 烟测、双分辨率布局检查和一次真实 MQTT 联调均已通过。
