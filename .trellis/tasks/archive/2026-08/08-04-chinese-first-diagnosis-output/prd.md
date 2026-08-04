# 中文优先诊断输出

## Goal

让 AI Bridge 的诊断结果以简体中文为主要表达语言，保证真实 MiMo、内置 fallback 和 StubProvider 在板端/调试台看到的诊断摘要、可能原因和建议都适合中文用户阅读，同时保留设备标识、单位、错误码、协议字段和必要技术名词的原始形式。

## User value

当前真实诊断返回内容经常是英文，板端用户需要额外翻译才能理解风险和处理建议。统一的中文优先约束可以让真实模型输出、降级结果和本地测试结果保持一致的阅读体验。

## Confirmed facts from repository

- ai_bridge/runtime/prompt_builder.py:21-33 的 DIAGNOSIS_SCHEMA_INSTRUCTIONS 只约束 JSON 结构、风险枚举和 advisory 语义，没有语言要求；build_diagnosis_system_prompt() 在 :37-40 将其追加到 skill 文本。
- ai_bridge/runtime/skill_manager.py:20-46 的内置 DEFAULT_DIAGNOSIS_SKILL 没有中文输出规则；可配置 skill ai_bridge/skills/industrial_fault_diagnosis.md:1-48 同样只描述英文角色和 JSON schema。
- ai_bridge/runtime/fallback.py:39-57 的 fallback 固定返回英文摘要、原因和建议，即使没有调用模型也会在页面显示英文。
- ai_bridge/providers/stub.py:38-47 的 StubProvider 固定返回英文摘要和建议，用于本地测试/演示。
- ai_bridge/providers/schema.py 只校验字段类型、风险枚举和范围，不应通过后处理强行翻译任意模型输出，否则可能破坏代码、单位、专有名词或诊断事实；语言优先约束应放在 prompt 和固定结果文本中。
- 现有 prompt 测试位于 tests/unit/test_prompt_builder.py:202-216，fallback/provider 行为测试主要位于 tests/unit/test_mimo_provider.py 与 tests/unit/test_fallback.py。

## Requirements

- R1. 真实 provider 的 system prompt 必须明确要求：diagnosis_summary、possible_causes、recommended_actions 以及可选 reasons、recommendations 以简体中文为主；不要因为输入 context 含英文就直接返回英文解释。
- R2. Prompt 必须允许保留设备 ID、传感器/协议字段名、单位、错误码、型号、产品名、代码表达式和必要技术术语原样，避免为了中文化而改变可操作信息。
- R3. 内置默认 skill 与仓库中的 industrial fault diagnosis skill 都要包含同等中文优先规则，确保外部 skill 文件缺失或正常加载时行为一致。
- R4. fallback 结果的摘要、可能原因、建议和 fallback reason 改为简体中文；字段名、source=fallback、advisory_only 等协议语义不变。
- R5. StubProvider 固定结果改为简体中文，保留 source=stub、advisory_only 和既有 schema。
- R6. 不新增模型输出后处理翻译器，不修改 v2 JSON schema、MQTT envelope、风险枚举或后端协议字段。
- R7. 增加回归测试，验证 system prompt 包含中文优先规则，默认 skill/文件 skill 均可触发该规则，fallback/stub 的面向用户文本不再是当前英文固定文案。

## Acceptance Criteria

- [x] AC1. 发送 diagnosis 请求时，MiMo system prompt 明确要求解释性诊断字段使用简体中文为主，并明确列出可保留原文的技术字段类别。
- [x] AC2. 默认内置 skill 与 industrial_fault_diagnosis.md 均包含中文优先规则，skill 加载路径不同不会丢失该约束。
- [x] AC3. fallback 和 StubProvider 的摘要、原因、建议文本均为中文，wire schema 和来源字段保持兼容。
- [x] AC4. 相关单元/契约测试通过，且不改变现有 prompt 长度限制、JSON-only 输出和 schema validation 行为。
- [x] AC5. 不修改 MQTT topic、响应 envelope、风险枚举或前端协议解析；已有 backend 全量测试通过。

## Out of scope

- 不对任意模型返回内容进行自动机器翻译或逐字段语言检测。
- 不改动 MiMo 模型、temperature、response_format、HTTP 重试或 provider 选择逻辑。
- 不翻译设备 ID、传感器型号、单位、代码表达式、错误码、JSON 字段名和协议状态。
- 不扩展到非 diagnosis 请求类型。

## Technical notes

- 语言要求放在固定 schema 指令附近，确保无论 skill 文件内容如何变化，最终 system prompt 都携带该约束。
- 固定 fallback/stub 文案直接本地化，避免 provider 不可用或测试模式下仍显示英文。
- 当前任务为 backend runtime/prompt/documentation/test 变更；前端只消费现有中文/文本字段，不需要改动。

## Notes

- 中文优先 prompt、skill、fallback、stub 和回归测试已实现；完整 pytest、ruff、mypy 和 compileall 均通过。
