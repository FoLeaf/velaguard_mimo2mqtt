# Design: 合并板端模拟器与请求调试台

## Summary

统一入口使用 board-sim/index.html。板端 HMI 保持主工作区和 480×272 复刻基准，完整请求调试台放入右侧可展开抽屉。页面只初始化一个运行时状态、一个 MQTT 客户端和一个诊断请求事件流；板端视图和调试台视图订阅同一事件流，各自负责渲染自己的内容。

debug-console/index.html 改为轻量兼容页，跳转到统一入口，不再加载第二套应用。统一入口继续支持 file://，不引入构建工具或服务端依赖。

## Architecture

~~~text
board-sim/index.html
  ├─ board frame                       # 480×272 HMI 主工作区
  ├─ debug drawer                      # 可展开调试台，内部滚动
  │   ├─ board controls                # 场景、device_id、流量日志
  │   ├─ request editor                # 基础字段、context、Mock 预设
  │   └─ response viewer               # envelope、result、timeline、history
  └─ global topbar                     # real/mock、连接徽标、调试台开关

board-sim/board-core.js                # 板端模型 + canonical JSON/hash + request helpers
board-sim/debug-core.js                # 调试 Mock 场景和 envelope 生成，纯逻辑，可 Node require
board-sim/request-service.js           # 唯一 MQTT/Mock 发送服务和请求事件总线
board-sim/debug-panel.js               # 调试抽屉 DOM 控制器和编辑/查看逻辑
board-sim/app.js                       # 页面路由、板端渲染、统一状态编排
board-sim/styles.css                   # 板端 token、布局和调试抽屉样式
board-sim/debug-panel.css              # 调试抽屉的局部样式，可被 styles.css 引入或由 index 加载
~~~

依赖方向保持单向：

~~~text
app.js ───────────────┐
                      ├─ request-service.js ── BoardCore + DebugCore + mqtt.js
 debug-panel.js ──────┘
app.js ──────────────── BoardCore
 debug-panel.js ────── BoardCore + DebugCore
~~~

request-service.js 不直接操作 DOM。debug-panel.js 不直接调用 mqtt.js。board-core.js 与 debug-core.js 保持浏览器全局 + CommonJS 双用，便于现有 Node 合约测试继续执行。

## Runtime ownership

| 能力 | 唯一归属 | 说明 |
|---|---|---|
| Board model、页面路由、板框渲染 | app.js + BoardCore | 保持现有 HMI 语义，诊断状态由请求事件更新 |
| canonical JSON、整数 token、SHA-256、UUID、请求构造 | BoardCore | 调试台移除重复实现，通过 window.BoardCore 调用 |
| 调试 Mock 场景 | DebugCore | 保留调试台协议场景，不与板端六个状态场景混用 |
| MQTT 连接、订阅、发布、超时、pending | RequestService | 页面只存在一个 client 和一个 pending Map |
| 请求编辑和响应查看 | DebugPanel | 只收集/渲染数据，通过 RequestService 发送 |
| 流量、历史、连接徽标 | 统一状态编排 | 板端工具区与调试抽屉观察同一数据，不重复记录 |

## Request service contract

RequestService 提供以下接口，具体命名可在实现阶段微调，但语义必须保持：

~~~js
const service = createRequestService({ core, debugCore, mqttLib, onEvent });
service.setMode("real" | "mock");
service.connect({ url, clientId, username, password });
service.disconnect(reason);
service.send({
  source: "board" | "debug",
  request: { body, full, payload_hash, payload },
  mockScenario,
  delayMs,
});
service.on("event", handler);
~~~

统一事件至少包含：

- connection：status、message、broker URL，不含密码。
- request：source、req_id、device_id、request topic、response topic、完整请求、hash。
- note：source、req_id、说明文本。
- response：source、req_id、topic、normalized envelope、kind（processing/terminal）。
- failure：source、req_id、error_code、error_message、是否超时。
- traffic：可安全展示的真实或 Mock 消息；密码不得进入 payload 或日志。

真实发送顺序保持不变：

~~~text
send(request)
  → 记录 entry 和 pending
  → subscribe vg/{device_id}/ai/response/{req_id}, QoS 1
  → subscribe 成功后 publish vg/{device_id}/ai/request, QoS 1, retain=false
  → 处理 processing / terminal
  → terminal 或失败后清理 timer、pending 和 response subscription
~~~

Mock 发送通过同一事件接口模拟时序。成功、fallback、provider_error、timeout、validation_error、conflict 的状态和是否产生 processing 必须与现有调试台语义一致。

## Board and debug data flow

~~~text
板端 AI 诊断
  → BoardCore.buildDiagnosisContext(model)
  → BoardCore.buildRequest({ source note: "board simulator" })
  → RequestService.send(source="board")

调试台发送
  → DebugPanel.collectRequest()
  → BoardCore.buildRequest({ source note: "synthetic publisher" })
  → RequestService.send(source="debug")

RequestService events
  ├─ app.js: 当前设备/诊断页匹配时更新 BoardCore diagnosis 和 lastTerminal
  ├─ DebugPanel: 创建/更新 history entry、viewer、timeline
  └─ unified traffic renderer: 更新流量日志
~~~

板端收到调试台请求的终态时，不强制跳转页面；当 device_id 与当前板端设备匹配时更新诊断结果和 lastTerminal，当前页面为诊断页则刷新内容，否则显示非侵入式 toast/状态提示。这样不会因调试台发送请求破坏板端用户正在浏览的页面。

## Layout and interaction

- 顶部保留一个全局 real/Mock 切换和连接徽标，删除调试台内部的第二套模式切换；模式切换会取消不适用的 pending 操作，并同步更新板端和调试抽屉。
- 顶部新增“打开调试台/关闭调试台”按钮，使用 aria-expanded 和可见状态；调试台默认关闭，以板端复刻为首屏焦点。
- 抽屉打开时采用 CSS Grid：左侧为板端 stage，右侧为调试抽屉；抽屉内部各区段独立滚动，页面根元素保持 scrollHeight <= innerHeight。
- 抽屉内按顺序放置“板端控制”“请求编辑器”“响应查看器”“时间线/历史”“流量日志”。发送操作在请求编辑器底部保持可见，响应和历史使用内部滚动。
- 调试 DOM 使用明确的 debug- 前缀或统一唯一 ID，避免与板端既有 content、toast、conn-status、f-device-id 等选择器冲突。
- 继承板端暗色 token 和调试台的 mono 数据展示；板框内部样式不被抽屉样式覆盖；加入 reduced-motion 和完整 empty/loading/error/connecting 状态。

## Compatibility and migration

- board-sim/index.html 保持现有 smoke test URL。
- debug-console/index.html 替换为包含相对跳转、可点击 fallback 链接和统一页面说明的静态兼容页，确保直接双击仍可到达新页面。
- 将调试台需要的纯逻辑迁移到 board-sim/debug-core.js，将 DOM 逻辑迁移到 board-sim/debug-panel.js；统一页面只加载一套 mqtt vendor。
- 删除或停止加载 debug-console/app.js、debug-console/styles.css 和重复 mqtt vendor。若保留物理文件仅为迁移阶段需要，最终验收前不得被任何入口引用。
- 更新 tests/contract/test_debug_console_hash_parity.py 的 Node 目标，使其验证统一页面实际加载的协议核心，而不是已停用的旧应用文件。
- 更新 README 为统一入口说明，并保留旧路径兼容说明、真实/Mock、安全、hash parity 和 board simulator 参考关系。

## Important trade-offs

1. **板端主视图优先。** A 方案保留板端复刻的核心体验，但请求编辑器在抽屉内空间更紧，需要内部滚动和固定发送区。
2. **单一 MQTT client。** 共享服务降低状态漂移和重复连接风险，但会要求板端和调试台接受统一的连接错误和 pending 清理语义。
3. **保留两套场景语义。** 板端场景驱动传感器/HMI，调试场景驱动协议响应；合并名称和状态会让测试与用户理解变差，因此在 UI 中分组展示。
4. **旧入口变兼容页。** 这样不会继续维护两套应用，但旧路径不再拥有独立页面状态，用户需要接受它跳转到统一入口。

## Rollback and operational safety

- 所有改动限定在静态前端、测试和 README，不触碰 AI Bridge、broker 配置或 MQTT 契约。
- 分阶段提交时，先保留旧目录文件，待统一入口与 smoke/contract 测试通过后再删除旧实现资产。
- 若抽屉布局或共享 service 出现问题，可先恢复 debug-console/index.html 及其旧资源作为临时入口；BoardCore 和后端协议不受影响。
- Mock 模式必须在每一阶段保持可用，真实 broker 不可用不能阻塞本地验证。

## Verification mapping

- AC1、AC3、AC4：统一页面 smoke/e2e，覆盖打开抽屉、编辑 context、Mock 发送、板端入口发送、共享 history/traffic。
- AC2：扩展 board-sim/e2e_smoke.py，保留现有选择器和 window.__boardSim 兼容。
- AC5：Node --check、现有 Python contract tests、双分辨率控制台错误和滚动检查。
- AC6：README 检查统一入口和兼容页行为。
