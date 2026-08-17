# Design: Backend manual acceptance gap closing

对应 PRD R1–R5。四块改动：手册修订（G3）、MQTTS（G4）、context 扩展（G5）、文档记录（G6/G7 + G1/G8 路线图）。

## 边界

- 只改后端侧与手册对应条款；不动设备端范围、不动 topic/QoS/retained/错误码等既有契约面。
- 所有改动均为增量：默认行为（明文 MQTT、四段 context）完全不变。
- `type=sensor_config` 及分类型超时明确不在本任务（已拆分后续任务）。

## D1 手册修订（G3 → R1）

`VelaGuard_项目手册.md`：

- §5.7「AI 输出结构」示例 JSON：`"summary"` → `"diagnosis_summary"`，并在示例后补一句：线上响应由 bridge 附加 `source`（`mimo|stub|fallback`）、`advisory_only`（stub/fallback）、`fallback_reason`（fallback）字段；AI 输出仅供参考，bridge 不据此执行设备写入。
- §10.1 输出格式 JSON：`"summary"` → `"diagnosis_summary"`。
- 不改 §10.2（sensor_config skill，随后续任务处理）。

理由：线上契约（bridge、契约测试、board-sim、docs/backend-api.md）已全线使用 `diagnosis_summary` 且刚完成中文诊断输出适配；改回 `summary` 是破坏性变更且无收益。

## D2 MQTTS 支持（G4 → R2）

### 配置（`configuration/settings.py`）

| 变量 | 默认 | 语义 |
|---|---|---|
| `MQTT_TLS` | `false` | 启用 TLS 连接 |
| `MQTT_CA_PATH` | 空 | CA bundle 文件路径；空则用系统 CA 存储 |
| `MQTT_CLIENT_CERT_PATH` | 空 | 客户端证书（mTLS，可选） |
| `MQTT_CLIENT_KEY_PATH` | 空 | 客户端私钥（mTLS，可选） |

校验（fail fast，沿用现有 field_validator 风格）：

- cert/key 必须成对出现（只给一个 → 启动报错）。
- 给定的路径必须存在（否则启动报错），错误消息不含路径外信息。
- `MQTT_TLS=false` 时忽略证书路径配置（不报错，保持 dev 姿态简单）。
- 端口不强制改 8883：沿用 `MQTT_PORT`，由部署者指定。

### 客户端（`transport/mqtt/client.py`）

`MqttBridgeClient.__init__` 增加参数 `tls_enabled=False, ca_path=None, client_cert_path=None, client_key_path=None`；在 `username_pw_set` 之后、回调注册之前：

```python
if tls_enabled:
    self._client.tls_set(
        ca_certs=ca_path or None,
        certfile=client_cert_path,
        keyfile=client_key_path,
    )
```

- 不提供 `tls_insecure_skip_verify` 类开关：证书校验永远开启。
- 其余行为（clean_session、重连重订阅、线程模型）不变。

### 装配（`__main__.py`）

从 Settings 透传四个参数到 client 构造。

### 测试

- `tests/unit/test_settings.py`：默认关；cert/key 不成对报错；路径不存在报错；`MQTT_TLS=false` + 路径不存在不报错。
- 新增 client TLS 用例（放 `tests/unit/`，mock `paho.mqtt.client.Client.tls_set` 断言参数；不联网）：tls 关→不调用；开+CA→`ca_certs=path`；开+无 CA→`ca_certs=None`；开+mTLS→certfile/keyfile 传入。

## D3 context 扩展（G5 → R4）

`runtime/json_validator.py`：

- 新上限：`MAX_SENSOR_CONFIG_CHARS = 4096`（寄存器表量级，参照 `MAX_EVENT_CHARS`）、`MAX_MANUAL_SUMMARY_CHARS = 2048`（参照 `MAX_DEVICE_CHARS`）。
- `sensor_config`：复用 `_normalize_object_section`——非对象丢弃 + `context_dropped` warning，超限走 `truncate_json_value`。
- `manual_summary`：新增 `_normalize_text_section`——仅接受 str（截断加 `TRUNCATED_MARKER`），非 str 丢弃 + warning。
- `ContextBundle` 增加 `sensor_config: dict|None`、`manual_summary: str|None` 字段；`to_dict()` 仅在非 None 时输出；`missing` 计算纳入两段。
- `MAX_USER_CONTENT_CHARS = 8192` 总界不动（新段挤占的是同一 user content 预算）。

`runtime/prompt_builder.py` / `runtime/skill_manager.py`：

- `DEFAULT_DIAGNOSIS_SKILL` 与 `industrial_fault_diagnosis.md` 中枚举 context 段落处的文案补充 `sensor_config`、`manual_summary`（说明缺失时应明说，不得编造）。
- 组装逻辑本身无需改：bundle.to_dict() 已整体序列化，`context_notes` 自动带上新段的 missing。

`ai_bridge/skills/industrial_fault_diagnosis.md`：同步段落清单文案。

### 测试

- 归一化用例（现有 json_validator/prompt_builder 测试文件内追加）：
  - sensor_config 合法对象通过；非对象丢弃且进 missing；超限截断带标记。
  - manual_summary 字符串通过；超长截断；非字符串丢弃且进 missing。
  - prompt user content 包含新段；缺失时 `context_notes` 出现 `sensor_config missing` / `manual_summary missing`。

## D4 文档记录（G6/G7 → R5；G1/G8 → R3）

`docs/backend-api.md`：

- 幂等章节：明确「已失败：重放存储的错误响应，不按失败类型重试」为对 §16.4 的已验收偏差；幂等存储进程内、重启丢失（若已有则核对表述）。
- 新增/更新：MQTT_TLS 等四个 env 变量说明 + 生产 MQTTS 提示；`context.sensor_config`、`context.manual_summary` 字段规则。
- 路线图小节：`type=sensor_config` 自然语言配置生成、手册解析、巡检报告、TTS、分类型超时为规划项，未实现。

`README.md`：

- env 表补四个 TLS 变量；Diagnosis context contract 规则补两段；Out of scope 补自然语言配置生成/巡检报告。

## 兼容与回滚

- 全部增量，默认路径行为不变；老请求（无新 context 段）产出与现状一致（新段仅多出 `context_notes` 提示，属 prompt 内部变化，不影响响应契约）。
- 回滚：按提交单元 revert；无数据/协议迁移。

## 风险

- prompt 预算：新段可能挤压 user content 8192 上限 → 已有截断机制兜底，测试覆盖一段「全部 context 段齐备且超限」的用例。
- paho `tls_set` 参数在不同 paho 版本一致（1.x/2.x 均支持 ca_certs/certfile/keyfile 关键字）；本项目锁 `paho-mqtt>=2.1`，1.x fallback 分支同样适用。
