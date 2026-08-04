# Implement: AI 诊断 Skill 与 fallback 闭环

## Execution Plan

Phase 1: 配置与契约（Settings、`context` 顶层校验、`ProviderFailure.fallback_eligible`）
Phase 2: v2 schema + stub 升级
Phase 3: Agent Runtime（skill_manager / prompt_builder / json_validator / fallback + Skill 文件）
Phase 4: MiMo 注入与失败分类 + 应用层 fallback 分支
Phase 5: 测试更新与新增
Phase 6: 文档与 spec 同步（README、`.env.example`、`mqtt-ai-bridge-contracts.md`、`index.md`）

## Ordered Checklist

1. **配置（`ai_bridge/configuration/settings.py`）**
   - `SKILLS_DIR: str | None`（默认 None → 包内 `ai_bridge/skills`）
   - `DIAGNOSIS_SKILL: str`（默认 `industrial_fault_diagnosis`，validator：非空 + `^[a-z0-9_]+$`）
   - `FALLBACK_ENABLED: bool`（默认 True）

2. **请求契约（`ai_bridge/contracts/request.py`）**
   - `parse_request`：`context` 存在且非 dict → `RequestValidationError("context must be an object")`
   - 不改变必填字段与 64 KiB 上限

3. **Provider 协议（`ai_bridge/providers/base.py`）**
   - `ProviderFailure` 增加 `fallback_eligible: bool = False`（frozen dataclass 追加默认字段）
   - `build_provider("mimo")`：解析 `SKILLS_DIR`（默认包路径）→ `SkillManager` → 加载 `DIAGNOSIS_SKILL` → `MiMoProvider(system_prompt=skill_text, user_content_builder=prompt_builder.build_diagnosis_user_content)`
   - `build_provider("stub")` 不变

4. **v2 结果 schema（`ai_bridge/providers/schema.py`）**
   - 必填：`diagnosis_summary`（非空 str）、`risk_level`（枚举 low|medium|high）、`possible_causes`/`recommended_actions`（list[str]，空列表合法）、`need_shutdown`（bool，拒绝 bool-like int）
   - 可选：`confidence`（`[0,1]`，拒绝 bool）、`reasons`/`recommendations`（list[str]）
   - 未知字段透传；错误消息不含 provider 内容

5. **Stub 升级（`ai_bridge/providers/stub.py`）**
   - 结果含 v2 必填字段：`risk_level=low`、`possible_causes=[]`、`recommended_actions=["Retry with PROVIDER=mimo for live diagnosis"]`、`need_shutdown=false`、`confidence=0.0`
   - 保留 `source="stub"`、`advisory_only=true`

6. **Skill 文件（`ai_bridge/skills/industrial_fault_diagnosis.md`）**
   - 英文，含角色、输入上下文（event/history/rules/device）、v2 输出 schema、JSON-only 约束、advisory-only 说明

7. **Agent Runtime**
   - `ai_bridge/runtime/skill_manager.py`：`SkillManager(skills_dir)` + `load(name)`；白名单校验；缺失/不可读 → 内置默认 prompt + warn；缓存
   - `ai_bridge/runtime/json_validator.py`：`normalize_diagnosis_context(raw_context) -> ContextBundle`（丢弃/截断规则按 design.md）
   - `ai_bridge/runtime/prompt_builder.py`：`build_diagnosis_messages(request, skill_text)` / `build_diagnosis_user_content(request)`；`MAX_USER_CONTENT_CHARS=8192`；system 消息追加固定 JSON schema 指令
   - `ai_bridge/runtime/fallback.py`：`build_fallback_diagnosis(request, reason)`；severity→risk 映射；返回前经 `validate_diagnosis_result`
   - `ai_bridge/runtime/__init__.py` 导出公共符号（按需，避免空壳）

8. **MiMo provider（`ai_bridge/providers/mimo.py`）**
   - 构造参数：`user_content_builder: Callable[[AiRequest], str] | None = None`（默认 `_safe_user_content`）
   - `_build_messages` 使用注入的 builder
   - 失败分类：schema 非法 → `fallback_eligible=False`；401/403/400、429/5xx 耗尽、网络 → `fallback_eligible=True`；timeout → 默认 False
   - 默认 `DIAGNOSIS_SYSTEM_PROMPT` 常量更新为 v2 schema 描述（当未注入 Skill 时仍可用）

9. **应用层 fallback（`ai_bridge/application/handle_request.py`）**
   - `HandleAiRequest` 新增参数：`fallback_builder: Callable[[AiRequest, str], dict] | None = None`、`fallback_enabled: bool = True`
   - `ProviderFailure` 分支：`fallback_eligible and fallback_enabled and remaining > 0` → 构建 fallback 结果 → `store.complete` + 发布 success + `warn` 日志；否则走现有 `_finish_error`
   - `timeout` 与 schema 非法不进入 fallback

10. **装配（`ai_bridge/__main__.py`）**
    - `build_runtime`：`HandleAiRequest(..., fallback_builder=build_fallback_diagnosis, fallback_enabled=settings.fallback_enabled)`

11. **测试**
    - 更新 `tests/unit/test_mimo_provider.py`（v2 矩阵、fallback_eligible、user content ≤ 8192、上下文进 prompt）
    - 新增 `tests/unit/test_prompt_builder.py`、`test_skill_manager.py`、`test_fallback.py`
    - 更新 `tests/unit/test_handle_request.py`（fallback 触发/禁用/预算耗尽/ineligible、重放、stub v2）
    - 更新 `tests/contract/test_request_validation.py`（`context` 非对象）
    - 更新 `tests/unit/test_stub_provider.py`、`tests/integration/test_mqtt_loop.py`（stub v2 断言）

12. **文档与 spec**
    - `.env.example`：`SKILLS_DIR`、`DIAGNOSIS_SKILL`、`FALLBACK_ENABLED`
    - `README.md`：context 契约、v2 result、fallback 语义、新 env、Skill 文件说明
    - `.trellis/spec/backend/mqtt-ai-bridge-contracts.md`：新增“Diagnosis context + v2 result + fallback”场景，更新结果 schema、错误矩阵、env 表
    - `.trellis/spec/backend/index.md`：Selected Implementation Choices 增加 Agent Runtime 组件与 fallback 决策（英文）

## Validation Commands

```bash
pytest tests/unit tests/contract -q
# 期望：全绿，无需 live MiMo key；现有用例更新后仍覆盖全部契约

pytest tests/integration -q
# 可选：需要 Mosquitto（docker compose -f deploy/dev/docker-compose.yml up -d）

# 手动端到端（PROVIDER=stub 默认回归）：
python -m ai_bridge.cli.synthetic_publisher --device-id dev01

# 手动 live MiMo（可选，服务器注入 key，永不进 repo/chat）：
# MIMO_API_KEY=<server-key> PROVIDER=mimo python -m ai_bridge
```

## Rollback Points

- `FALLBACK_ENABLED=false` 立即恢复原 `provider_error` 行为（无需发版）。
- `PROVIDER=stub` 默认不变；任何 MiMo 回归 → 切 stub。
- v1 信封/topic/幂等不变；代码回滚粒度 = 一次 commit（Agent Runtime + fallback 同批）。
- Skill 文件可独立调整 prompt，无需改代码。

## Quality Gates Before `task.py start`

- PRD AC1–AC8 全部可测项在测试计划中有对应用例
- `pytest tests/unit tests/contract` 全绿（本任务完成后）
- 无密钥出现在源码/测试/文档（`MIMO_API_KEY` 仅 `Settings` 字段 + `.env.example` 空值）
- README 与契约 spec 同步 v2 结构
- `implement.jsonl` / `check.jsonl` 已收录真实 spec 条目（sub-agent 派发模式）

## Sub-agent Notes

- Phase 2 实施前加载 `trellis-before-dev`；实施后 `trellis-check`
- 检查重点是：v2 校验唯一实现点、fallback 不吞 schema 非法/timeout、密钥隔离、契约文档同步
