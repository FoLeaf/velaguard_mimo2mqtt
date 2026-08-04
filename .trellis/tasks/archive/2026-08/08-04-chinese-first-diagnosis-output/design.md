# Design: 中文优先诊断输出

## Summary

把语言规则放在诊断 system prompt 的固定 schema 指令中，同时同步默认 skill 和文件 skill，并本地化 fallback/stub 固定结果。模型输出仍保持单个 JSON 对象和现有 v2 schema，不新增后处理翻译层。

## Data flow

请求 -> prompt_builder.build_diagnosis_messages -> fixed schema and language instructions + loaded skill -> MiMo provider -> JSON parse and v2 schema validation -> MQTT response envelope -> board-sim/debug-console display

fallback/provider stub -> fixed v2 result text in Chinese -> same schema validation and response envelope

## Boundaries

- prompt_builder.py owns the invariant language instruction shared by all skills.
- skill_manager.py owns the built-in fallback skill text; its language rule mirrors the file skill.
- industrial_fault_diagnosis.md is the checked-in operator-facing skill documentation.
- fallback.py and providers/stub.py own only fixed local result text and preserve source/advisory metadata.
- providers/schema.py remains language-agnostic and unchanged.

## Language contract

The prompt must say that the following explanatory fields use Simplified Chinese as the primary language:

- diagnosis_summary
- possible_causes
- recommended_actions
- reasons
- recommendations

It must also say that IDs, field names, units, error codes, model names, product names, code expressions and necessary technical terms may remain in their original form. This permits useful mixed-language technical output without accepting English prose as the default.

## Compatibility

No JSON field, risk enum, MQTT topic, envelope status, provider choice, retry, model, temperature or response_format changes. Existing English fixture strings in provider validation tests remain test fixtures for schema normalization; only user-facing fixed results and prompt assertions change.

## Rollback

The change is isolated to prompt text, static skill text, fallback/stub result strings and tests. Reverting the task commit restores prior language behavior without changing protocol or persisted data.

## Verification

- Assert the system prompt contains the Chinese-first rule and technical-term exception.
- Assert both default and file skill paths retain the rule.
- Assert fallback/stub result fields are Chinese while source/advisory fields remain unchanged.
- Run backend unit, contract and full pytest suites.
