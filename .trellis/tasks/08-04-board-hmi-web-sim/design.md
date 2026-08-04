# Design: VelaGuard board HMI web simulator

## Summary

在 `board-sim/` 构建一个静态、零构建的 Web 复刻：左侧 480×272 板端框（home/device/trend/alarm/diagnosis/logs 六页，模拟 `main/ui/` 的 shell/model/pages/widgets），右侧开发工具栏（场景切换、真实/Mock 切换、连接面板、原始流量日志）。真实模式复用已验证的 MQTT-over-WebSocket 通道（vendored mqtt.js）与 v1/v2 契约，AI 诊断从复刻模型构建 context 并走真实 AI Bridge。

## Architecture

```text
board-sim/
  index.html        # 单页：板端框 + 工具栏 + 流量日志抽屉
  styles.css        # 板端 token CSS 变量 + 布局（100dvh 网格）
  app.js            # UI 渲染 + 事件 + 页面路由 + 工具栏
  board-core.js     # 纯逻辑：model（场景/传感器/告警/日志）、canonical JSON + SHA-256、
                    #         context builder、诊断结果映射、mock 诊断引擎（浏览器 + Node 双用）
  vendor/mqtt.min.js  # mqtt@5.15.2（从 debug-console/vendor 复制，保持自包含）
```

分层：

- `board-core.js`：不触碰 DOM。镜像 `vg_model` 语义（scenario、sensors、alarms、net、diagnosis、logs、history）；暴露 `buildDiagnosisContext(model)`、`mapResultToDiagnosis(result)`、`runMockDiagnosis(scenario)`、`canonicalStringify`/`payloadHash`（复用 `debug-console` 已验证算法，复制为单一实现并注明来源）。
- `app.js`：状态 → 页面渲染；导航栈（home/device/trend/alarm/diagnosis/logs + 返回）；toast；场景切换；MQTT 生命周期（connect/subscribe/publish/watchdog/断连恢复）。
- `styles.css`：CSS 变量严格映射板端 token；板端框内只使用板端 token；工具栏可用同色系但允许更高对比度。

依赖方向：`app.js` → `board-core.js`；`board-core.js` 无依赖（浏览器全局 + CommonJS 导出，供 node 测试）。

## Board frame spec（复刻基准）

| 项目 | 值（来自 C 工程） |
|---|---|
| 分辨率 | 480×272（CSS 像素，可等比缩放） |
| 状态栏 | 高 28px；字段 NET/MiMo/采集/音频/OTA + 时间，右侧状态色点 |
| 页面 padding / gap | 6px / 4px |
| 卡片 | surface 底、border 1px、圆角 4px、pad 6px |
| 触摸目标 | ≥36px 高、≥40px 宽；列表行 40px |
| 颜色 | bg #1A1D21、surface #24292E、border #3A424A、text #E8ECF0、muted #9AA3AD、ok #2F9E44、warn #F0A202、crit #E03131、offline #6C757D、info/accent #1C7ED6 |
| 风险徽标 | low→ok 色、medium→warn 色、high→crit 色；chip 底色 30% 透明度 + 同色边框文字 |
| 字体 | 中文使用系统 CJK 栈（`"Microsoft YaHei", "PingFang SC", sans-serif`）；数字/指标用 `ui-monospace, "Cascadia Mono", monospace` |

页面清单（实现时逐页对照 `main/ui/pages/*.c`）：

- home：状态栏 + 筛选 chip（全部/告警/离线/正常）+ 可滚动传感器列表（设备行）+ 告警摘要条 + 快捷操作（详情/诊断/添加传感器）；以当前 `vg_page_home.c` 源码为准。
- device：选中传感器详情（值、单位、阈值 warn/crit/low、寄存器、周期、质量、在线状态、历史摘要）。
- trend：最近 60 点曲线 + 阈值线（warn/crit）。
- alarm：活动告警列表/详情（severity/title/value/threshold/duration/acked/muted）+ 确认/静音按钮（mock）。
- diagnosis：LOADING（spinner+文字）→ OK（summary/风险徽标/置信/原因≤3/建议≤3/降级提示）或 ERROR（error_msg + 重试）。
- logs：五类日志列表（alarm/diag/sys/ota/ui，时间+文本）。

## Model mapping（JS ↔ C）

`board-core.js` 的数据结构与 `vg_model.h` 对应：

- `scenario`: normal | warn | crit | offline | ai_down | ota
- `sensors[]`: id/name/unit/value/thr_warn/thr_crit/thr_low/severity/age_sec/period_ms/reg_addr/quality_pct/online/history[60]
- `alarms[]`: active/severity/title/sensor_id/value/threshold/duration_sec/acked/muted
- `net`: net_ok/mimo_ok/acq_ok/aud_ok/ota_active/ip/latency_ms
- `diagnosis`: state(idle/loading/ok/error)/summary/risk/causes[3]/actions[3]/confidence_pct/error_msg/alarm_title
- `logs[]`: type(alarm/diag/sys/ota/ui)/severity/time/text

场景默认数据从 `vg_model.c` 的初始值/`set_scenario` 行为推导（实现时读源文件核对数值与文案）。

## Real diagnosis flow

```text
用户点击 AI 诊断（真实模式）
  → 连接（未连接则自动连接；失败→内联错误）
  → req_id = UUID；context = buildDiagnosisContext(model)
      context.event    ← 活动告警（title/severity/current_value/rule/threshold/ts_ms）
      context.history  ← 选中传感器最近 ≤50 点 {ts_ms, values}
      context.rules    ← 传感器阈值生成 ≤20 条 {rule_id, expr, severity, message}
      context.device   ← 选中传感器 {name, model, description(静态模板)}
  → 先订阅 vg/{device_id}/ai/response/{req_id}（QoS 1）
  → 发布 vg/{device_id}/ai/request（QoS 1, retain=false, payload_hash 自动计算）
  → 60s watchdog；收到 processing → 诊断页 LOADING
  → 收到终态：
      success + source=mimo      → OK 页（映射 v2 字段）
      success + source=fallback  → OK 页 + 降级提示（advisory_only/fallback_reason）
      error                       → ERROR 页（error_code/error_message）+ 重试
  → 断连/错误/离线 → 取消 pending 并标记“已中断”，恢复 UI 可切 mock
```

`mapResultToDiagnosis(result)` 映射：

| v2 result | 诊断页 |
|---|---|
| `diagnosis_summary` | summary（≤128 字符，超长截断） |
| `risk_level` | risk 徽标（low/medium/high） |
| `possible_causes[0..2]` | causes（最多 3 条） |
| `recommended_actions[0..2]` | actions（最多 3 条） |
| `confidence` | confidence_pct = round(confidence*100) |
| `source=fallback` | 页面顶部降级提示（advisory_only + fallback_reason） |
| `need_shutdown` | 高亮提示（不在 C 版字段中则记入日志） |

## Contract fidelity

- `payload_hash`/canonical JSON：从 `debug-console` 复制已验证实现（递归排序键、`,`/`:`、int/float 区分、SHA-256 over UTF-8、排除 hash 自身）；`board-core.js` 内单一实现，README 注明与 `synthetic_publisher` 的关系。
- context 结构：`event`/`history`/`rules`/`device` 全部为可选但真实诊断总是提供（缺数据时省略对应段，不构造非法结构）。
- 信封/错误码/v2 字段/fallback 语义：与 `mqtt-ai-bridge-contracts.md` 一致；`validation_error`/`conflict` 由真实 bridge 返回（本页只展示）。

## Toolbar（不进板端框）

- 场景切换：6 个按钮（正常/预警/严重/离线/MiMo 不可用/OTA 中），等价 C 版数字键 1-6。
- 模式切换：真实 / Mock（默认真实）。
- 连接面板：broker URL（默认 `ws://107.174.123.74:9001`）、client_id、可选用户名/密码、连接/断开、状态徽标（connecting/connected/error/disconnected）。
- 流量日志：折叠面板，记录每次真实请求/响应 JSON（时间 + topic），清空按钮；mock 模式记录模拟消息。
- device_id 输入（默认 `dev01`），供真实发布使用。

## Layout

```text
┌────────────────────────────────────────────────────────┐
│ header: 标题 + 模式切换 + 连接状态 + 场景按钮            │
├──────────────────────────────┬─────────────────────────┤
│ 板端框 480×272（等比缩放居中）│ 工具栏：连接面板          │
│   页面内容可点击             │ device_id/模式           │
│                              │ 流量日志（可折叠）        │
└──────────────────────────────┴─────────────────────────┘
```

页面 `height:100dvh`（body `100dvh` + `100%` 兜底），CSS Grid 两列；板端框与工具栏内部各自滚动；页面级不滚动。板端框用 `transform: scale()` 或 `zoom` 等比适配可用空间（480×272 保持比例）。

## Observability & errors

- 所有真实模式错误（连接失败、订阅失败、发布失败、watchdog 超时、断连）渲染为内联状态 + toast，不崩溃。
- 日志记录：`mqtt_*`、`diagnosis_req`（req_id/hash）、`diagnosis_terminal`（status/source/error_code）不带密钥。
- 不打印/不记录 broker 密码；密码字段不回显。

## Compatibility & rollout

- `board-sim/` 与 `debug-console/` 完全独立，互不影响；共享契约与 vendored mqtt.js 版本（注明同步来源）。
- Mock 模式默认可用 → 真实模式是增量；回滚 = 使用 mock 或还原 `board-sim/`。
- 服务器侧无需改动（9001 已部署）。

## Explicit Non-Goals

- 不编译/不运行 C 代码（无 WASM）。
- 不改板端 C 工程、不改后端/契约。
- 不做 add_sensor/system/ota 页面真实功能（入口 toast 即可，与 C 版一致）。
- 不做生产鉴权。
