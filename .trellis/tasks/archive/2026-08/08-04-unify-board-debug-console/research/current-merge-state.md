# 合并现状与约束研究

## 研究范围

本研究只检查仓库内现有两个静态页面、其浏览器逻辑、契约测试、烟测和 README，不引入外部依赖或后端改动。

## 当前入口职责

| 路径 | 当前职责 | 关键依赖 |
|---|---|---|
| `board-sim/index.html` | 480×272 板端 HMI、场景切换、板端诊断入口、MQTT 连接和原始流量 | `board-sim/styles.css`、`board-sim/board-core.js`、`board-sim/app.js`、本地 mqtt.js |
| `debug-console/index.html` | 请求字段/context 编辑、Mock 场景、请求预览、响应查看、时间线、历史、MQTT 连接 | `debug-console/styles.css`、`debug-console/app.js`、本地 mqtt.js |

`board-sim/index.html:30-107` 将板框和开发工具栏放在同一布局中；`debug-console/index.html:25-312` 以请求编辑器和响应查看器组成双面板布局。两者均为无构建静态页面，可从 `file://` 打开。

## 重复和冲突点

1. **协议核心重复。** `board-sim/board-core.js` 和 `debug-console/app.js` 都包含 canonical JSON、整数 token 保留、SHA-256、payload_hash 和 UUID 逻辑。board core 已将这些能力导出到 Node/CommonJS 与浏览器 `window.BoardCore`。
2. **MQTT 客户端重复。** `board-sim/app.js:37-52` 和 `debug-console/app.js:2011-2027` 各自维护 client、连接状态和 pending Map；两套连接不能在同一页面并行运行，否则会出现重复订阅和状态互相覆盖。
3. **诊断事件重复。** 板端通过 `state.mqtt.pending`、`pushTraffic`、`applyResultToDiagnosis` 处理请求；调试台通过 history entry、timeline event 和 viewer 处理同一类 processing/terminal envelope，合并后需要统一事件流再分别渲染。
4. **Mock 场景语义不同。** 板端场景是 `normal/warn/crit/offline/ai_down/ota`，用于驱动 HMI 模型；调试台场景是协议响应场景（MiMo success、fallback、provider error、timeout、validation/conflict 等）。统一页面应保留两套语义，但不能用同一个 select 或同一个状态字段覆盖彼此。
5. **请求来源不同。** 板端请求由 `BoardCore.buildDiagnosisContext(model)` 自动生成 context；调试台请求由四段表单/JSON 编辑器收集。共享发送服务必须接受“来源 + 已构造 request”而不是强行使用单一 context 来源。

## 现有验证锚点

- `tests/contract/test_debug_console_hash_parity.py` 通过 Node require 加载 `debug-console/app.js` 和 `board-sim/board-core.js`，与 Python `build_request` 比较 canonical JSON 和 SHA-256。
- `tests/contract/test_board_sim_core.py` 直接 require board core，覆盖 context shape、v2 result mapping、Mock diagnosis 和真实 request。
- `board-sim/e2e_smoke.py:21-107` 固定打开 `board-sim/index.html`，覆盖 Mock 场景、板端诊断、双分辨率页面级滚动和可选真实诊断，并依赖 `window.__boardSim`。
- `README.md:151-269` 当前分别说明两个入口，合并后必须改为统一入口说明，并保留真实/Mock、安全及 hash parity 信息。

## 设计结论

- 统一运行入口选择 `board-sim/index.html`，以板端主工作区为视觉锚点；调试台放入可展开右侧抽屉，抽屉内部滚动，页面本身仍保持固定视口。
- 将通用协议和 MQTT 生命周期收敛到 board-sim 统一运行时；调试面板只负责编辑/渲染，板端页面只负责板端模型/渲染，二者通过请求服务事件总线连接。
- `debug-console/index.html` 变为兼容跳转/说明页，不再加载第二套应用；旧测试中的 Node 导入目标需要切换到统一后的协议核心模块或 board core。
- 真实 MQTT 的订阅顺序、QoS、topic、60 秒超时、processing/终态和错误语义必须保持原实现与后端契约不变；Mock 也应通过同一事件接口，以便两个视图观察一致。

## 风险

- 将完整调试台塞入板端页面可能造成 CSS 选择器和全局 ID 冲突；调试 DOM 应使用明确的 `debug-` 命名空间，或统一只保留一套 ID。
- 板端原有“诊断页自动请求”与调试台手动请求的生命周期不同；请求服务必须带来源和 entry id，板端只把匹配当前设备/当前诊断的事件应用到模型，避免误更新。
- file:// 下的兼容跳转、脚本相对路径和 clipboard API 行为需要在浏览器烟测中实际验证。
