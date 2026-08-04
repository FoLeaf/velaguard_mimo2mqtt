# Design: AI 诊断 Skill 与 fallback 闭环

## Summary

在现有 `Provider` 接缝和 v1 信封之上，为 `type=diagnosis` 增加 Agent Runtime 组件：`skill_manager`（加载 `industrial_fault_diagnosis.md`）、`prompt_builder`（用请求上下文组装有界 prompt）、`json_validator`（规范化请求上下文）、`fallback`（MiMo 失败时的降级结果）。MiMo 输出升级到 v2 诊断 schema 校验；应用层在 `provider_error` 且预算未耗尽时发布 `status=success + source=fallback` 的降级结果。信封、幂等、topic、QoS/retain 契约不变。

## Architecture Boundaries

新增模块（Agent Runtime，对应手册 5.4）：

- `ai_bridge/runtime/skill_manager.py` — 加载/缓存 Skill 文件，缺失回退内置 prompt
- `ai_bridge/runtime/prompt_builder.py` — 组装 system/user 消息，含上下文规范化调用与截断
- `ai_bridge/runtime/json_validator.py` — 请求上下文的结构校验与归一化（结果 schema 校验继续由 `providers/schema.py` 单一负责，避免重复实现）
- `ai_bridge/runtime/fallback.py` — 构建 v2-schema 合法的 fallback 诊断结果
- `ai_bridge/skills/industrial_fault_diagnosis.md` — 诊断 Skill 文件（数据资源）

修改模块：

- `ai_bridge/providers/schema.py` — v2 结果校验规则
- `ai_bridge/providers/mimo.py` — 注入 `system_prompt`/`user_content_builder`；失败分类增加 `fallback_eligible`
- `ai_bridge/providers/base.py` — `ProviderFailure` 增加 `fallback_eligible` 字段；`build_provider("mimo")` 组装 Skill + prompt
- `ai_bridge/providers/stub.py` — stub 结果升级为 v2 结构
- `ai_bridge/contracts/request.py` — `context` 顶层类型校验（存在且非对象 → `validation_error`）
- `ai_bridge/application/handle_request.py` — provider 失败后的 fallback 分支（应用层编排）
- `ai_bridge/configuration/settings.py` — `SKILLS_DIR`、`DIAGNOSIS_SKILL`、`FALLBACK_ENABLED`
- `ai_bridge/__main__.py` — 装配 fallback 依赖
- `tests/*`、`README.md`、`.env.example`、`.trellis/spec/backend/mqtt-ai-bridge-contracts.md`、`index.md`

依赖方向保持：providers 只依赖 contracts + runtime 组件（`mimo.py` 注入式使用 prompt 构建结果）；application 依赖 runtime（fallback）与 providers；runtime 不依赖 providers/application；无环。

## Data Flow

```text
HandleAiRequest.handle_message (unchanged topic/validation/idempotency/deadline)
  └─ Provider.handle(request, deadline_s)
       └─ MiMoProvider (built with SkillManager + prompt_builder)
            ├─ skill = skill_manager.load("industrial_fault_diagnosis")
            ├─ messages = prompt_builder(request, skill)      # bounded
            ├─ POST {base}/chat/completions (retry budget, per-attempt timeout)
            └─ json_validator / providers.schema validate → ProviderSuccess(v2) | ProviderFailure
  └─ ProviderFailure + fallback_eligible + budget remains
       └─ runtime/fallback.build_fallback_diagnosis(request, reason)
            └─ ProviderSuccess(source=fallback)  → publish status=success
  └─ ProviderFailure timeout / schema-invalid / FALLBACK_ENABLED=false
       └─ v1 error envelope (timeout | provider_error) unchanged
```

## Contracts

### Config additions

| Env | Type | Default | Notes |
|---|---|---|---|
| `SKILLS_DIR` | str | package default `ai_bridge/skills` | 可覆盖为绝对/相对路径；校验目录存在性可延后到首次加载 |
| `DIAGNOSIS_SKILL` | str | `industrial_fault_diagnosis` | 文件名白名单 `^[a-z0-9_]+$` |
| `FALLBACK_ENABLED` | bool | `true` | 运维开关；`false` 时保持原 `provider_error` 行为 |

### Request context (v1 请求字段 + 可选 `context`)

```json
{
  "context": {
    "event": {"event_id": "evt_1", "type": "threshold_high", "severity": "warning", "title": "...", "current_value": 82.4, "rule": "temperature > 70", "ts_ms": 1782450000000},
    "history": [{"ts_ms": 1782450000000, "values": {"temperature": 72.8}}],
    "rules": [{"rule_id": "r1", "expr": "temperature > 70", "severity": "warning", "message": "..."}],
    "device": {"name": "Motor Temp", "model": "RS485-TH-1", "description": "Cooling pump motor"}
  }
}
```

规则（`runtime/json_validator.py`）：

- `context` 可选；存在且非对象 → `validation_error`（在 `parse_request` 拦截）。
- `event`/`device` 非对象、`history` 非数组、`rules` 非数组 → warn + 丢弃该子字段（宽容降级，不拒绝整条请求）。
- `history` 仅保留前 50 条，`rules` 仅保留前 20 条，超出部分 warn + 截断。
- `history`/`rules` 中非对象条目 → warn + 丢弃；缺失 `ts_ms`/`values` 的 history 条目保留但显式标记缺失。
- 各字段 JSON 序列化上限：event 4096 字符、device 2048 字符、rules 8192 字符、history 16384 字符；超限截断并加 `...[truncated]`，warn。

### Result schema v2（MiMo / fallback / stub 共用）

```json
{
  "diagnosis_summary": "string (required, non-empty)",
  "risk_level": "low|medium|high (required)",
  "possible_causes": ["string"] (required, list[str], empty allowed),
  "recommended_actions": ["string"] (required, list[str], empty allowed),
  "need_shutdown": false (required, bool; bool-like ints rejected),
  "confidence": 0.0 (optional, number in [0,1]; bool rejected),
  "reasons": ["string"] (optional, legacy kept),
  "recommendations": ["string"] (optional, legacy kept),
  "source": "mimo|fallback|stub (bridge-added)",
  "advisory_only": true (stub/fallback only),
  "fallback_reason": "provider_error" (fallback only, extra key)
}
```

未知字段继续透传。`providers/schema.py::validate_diagnosis_result` 是唯一实现点；MiMo、fallback、stub 输出都经过它（stub 静态结果在构造/测试中校验一次即可，不要求运行时重复校验）。

### Fallback 结果

`runtime/fallback.py::build_fallback_diagnosis(request, reason) -> dict`：

- `diagnosis_summary`：固定模板英文文本（“Cloud AI diagnosis is temporarily unavailable; local template result.”），不拼接任意原始 payload。
- `risk_level`：由 `context.event.severity` 映射（`critical`/`error` → high，`warning` → medium，其他/缺失 → low）。
- `possible_causes` / `recommended_actions`：固定模板数组。
- `need_shutdown=false`、`confidence=0.0`、`source="fallback"`、`advisory_only=true`、`fallback_reason=reason`。
- 返回前经 `validate_diagnosis_result` 校验（防御性，正常恒通过）。

### ProviderFailure 扩展

```python
@dataclass(frozen=True, slots=True)
class ProviderFailure:
    code: str
    message: str
    fallback_eligible: bool = False  # additive; default False keeps old call sites valid
```

MiMo 分类：

| 条件 | code | fallback_eligible |
|---|---|---|
| 200 + schema 非法（JSON/缺字段/类型错） | provider_error | False |
| 401/403/400、429/5xx 重试耗尽、网络失败 | provider_error | True |
| deadline 已过（任何时刻） | timeout | False（保持默认） |

## Prompt 与 Skill

`ai_bridge/skills/industrial_fault_diagnosis.md`（英文，约 40-60 行）：角色定义、输入上下文说明（event/history/rules/device）、输出 v2 JSON schema、要求（仅返回 JSON、advisory only、不包含设备控制指令、缺信息时显式说明）。文件是运行时数据，不是 prompt 模板常量。

`runtime/prompt_builder.py`：

- `build_diagnosis_messages(request, skill_text) -> list[dict]`：system = skill 文本 + 固定的“仅返回 JSON + schema”附加指令（防止 Skill 被编辑后丢 schema 约束）；user = `{"device_id", "req_id", "type", "context": normalized}` JSON。
- 用户内容上限 `MAX_USER_CONTENT_CHARS = 8192`（替代现有 2048 常量），超限截断并加标记。
- 上下文为空时 user 消息显式标注 `"context": {}` + 缺省提示，prompt 仍可调用（MiMo 可返回基础诊断）。

`MiMoProvider` 构造参数扩展（向后兼容）：

- `system_prompt: str = DIAGNOSIS_SYSTEM_PROMPT`（现有）
- `user_content_builder: Callable[[AiRequest], str] | None = None` — 默认保持现有 `_safe_user_content`；由 `build_provider("mimo")` 注入 `prompt_builder` 的构建函数。

`build_provider("mimo")` 装配：`SkillManager(skills_dir).load(diagnosis_skill)` → `MiMoProvider(system_prompt=skill_text, user_content_builder=...)`；Skill 缺失时由 SkillManager 返回内置默认 prompt 并 warn。

## 错误分类与 fallback 策略

| 场景 | 发布内容 |
|---|---|
| provider 成功 | `success` + v2 result + `source=mimo` |
| MiMo 输出 schema 非法 | `error` + `provider_error`（不 fallback） |
| MiMo HTTP/网络失败、预算耗尽且剩余预算 > 0、`FALLBACK_ENABLED=true` | `success` + fallback result（`source=fallback`） |
| deadline 已过 | `error` + `timeout`（不 fallback） |
| `FALLBACK_ENABLED=false` | 维持原 `error` + `provider_error` |

应用层实现：`HandleAiRequest` 在收到 `ProviderFailure` 后，若 `fallback_eligible and fallback_enabled and _remaining_deadline_s(received_ts_ms) > 0`，构建 fallback 结果、`store.complete` 并发布 success；否则走现有 `_finish_error`。fallback 路径记 `warn`：`fallback_used device_id=... req_id=... reason=...`。幂等存储对 fallback 响应与普通 success 一视同仁（完成态重放）。

## 可观测性

- `skill_manager`：加载成功 `info`（skill 名、字节数），缺失/不可读 `warn`（不含路径细节之外的内容）。
- `prompt_builder`：上下文规范化 `warn`（丢弃条目数、截断字段），不记录原始 payload 全文。
- `fallback`：`warn` 记录 reason、elapsed；不记录密钥/provider body。
- 现有 `mimo_attempt` 日志不变；新增输出分类日志（success/fallback/provider_error）复用现有 logger 风格。

## 测试策略

- 更新 `tests/unit/test_mimo_provider.py`：v2 合法/非法矩阵（缺 `risk_level`、枚举非法、`need_shutdown` 非 bool、`confidence` bool/越界）、`fallback_eligible` 断言（schema 非法=False、401/429 耗尽/网络=True、timeout=False）、user content ≤ 8192、上下文进 prompt。
- 新增 `tests/unit/test_prompt_builder.py`：上下文渲染、缺失字段、history 50 条截断、rules 20 条截断、字段超限截断、总长度上限。
- 新增 `tests/unit/test_skill_manager.py`：加载、缓存、缺失回退默认 prompt、文件名穿越拒绝。
- 新增 `tests/unit/test_fallback.py`：schema 合法、`source=fallback`、severity→risk 映射、reason 透传、`advisory_only`。
- 更新 `tests/unit/test_handle_request.py`：fallback 触发/不触发（ineligible、timeout、disabled、预算耗尽）、fallback 重放、stub v2 结构。
- 更新 `tests/contract/test_request_validation.py`：`context` 非对象 → validation_error。
- 更新 `tests/unit/test_stub_provider.py` 与集成断言：stub 结果含 v2 必填字段。
- 验证命令：`pytest tests/unit tests/contract -q`（必过，无 live key）；`pytest tests/integration -q`（可选，需 Mosquitto）。

## 兼容与回滚

- v1 信封、topic、QoS/retain、错误码不变；`req_id + payload_hash` 幂等不变。
- v2 结果增量字段：旧消费方读到新字段无害；旧字段仍在。
- `PROVIDER=stub` 默认不变（结果结构升级为 v2，属同一任务内契约演进，需同步 README/spec）。
- 回滚：`FALLBACK_ENABLED=false` 可单独关闭降级；代码回滚 = 还原 provider_error 分支与 v2 校验（保持 commit 粒度清晰）。
- 线上 MiMo prompt 变更仅依赖 Skill 文件，可独立调整，不需要改代码。

## Explicit Non-Goals

- 不新增信封状态（无 `degraded`）。
- 不做流式/工具调用/多轮。
- 不在云端执行设备侧确认/安全校验。
- 不实现 TTS/ASR/手册解析。
- 不做可持久化幂等。
