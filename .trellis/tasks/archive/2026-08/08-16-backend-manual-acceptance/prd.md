# Backend acceptance against project manual

## Goal

对照 `VelaGuard_项目手册.md` 验收后端 AI Bridge（`ai_bridge/`），把验收发现的差距转化为可验收的修复或记录决策，使后端与手册第 8/16 章的后端侧契约一致（或明确记录有意的偏差）。

验收基线：2026-08-16 工作区（main @ 50e1ac2 + 未提交的 docs/backend-api.md）。

## 验收结论（2026-08-16）

后端核心链路（MQTT 请求/响应、诊断、幂等、超时、降级、密钥安全）与手册一致。符合项证据：

| 手册条款 | 要求 | 实现证据 | 结论 |
|---|---|---|---|
| §16.2 | VelaGuard→Broker→Bridge→HTTPS MiMo 链路，Bridge 为 Broker 独立客户端 | `transport/mqtt/client.py` + `providers/mimo.py` | 符合 |
| §16.2 | ai/request、ai/response QoS 1；请求/响应不 retained | `contracts/topics.py` `AI_QOS=1` `AI_RETAIN=False` | 符合 |
| §16.2 | clean_session=true；重连后重新订阅 | `client.py` `clean_session=True`，`_handle_connect` 内 subscribe | 符合 |
| §16.4 | 必填字段 req_id/device_id/created_ts_ms/type/payload_hash；topic 与 payload device_id 一致 | `contracts/request.py` | 符合 |
| §16.4 | 幂等键 req_id+payload_hash；处理中→processing；已完成→重发同一响应；同 req_id 异 hash→拒绝 | `persistence/idempotency.py` + `application/handle_request.py` | 符合 |
| §16.3 | req_id 原样带回；云端另存 received_ts_ms | `contracts/envelope.py` | 符合 |
| §16.4 | MQTT 只承载控制 JSON/小结果 | `request.py` 64KB 上限 | 符合 |
| §12.3 | AI 输出非法→拒绝应用（error），绝不作为 success 发布 | `providers/schema.py` | 符合 |
| §11.2 | API Key 不入日志/payload | `observability/logging.py` 脱敏 + `tests/unit/test_redaction.py` | 符合 |
| §5.7 | 诊断输入含事件/历史/规则/设备说明 | `runtime/prompt_builder.py` context 归一化 | 部分符合（见 G5） |
| §10.1 | 诊断 Skill 文件 + JSON 输出 | `ai_bridge/skills/industrial_fault_diagnosis.md` | 符合（命名见 G3） |

## 差距清单（转需求）

- **G1 调用类型只有诊断**：手册 §8.4 要求后端支持自然语言配置生成、手册解析、巡检报告、TTS 五类 MiMo 调用；`contracts/request.py` `SUPPORTED_TYPES={"diagnosis"}` 仅一类。
- **G2 配置生成 Skill 缺失**：手册 §10.2 要求 `sensor_config_generator.md`；`ai_bridge/skills/` 只有诊断 skill。
- **G3 诊断输出字段命名不一致**：手册 §5.7/§10.1 输出字段为 `summary`；实现/测试/board-sim/docs 全线使用 `diagnosis_summary`（v2 schema）。需要决策：改实现回 `summary`，或修订手册采纳 `diagnosis_summary`。
- **G4 无 MQTTS/TLS 支持**：手册 §16.2 正式环境要求 MQTT over TLS；`transport/mqtt/client.py` 与 `configuration/settings.py` 无任何 TLS/CA 配置项，仅明文 1883 形态。
- **G5 诊断输入缺两段上下文**：手册 §5.7 列出「传感器配置（寄存器表）」与「用户手册摘要」；当前 `context` 仅 event/history/rules/device。
- **G6 失败幂等策略偏差**：手册 §16.4「已失败：按失败类型决定是否允许重试」；实现统一重放存储的错误响应（`idempotency.py` FAILED 也走 Completed 重放），不允许按类型重试。
- **G7 幂等存储进程内、重启丢失**：README 已声明 disposable；手册未强制持久化，但 §16.4 幂等语义在生产重启后会失效，需作为已知限制记录（或升级为持久化需求）。
- **G8 分类型超时未实现**：手册 §16.4 按任务类型给超时建议（自然语言配置 15-30s、手册解析 60-180s）；当前单一 `REQUEST_TIMEOUT_MS`。依赖 G1。

范围说明：LWT/status、设备 token HMAC/轮换、Broker ACL、OTA/voice/tts topic 族属设备端与部署侧职责，不计入后端 Bridge 差距。

## Requirements

- R1（G3，已决策 2026-08-16）：**修订手册采纳 `diagnosis_summary`**。保留现有线上契约不动，修改手册 §5.7/§10.1 的输出 JSON 命名，并注明 bridge 附加字段（`source`/`advisory_only`/`fallback_reason`）。代码、测试、board-sim 不改。
- R2（G4）：Bridge 增加 MQTTS 连接能力（`MQTT_TLS` 开关 + 可选 CA/客户端证书 env 配置），默认行为不变（明文 dev 姿态可用）。
- R3（G1+G2+G8，已决策 2026-08-16）：**拆分为后续任务**，本任务不实现 `type=sensor_config`；在 docs/backend-api.md 与 README 记录为路线图项（自然语言配置生成、手册解析、巡检报告、TTS、分类型超时）。
- R4（G5）：诊断 `context` 增加可选 `sensor_config`（对象）、`manual_summary`（字符串）段，沿用现有容错（类型不符丢弃+warning、截断、missing 列入 context_notes）。
- R5（G6+G7）：在 docs/backend-api.md 与 README 显式记录两个已验收偏差（失败统一重放错误响应、不按失败类型重试；幂等存储进程内、重启丢失）。
- R6：验收报告（本 PRD 表格）随任务归档，作为手册符合性的基线记录。

## Acceptance Criteria

- [ ] 每个差距 G1–G8 要么被修复并有测试覆盖，要么在手册或 docs/backend-api.md 中记录为有意决策（含理由）。
- [ ] R1 命名决策落地后：`pytest tests/unit tests/contract -q` 全绿，board-sim 展示字段与决策一致。
- [ ] R2 落地后：明文默认行为不回归；TLS 配置有单元/契约测试或本地验证记录。
- [ ] R4 落地后：新增 context 段的容错行为与现有 history/rules 规则一致（丢弃、截断、missing 标注）并有测试。
- [ ] docs/backend-api.md 与最终实现状态同步（含偏差记录）。

## Notes

- 关联任务：`08-04-backend-api-docs`（planning，docs/backend-api.md 已产出未提交）——本任务的 docs 改动叠加在其产出之上，提交时一并处理。
- 验收阶段已完成（见上表）；R1/R3 决策已定，见 Requirements。
- 手册是系统级文档（设备+云），本任务只改后端侧或修订手册对应条款，不动设备端范围。
