# Implement plan: 中文优先诊断输出

## Ordered checklist

1. Baseline
   - Inspect current prompt, fallback, stub and tests.
   - Run prompt/fallback/provider tests before editing.

2. Prompt language contract
   - Add a stable Chinese-first language instruction next to the fixed JSON schema instructions in ai_bridge/runtime/prompt_builder.py.
   - Update DEFAULT_DIAGNOSIS_SKILL and ai_bridge/skills/industrial_fault_diagnosis.md with the same rule.
   - Preserve the existing JSON-only, advisory-only and schema requirements.

3. Fixed result localization
   - Translate fallback diagnosis_summary, possible_causes, recommended_actions and fallback_reason into concise Simplified Chinese.
   - Translate StubProvider diagnosis_summary and recommended_actions into concise Simplified Chinese.
   - Preserve source, advisory_only, confidence, risk_level, need_shutdown and error semantics.

4. Regression tests
   - Extend prompt builder tests for Chinese-first instructions and technical-field exceptions.
   - Extend fallback and stub tests for Chinese fixed text and unchanged metadata.
   - Do not assert a brittle exact translation for arbitrary external model output.

5. Verification and documentation
   - Run node-independent backend tests, full pytest and quality checks.
   - Review that no MQTT/envelope/schema/frontend changes were introduced.

## Validation commands

- pytest tests/unit/test_prompt_builder.py tests/unit/test_fallback.py tests/unit/test_mimo_provider.py -q
- pytest -q

## Risky files

- ai_bridge/runtime/prompt_builder.py: a malformed instruction could break JSON-only output or exceed prompt bounds.
- ai_bridge/runtime/skill_manager.py and ai_bridge/skills/industrial_fault_diagnosis.md: the two skill paths could drift.
- ai_bridge/runtime/fallback.py and ai_bridge/providers/stub.py: fixed result text must remain schema-valid and advisory.

## Pre-start gate

- PRD, design, implement and research artifacts are complete.
- No product decision remains unresolved.
- Do not run task.py start until the user explicitly approves this final planning summary.
