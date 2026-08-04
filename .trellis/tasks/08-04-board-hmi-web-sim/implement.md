# Implement: VelaGuard board HMI web simulator

## Execution Plan

Phase 1: 骨架与模型（board-sim/ 结构、board-core.js 模型/场景/日志、canonical hash 复制）
Phase 2: 页面复刻（home/device/trend/alarm/diagnosis/logs + shell/toast/返回栈，逐页对照 C 源码）
Phase 3: 真实诊断流（MQTT 连接面板、context builder、subscribe→publish→渲染、watchdog/断连恢复）
Phase 4: 工具栏与布局（场景按钮、模式切换、流量日志、16:9 单屏）
Phase 5: 验证与文档（node 契约测试、headless E2E、README、后端回归）

## Reference sources（复刻基准，只读）

- `D:/Study/Embeded/Velaguard/GUI/main/ui/pages/vg_page_*.c`（页面结构与文案）
- `D:/Study/Embeded/Velaguard/GUI/main/ui/shell/vg_shell.c`（状态栏/返回栈/toast）
- `D:/Study/Embeded/Velaguard/GUI/main/ui/model/vg_model.c`（场景/传感器/告警/诊断/日志初始值与行为）
- `D:/Study/Embeded/Velaguard/GUI/main/ui/theme/vg_theme.c`、`main/inc/vg_display.h`（token/布局常量）
- `D:/Study/Embeded/Velaguard/GUI/bin/qa/*.png`（视觉参考）
- 本仓库 `debug-console/`（mqtt.min.js、canonical hash、契约 mock 的可复用实现）

## Ordered Checklist

1. **骨架**
   - `board-sim/index.html`、`styles.css`、`app.js`、`board-core.js`、`vendor/mqtt.min.js`（从 `debug-console/vendor` 复制）+ `vendor/README.md`（注明来源与版本）

2. **board-core.js（纯逻辑，浏览器+Node 双用）**
   - 模型：scenario/sensors/alarms/net/diagnosis/logs/history，镜像 `vg_model.h` 字段与默认值（读 `vg_model.c` 核对）
   - 场景切换行为（normal/warn/crit/offline/ai_down/ota）与首页筛选（all/alarm/offline/ok）
   - canonical JSON + SHA-256（复制自 debug-console，保持单一实现）；`buildRequest(body)` 自动算 `payload_hash`
   - `buildDiagnosisContext(model)`：event/history(≤50)/rules(≤20)/device
   - `mapResultToDiagnosis(result)`：v2 → 诊断页字段（含 fallback 降级标记）
   - `runMockDiagnosis(scenario)`：LOADING → OK/ERROR 预设（与 C 版一致）
   - `appendLog` / 历史管理

3. **页面复刻（app.js 渲染）**
   - shell：状态栏（NET/MiMo/采集/音频/OTA/时间/IP/延迟）、content host、返回栈、toast
   - home：设备卡/瓷砖（2×2）、告警摘要、快捷操作、筛选 chip
   - device：详情指标行（值/单位/阈值/寄存器/周期/质量/在线）
   - trend：60 点曲线 + warn/crit 阈值线（Canvas 或 SVG，轻量）
   - alarm：列表/详情 + 确认/静音（mock）
   - diagnosis：LOADING/OK/ERROR + 重试 + 降级提示
   - logs：五类日志列表
   - add_sensor/system/ota 入口：toast「后续版本」（与 C 版一致）
   - 导航、返回、toast 行为与 `vg_shell`/`vg_nav_*` 一致；触控热区 ≥36px 等效

4. **真实诊断流**
   - 连接面板：broker URL（默认 `ws://107.174.123.74:9001`）、client_id、可选账号密码、连接/断开、状态徽标
   - 发送：`req_id` UUID → 订阅响应 topic（QoS 1）→ 发布请求（QoS 1, retain=false）→ 60s watchdog
   - 渲染：processing → LOADING；success+mimo → OK；success+fallback → OK+降级提示；error → ERROR+重试
   - 断连/错误/离线 → 取消 pending、标记中断、恢复 UI、可切 mock（复用 debug-console 的恢复模式）

5. **工具栏与布局**
   - 场景按钮（6 个）、真实/Mock 切换、device_id 输入、流量日志折叠面板（真实与 mock 都记录）
   - 16:9 单屏：`height:100dvh`（+`100%` 兜底）、CSS Grid、板端框等比缩放、面板内部滚动、页面级不滚动

6. **文档**
   - README 增加 Board Simulator 章节：打开方式、模式说明、默认连接、安全注意、与板端 C 工程关系

## Validation Commands

```bash
node --check board-sim/app.js board-sim/board-core.js
# hash 契约（与 debug-console 同算法）：node 侧 buildRequest 与 Python build_request 对比
pytest tests/unit tests/contract -q          # 后端回归（159+）

# headless Chrome/Edge over file://：
# 1) mock：六场景、六页导航、toast/返回、筛选
# 2) 真实：连接 ws://107.174.123.74:9001 → 点 AI 诊断 → processing + 终态（mimo/fallback）→ req_id 一致
# 3) 1366×768 / 1920×1080：document.documentElement.scrollHeight <= innerHeight
```

## Rollback Points

- Mock 模式默认可用 → 真实模式失败不影响演示。
- `board-sim/` 独立目录，回滚 = 删除/还原该目录；不改后端与板端 C 工程。
- 服务器侧无需改动（9001 已部署）。

## Quality Gates Before `task.py start`

- PRD AC1-AC9 均有对应实现/测试路径
- `node --check` 通过；hash 契约测试纳入 `tests/contract`（或等价可重复验证）
- headless E2E：mock 全场景 + 真实诊断一发（记录 req_id/status/source）
- 单屏 16:9 双分辨率验证；零 em-dash；设计 token 与 C 版一致
- `implement.jsonl` / `check.jsonl` 已收录真实 spec 条目

## Sub-agent Notes

- 实施前加载 `trellis-before-dev`；实施后 `trellis-check`
- 复刻必须逐页对照 C 源码（页面字段/文案/交互），不能凭截图猜
- `board-core.js` 保持纯逻辑可 node 测试；mqtt.min.js 只经 script 标签在浏览器使用
