# AI 诊断 Skill 与 fallback 闭环

## Goal

让 `type=diagnosis` 请求走完整的云端诊断闭环：设备把事件、历史采样、规则、设备说明作为上下文随请求发送；AI Bridge 用 `industrial_fault_diagnosis` Skill 组织 prompt 调用 MiMo；返回结构化的完整诊断报告（现象、风险等级、可能原因、建议步骤、是否建议停机、置信度）；MiMo 不可用时，云端返回可识别的 fallback 降级结果，而不是只发布一个空错误。

## Background / Confirmed Facts

来源：仓库代码（`ai_bridge/`、`tests/`）、`VelaGuard_项目手册.md`（5.7、10.1、16.x）、`VelaGuard_推进方案.md`（6.2、6.3）、归档任务 `08-03-ai-bridge-mimo-provider`、`.trellis/spec/backend/*`。

- 当前 v1 诊断结果：`diagnosis_summary`（必填非空）、`reasons`/`recommendations`（可选字符串数组）、`confidence`（可选 `[0,1]`）；provider 在结果里加 `source`（`stub`/`mimo`）。
- Provider 接缝：`Provider.handle(request, *, deadline_s) -> ProviderSuccess | ProviderFailure`；MiMo provider 已实现强制 JSON、schema 校验、有界重试、单次 HTTP 超时、密钥隔离；请求内容来自 `request.raw`，用户消息截断到 2048 字符。
- 请求校验：必填 `req_id`、`device_id`、`created_ts_ms`、`type`（当前仅 `diagnosis`）、`payload_hash`；`AiRequest.raw` 保留完整 payload；普通 payload 上限 64 KiB。
- 响应信封：`processing` / `success` / `error`；错误码 `validation_error`、`conflict`、`timeout`、`provider_error`、`internal_error`；没有 `degraded` 状态。
- 手册定义的目标诊断结构（5.7 / 10.1）：现象、`risk_level`（low|medium|high）、可能原因、建议步骤、`need_shutdown`（bool）、`confidence`（0~1）。
- 手册约束：AI 输出只是建议，不直接控制设备；非法 JSON / 缺字段必须拒绝，不能当 success 发布；密钥永不进入 prompt、日志、MQTT payload。
- 方案 6.3：MiMo 或云服务器失败时使用本地 fallback 模板；设备 UI 有“诊断中 / 成功 / 失败 / 降级”四种展示状态（设备侧用 `source` 区分降级）。

## Key Decisions

1. **fallback 语义（用户已确认）**：fallback 响应沿用 `status=success`，`result.source="fallback"`、`result.advisory_only=true`；不新增信封状态，不破坏 v1 信封和幂等重放。
2. **v2 结果 schema 采用增量演进**：保留 v1 字段（`diagnosis_summary`、`reasons`、`recommendations`、`confidence`），新增必填字段 `risk_level`、`possible_causes`、`recommended_actions`、`need_shutdown`；未知字段继续透传。
3. **fallback 触发范围**：仅对 `provider_error`（HTTP 错误、网络失败、重试预算耗尽，含 401/403/400）且在请求预算仍有剩余时触发；MiMo 输出 schema 非法仍发布 `provider_error`（不 fallback）；整体 deadline 已过仍发布 `timeout`（不 fallback）。
4. **诊断上下文载荷**：请求新增可选顶层 `context` 对象（`event`、`history`、`rules`、`device`）；`context` 存在但非对象 → `validation_error`；子字段结构/大小问题在 Agent Runtime 层宽容处理（warn + 丢弃/截断），不因上下文小缺陷拒绝整条请求。

## Requirements

- R1. 升级诊断结果 schema 到 v2：`diagnosis_summary`（必填非空）、`risk_level`（必填，low|medium|high）、`possible_causes`（必填，字符串数组）、`recommended_actions`（必填，字符串数组）、`need_shutdown`（必填，bool）、`confidence`（可选，`[0,1]`）；`reasons`/`recommendations` 保留为可选兼容字段；未知字段透传。任何校验失败不得以 success 发布。
- R2. 定义并校验 `type=diagnosis` 上下文载荷契约：`context` 可选，存在时必须为对象；`event`/`device` 为对象、`history` 为数组（≤50 条）、`rules` 为数组（≤20 条）；子字段非法时 warn + 丢弃，大小超限时截断并 warn。
- R3. 实现 `skill_manager`：从可配置目录加载 `industrial_fault_diagnosis.md`；文件名白名单（`^[a-z0-9_]+$`）；缺失/不可读时回退内置默认 prompt 并 warn，不中断请求。
- R4. 实现 `prompt_builder`：把 Skill 内容 + 输出 schema 指令组成 system 消息，把规范化后的上下文组成 user 消息；总长度有界（用户内容 ≤ 8192 字符），超长截断而不是整包丢弃；prompt 中不出现任何密钥。
- R5. 实现 `json_validator`：负责请求上下文的规范化/校验（与 `providers/schema.py` 的结果校验单一职责分离，不重复实现）。
- R6. MiMo 失败且满足触发条件时返回 fallback 诊断结果：结构仍通过 v2 schema，`source="fallback"`、`advisory_only=true`、`confidence=0.0`，带 `fallback_reason`；可被设备识别为降级。
- R7. `PROVIDER=stub` 保持默认可用，stub 结果同步升级为 v2 结构；幂等、请求 deadline、重试、密钥隔离、v1 信封错误码契约保持不变。
- R8. `timeout` 与 schema 非法不进入 fallback：deadline 已过 → `error/timeout`；MiMo 输出非法 → `error/provider_error`（见 Key Decision 3）。

## Acceptance Criteria

- [ ] AC1. 带完整上下文（事件/历史/规则/设备说明）的 `type=diagnosis` 请求经 MiMo 成功时，响应 `status=success`，`result` 含 v2 全部必填字段、`source=mimo`，`req_id` 原样返回。
- [ ] AC2. MiMo 返回非法 JSON、缺必填字段、`risk_level` 枚举非法或 `need_shutdown`/`confidence` 类型非法时，响应为 `error` + `provider_error`，绝不 success，也不进入 fallback。
- [ ] AC3. MiMo HTTP/网络失败且重试预算耗尽时（预算未耗尽场景），响应 `status=success`、`result.source="fallback"`、`advisory_only=true`，通过 v2 schema；幂等存储记录该 fallback 响应，重复请求精确重放。
- [ ] AC4. 请求 deadline 已过时响应 `error/timeout`，不发布 fallback success；`FALLBACK_ENABLED=false` 时保持 `provider_error` 行为。
- [ ] AC5. prompt 实际包含事件、历史采样、规则、设备说明（有则用、无则显式标注缺失）；超长上下文被截断，单条 user 消息 ≤ 8192 字符。
- [ ] AC6. `context` 存在但非对象 → `validation_error`；history 超 50 条、规则子项非法等 → warn + 丢弃/截断，请求仍可处理。
- [ ] AC7. Skill 文件缺失/损坏时服务仍可用（内置默认 prompt），并记录 warn；文件名穿越被拒绝。
- [ ] AC8. 密钥隔离回归：`MIMO_API_KEY` 不出现在 prompt、日志、MQTT payload、测试 fixture；现有 redaction 测试覆盖新增字段名；`pytest tests/unit tests/contract` 全绿，`PROVIDER=stub` 端到端回归不变。

## Out of Scope

- TTS / ASR / 手册解析服务
- 可持久化幂等存储（SQLite/Redis）
- MQTTS、设备 token、Broker ACL
- 设备固件、板端 skill_manager / UI 诊断页
- 流式输出、工具/函数调用、多轮对话
- `diagnosis` 之外的新请求类型
- 新增信封状态（如 `degraded`）
