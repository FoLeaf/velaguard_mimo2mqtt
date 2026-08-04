# Implement plan: 合并板端模拟器与请求调试台

## Delivery shape

按“先收敛运行时，再迁移 UI，最后切换入口”的顺序执行。每一阶段都保持统一页面可从 file:// 打开，并优先保留 Mock 可用性。不要在 task.py start 前修改产品代码。

## Ordered checklist

### 1. 建立基线和迁移清单

- 记录当前 git 状态，确认只存在任务创建文件以及用户已有的 .trellis/.template-hashes.json、.reasonix/、.zcode/ 变更。
- 运行现有 board core contract、debug hash parity、单元测试和 board-sim mock smoke，记录基线结果。
- 列出 debug-console/app.js 中需要迁移的纯逻辑、DOM 逻辑和测试导出，确认迁移后没有遗漏场景或响应字段。

### 2. 收敛协议核心和调试 Mock

- 以 board-sim/board-core.js 的 canonical JSON、整数 token、SHA-256、UUID、request/envelope helper 作为统一页面的协议基础。
- 将 debug-console 的协议 Mock 场景、result 构造、processing/终态规则迁移到新的 board-sim/debug-core.js；保留六个调试响应场景及其既有 error_code、result、source、advisory_only 语义。
- 让 debug-core.js 和 board-core.js 支持浏览器全局与 Node CommonJS；补足直接 Node require 的最小测试入口。
- 删除 debug-console/app.js 中重复的 hash、parse、request helper，改为调用 BoardCore API；不改变 Python build_request parity。

### 3. 实现唯一 RequestService

- 新增 board-sim/request-service.js，集中维护 mode、mqtt client、connection status、pending Map、响应订阅和 60 秒 watchdog。
- 复用既有真实流程：先订阅 vg/{device_id}/ai/response/{req_id}，QoS 1 成功后发布 vg/{device_id}/ai/request，QoS 1 且 retain=false。
- 统一处理 processing、终态、非法 JSON、订阅失败、发布失败、连接断开、超时和模式切换；终态/失败必须清理 timer、pending 和临时订阅。
- Mock 分支通过同一事件接口发 processing 和终态；validation_error/conflict 保持无 processing 的现有行为。
- 事件携带 source、req_id、device_id、topic、normalized envelope 和安全 traffic payload，禁止记录 MQTT 密码。
- 为 service 增加可被浏览器 smoke hook 读取的连接数和 pending 数，方便验证同页只有一个 client。

### 4. 将调试台迁移到统一页面

- 在 board-sim/index.html 中加入 debug drawer、开关按钮和调试面板 markup；为所有调试元素使用 debug 前缀或唯一 ID。
- 将 debug-console 的请求编辑器、context 四段表单/JSON、预设、Mock 控制、请求预览、发送栏、响应 viewer、timeline、history、导入/导出和复制功能迁移到 board-sim/debug-panel.js。
- debug-panel.js 只负责 DOM 收集与渲染，通过 BoardCore 构造请求，通过 DebugCore 提供 Mock 场景，通过 RequestService 发送；不能直接创建 mqtt client。
- 合并 debug-console/styles.css 到 board-sim/styles.css 或新增 debug-panel.css，并隔离抽屉样式，避免覆盖板框内部样式。
- 抽屉默认关闭；打开时板端 stage 与调试抽屉使用固定视口双列布局，抽屉内滚动，发送区和顶部开关可用；1366×768 与 1920×1080 均不得产生页面级滚动。
- 顶部保留一套 real/Mock 切换、连接徽标和调试台开关；删除重复模式/连接状态来源。

### 5. 接入板端模型和共享事件

- 修改 board-sim/app.js，移除直接 MQTT client/pending 实现，改用 RequestService。
- 板端 AI 诊断继续从当前模型生成 context，并通过 BoardCore.buildRequest 发送，source 标记为 board，保持 board simulator note。
- RequestService processing/terminal/failure 事件更新当前板端诊断和 lastTerminal；调试 source 的事件仅在 device_id 匹配时更新模型，不强制改变页面路由。
- 将板端流量日志、调试台历史和响应 viewer 接到同一事件源，确保板端入口发起的请求能在调试台查看，调试台请求也能在板端状态中反映。
- 保持 window.__boardSim.getState 的既有字段，并增加 drawer、service/pending 或等价字段供 smoke 验证，不能删除已有自动化字段。

### 6. 切换兼容入口和静态资源

- 将 debug-console/index.html 改为 file:// 兼容页，提供相对跳转到 ../board-sim/index.html 和手动点击 fallback。
- 确认统一入口只加载 board-sim/vendor/mqtt.min.js；旧 debug-console vendor、旧 app.js、旧 styles.css 不再被任何入口引用，迁移完成后删除冗余文件或明确其仅为历史资产。
- 更新 vendor README（如保留）和页面 title/说明，避免 README 或 HTML 继续暗示存在两个独立功能页。

### 7. 更新测试和文档

- 更新 tests/contract/test_debug_console_hash_parity.py，使 hash parity 覆盖实际统一页面使用的 BoardCore/debug-core 模块；保留 board-core contract 测试并新增 debug Mock contract 覆盖。
- 扩展 board-sim/e2e_smoke.py：打开/关闭调试抽屉、Mock 请求发送、响应 processing/终态、历史/时间线、共享 client/pending、双分辨率无滚动和无 console/page error。
- 增加旧 debug-console/index.html 跳转 smoke，验证 file:// 下相对路径可达统一入口。
- 运行 node --check 覆盖所有新增/修改 JS；运行 pytest tests/contract -q 和完整 pytest -q。
- 合并 README 的 Debug console 与 Board simulator 章节，统一为一个入口，保留真实模式 broker、Mock 场景、hash parity 和开发安全说明。

## Validation commands

在实现阶段至少运行：

~~~powershell
node --check board-sim/board-core.js
node --check board-sim/debug-core.js
node --check board-sim/request-service.js
node --check board-sim/debug-panel.js
node --check board-sim/app.js
pytest tests/contract -q
pytest -q
python board-sim/e2e_smoke.py
~~~

若环境有 Playwright Chrome/Edge，再运行真实联调：

~~~powershell
python board-sim/e2e_smoke.py --real
~~~

真实联调失败不应阻塞 Mock、契约和布局验收，但必须记录 broker/bridge 不可用还是页面逻辑错误。

## Risky files and rollback points

| 风险点 | 影响 | 回滚点 |
|---|---|---|
| board-sim/app.js MQTT 重构 | 板端诊断和 smoke 可能失效 | 先保留旧函数副本，RequestService 通过适配层接入，确认测试后删除旧路径 |
| board-sim/index.html / styles.css 布局 | 480×272 板框缩放或页面滚动回归 | 抽屉 markup/CSS 独立提交，先用 closed 状态验证原板框 |
| debug-panel.js 迁移 | 请求编辑、JSON 校验、历史可能丢失 | 先逐段迁移并保留旧 debug-console 资源，契约和 e2e 通过后再清理 |
| 单一 MQTT client | 两个来源的 pending/事件边界错误 | 为每个 entry 保留 source 和 entry id，增加同页 client 数验证 |
| debug-console 兼容页 | file:// 相对跳转在不同浏览器行为差异 | 提供 meta/JS 跳转和可点击链接双重 fallback |
| 删除旧资源 | 旧书签或脚本引用失败 | 最后一阶段才删除，且保留兼容 index.html |

## Review gates before task start

- PRD 已完成 convergence pass，A 布局、统一入口、兼容页和共享 client 决策已记录，无 blocking open question。
- design.md 和 implement.md 已存在并与 PRD 的 AC1-AC6 一一对应。
- research/current-merge-state.md 已保存仓库证据、重复点、测试锚点和风险。
- 当前任务仍为 planning；只有用户在看到本规划摘要后明确批准实施，才运行 task.py start。
- 本项目按 Codex inline workflow 工作，因此 implement.jsonl/check.jsonl 不需要伪造代码条目；开始编码前需加载 trellis-before-dev，完成后需运行 trellis-check。
