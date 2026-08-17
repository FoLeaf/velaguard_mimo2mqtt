# Implement: Backend manual acceptance gap closing

前置：PRD（含验收表与决策）、design.md。按序执行，每步末尾跑验证命令。

## 0. 准备

- [ ] `pip install -e ".[dev]"`（如环境已就绪可跳过）

## 1. 手册修订（G3 → R1，独立可回滚）

- [ ] `VelaGuard_项目手册.md` §5.7：示例 JSON `summary` → `diagnosis_summary`；示例后补 bridge 附加字段说明（source/advisory_only/fallback_reason，AI 输出 advisory only）。
- [ ] §10.1：输出格式 JSON `summary` → `diagnosis_summary`。
- 验证：grep 确认手册中诊断输出示例不再有裸 `"summary"`（§5.7/§10.1 范围；其他章节的 summary 措辞不属本项）。

## 2. context 扩展（G5 → R4）

- [ ] `ai_bridge/runtime/json_validator.py`：新增 `MAX_SENSOR_CONFIG_CHARS`/`MAX_MANUAL_SUMMARY_CHARS`、`_normalize_text_section`；`ContextBundle` 增加两字段并接入 `to_dict()`/`missing`。
- [ ] `ai_bridge/runtime/skill_manager.py` `DEFAULT_DIAGNOSIS_SKILL` 与 `ai_bridge/skills/industrial_fault_diagnosis.md`：context 段落清单补 `sensor_config`、`manual_summary`。
- [ ] 测试：归一化（通过/丢弃/截断/missing）、prompt 包含新段与 context_notes、全段齐备超限截断兜底。
- 验证：`pytest tests/unit tests/contract -q`

## 3. MQTTS 支持（G4 → R2）

- [ ] `ai_bridge/configuration/settings.py`：四个 env 字段 + 校验（成对、存在性、TLS 关时忽略）。
- [ ] `ai_bridge/transport/mqtt/client.py`：构造参数 + `tls_set` 装配（无 insecure 开关）。
- [ ] `ai_bridge/__main__.py`：透传。
- [ ] 测试：settings 校验用例；client `tls_set` mock 断言（关/开+CA/开无CA/mTLS）。
- 验证：`pytest tests/unit tests/contract -q`

## 4. 文档记录（G6/G7 → R5；G1/G8 → R3）

- [ ] `docs/backend-api.md`：失败重放偏差、进程内幂等表述核对、TLS env、context 新字段、路线图小节。
- [ ] `README.md`：env 表、context 规则、Out of scope 补自然语言配置生成/巡检报告。
- 验证：文档内字段名/变量名与代码一致（人工核对 + grep `diagnosis_summary`/`MQTT_TLS`）。

## 5. 全量质量检查（review gate）

- [ ] `pytest tests/unit tests/contract -q` 全绿
- [ ] 集成测试（可选，需本地 Mosquitto）：`docker compose -f deploy/dev/docker-compose.yml up -d && pytest tests/integration -q`
- [ ] 对照 `.trellis/spec/backend/quality-guidelines.md` 复查清单：契约变更评估、重试有界、幂等、密钥不泄露。
- [ ] 对照 PRD 验收标准逐条勾验。

## 回滚点

- 每步独立成 commit（或至少 step 1 与 2/3 分开），任一步可单独 revert。
