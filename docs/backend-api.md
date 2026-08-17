# 当前后端接口文档

> 适用范围：当前仓库中的 VelaGuard AI Bridge。  
> 核对时间：2026-08-16。  
> 接口形态：MQTT 请求/响应，不是 HTTP REST。

本文只描述代码已经实现的后端边界。规划中的 TTS、ASR、手册解析、OTA、设备本地 HTTP API 等能力不属于当前接口。

## 1. 后端边界

当前链路如下：

```text
设备或调试面板 -> MQTT Broker -> AI Bridge -> MiMo HTTPS（可选）
```

AI Bridge 是 MQTT Broker 的独立客户端：

- 从请求主题接收 AI 请求；
- 校验请求并按 `req_id + payload_hash` 做进程内幂等处理；
- 使用 Stub 或 MiMo Provider 生成结构化诊断结果；
- 将 `processing`、终态成功或终态错误发布到响应主题。

当前没有可供设备直接调用的 HTTP endpoint。MiMo HTTPS 只在 Bridge 内部使用，不能当作设备侧接口。

## 2. MQTT 连接约定

| 项目 | 当前实现 |
|---|---|
| 请求主题过滤器 | `vg/+/ai/request` |
| 单个设备请求主题 | `vg/{device_id}/ai/request` |
| 单个请求响应主题 | `vg/{device_id}/ai/response/{req_id}` |
| QoS | `1` |
| Retained | `false` |
| MQTT 协议 | MQTT 3.1.1 |
| Bridge 客户端 | 独立 MQTT 客户端 |
| 默认客户端 ID | `ai-bridge-dev` |
| 会话 | `clean_session=true` |
| 请求/响应编码 | UTF-8 JSON object |
| 普通 MQTT payload 上限 | 64 KiB（`65,536` bytes） |

请求和响应都不使用 retained message。QoS 1 代表至少一次投递，调用方必须允许重复响应并依赖下文的幂等语义。

生产环境应使用 MQTTS、设备级凭据或 token 和 Broker ACL。Bridge 侧通过 `MQTT_TLS` / `MQTT_CA_PATH` / `MQTT_CLIENT_CERT_PATH` / `MQTT_CLIENT_KEY_PATH` 环境变量启用 TLS（见 8.1），不提供跳过证书校验的 insecure 开关。仓库里的明文匿名 Mosquitto 仅用于受控的本地开发验证。

### 2.1 主题规则

请求主题必须严格匹配：

```text
vg/{device_id}/ai/request
```

其中 `{device_id}` 不能为空，也不能是 `+`。Bridge 只从 `vg/+/ai/request` 订阅请求；响应主题由请求体中的 `device_id` 和 `req_id` 生成：

```text
vg/{device_id}/ai/response/{req_id}
```

请求体中的 `device_id` 必须与主题中的 `{device_id}` 完全一致，否则不会调用 Provider。

## 3. AI 诊断请求

### 3.1 发布方式

```text
Topic:   vg/{device_id}/ai/request
QoS:     1
Retain:  false
Payload: UTF-8 JSON object
```

### 3.2 顶层字段

| 字段 | 类型 | 必填 | 当前规则 |
|---|---|---:|---|
| `req_id` | string | 是 | 去除首尾空白后不能为空。用于关联响应和幂等。 |
| `device_id` | string | 是 | 去除首尾空白后不能为空，且必须等于请求主题中的设备 ID。 |
| `created_ts_ms` | integer | 是 | Unix 毫秒时间戳，必须 `>= 0`；布尔值不算整数。 |
| `type` | string | 是 | 当前只支持 `diagnosis`。 |
| `payload_hash` | string | 是 | 去除首尾空白后不能为空，用作幂等键的一部分。 |
| `context` | object | 否 | `type=diagnosis` 的结构化诊断上下文，见 3.3。存在时必须是 JSON object。 |
| 其他字段 | 任意 JSON 类型 | 否 | 当前请求解析器允许保留；Provider prompt 只使用已定义的诊断上下文。 |

当前后端只要求 `payload_hash` 是非空字符串，不会重新计算并校验它是否与请求体内容匹配。调用方仍应按统一算法生成它：

```python
canonical = json.dumps(
    body_without_payload_hash,
    sort_keys=True,
    separators=(",", ":"),
)
payload_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

其中 `body_without_payload_hash` 包含请求的其他字段（包括 `context` 和业务自定义字段），但不包含 `payload_hash` 自身。该算法与 `ai_bridge.cli.synthetic_publisher.build_request` 以及调试面板保持一致。

### 3.3 `context` 结构

`context` 是可选的顶层对象。推荐结构如下：

```json
{
  "context": {
    "event": {
      "event_id": "evt-001",
      "severity": "warning",
      "title": "Motor temperature is high",
      "current_value": 82.4
    },
    "history": [
      {
        "ts_ms": 1782450000000,
        "values": {
          "temperature": 72.8
        }
      }
    ],
    "rules": [
      {
        "rule_id": "r1",
        "expr": "temperature > 70"
      }
    ],
    "device": {
      "name": "Motor Temp",
      "model": "RS485-TH-1",
      "description": "Motor temperature sensor"
    },
    "sensor_config": {
      "registers": [
        {"key": "temperature", "addr": 40001, "data_type": "int16", "scale": 0.1}
      ]
    },
    "manual_summary": "温度传感器接在保持寄存器 40001，量程 0-150C。"
  }
}
```

Bridge 会对六个已知 section 做宽容规范化，再将其放入 MiMo prompt：

| Section | 期望类型 | 当前限制和处理 |
|---|---|---|
| `event` | object | 非 object 时丢弃并记录 warning；内容上限约 4,096 字符。 |
| `device` | object | 非 object 时丢弃并记录 warning；内容上限约 2,048 字符。 |
| `history` | array[object] | 非 array 时丢弃；非 object 条目丢弃；最多保留前 50 条；内容上限约 16,384 字符。 |
| `rules` | array[object] | 非 array 时丢弃；非 object 条目丢弃；最多保留前 20 条；内容上限约 8,192 字符。 |
| `sensor_config` | object | 传感器配置/寄存器表。非 object 时丢弃并记录 warning；内容上限约 4,096 字符。 |
| `manual_summary` | string | 用户手册摘要。非 string 时丢弃并记录 warning；内容上限约 2,048 字符，超长截断。 |

补充规则：

- `context` 本身不是 object 时，直接返回 `validation_error`，不会调用 Provider。
- section 缺失或因类型错误被丢弃时，会在 Provider prompt 的 `context_notes` 中标记为 `"{section} missing"`。
- 超长 section 会截断，并追加 `...[truncated]` 标记。
- `history` 条目缺少 `ts_ms` 或 `values` 时保留该条目，并追加 `__missing__` 字段说明缺失项。
- 未知的 `context` 子字段不会进入规范化后的 Provider prompt。
- 规范化只影响 Provider 输入；原始请求仍保留在 Bridge 内部的 `raw` 请求对象中。

### 3.4 完整请求示例

下面的 `payload_hash` 是占位符，实际发送前必须按 3.2 的算法计算：

```json
{
  "req_id": "req-demo-001",
  "device_id": "dev01",
  "created_ts_ms": 1782450000000,
  "type": "diagnosis",
  "payload_hash": "<sha256-of-canonical-body-without-payload_hash>",
  "context": {
    "event": {
      "event_id": "evt-001",
      "severity": "warning",
      "title": "Motor temperature is high",
      "current_value": 82.4
    },
    "history": [
      {
        "ts_ms": 1782450000000,
        "values": {
          "temperature": 72.8
        }
      }
    ],
    "rules": [
      {
        "rule_id": "r1",
        "expr": "temperature > 70"
      }
    ],
    "device": {
      "name": "Motor Temp",
      "model": "RS485-TH-1",
      "description": "Motor temperature sensor"
    }
  }
}
```

## 4. AI 响应

### 4.1 发布方式

```text
Topic:   vg/{device_id}/ai/response/{req_id}
QoS:     1
Retain:  false
Payload: UTF-8 JSON object
```

### 4.2 响应 envelope

所有可关联的响应都使用以下字段：

| 字段 | 类型 | `processing` | `success` | `error` |
|---|---|---:|---:|---:|
| `req_id` | string | 有 | 有 | 已知时有 |
| `device_id` | string | 有 | 有 | 已知时有 |
| `type` | string | 有 | 有 | 已知时有，否则为 `unknown` |
| `status` | string | `processing` | `success` | `error` |
| `error_code` | string/null | `null` | `null` | 必填，见 4.4 |
| `error_message` | string/null | `null` | `null` | 可选的安全错误描述 |
| `result` | object/null | `null` | 必填 | `null` |
| `received_ts_ms` | integer | 有 | 有 | 有 |
| `bridge_ts_ms` | integer | 有 | 有 | 有 |

### 4.3 响应生命周期

当前主进程对新请求默认发布：

```text
processing -> success
processing -> error
```

`processing` 只表示 Bridge 已接收并开始或已在处理，不表示 Provider 已成功。

成功示例：

```json
{
  "req_id": "req-demo-001",
  "device_id": "dev01",
  "type": "diagnosis",
  "status": "success",
  "error_code": null,
  "error_message": null,
  "result": {
    "diagnosis_summary": "本地 StubProvider 未调用在线 MiMo。",
    "risk_level": "low",
    "possible_causes": [],
    "recommended_actions": [
      "将 PROVIDER 设置为 mimo 以执行在线诊断。"
    ],
    "need_shutdown": false,
    "confidence": 0.0,
    "source": "stub",
    "advisory_only": true
  },
  "received_ts_ms": 1782450000000,
  "bridge_ts_ms": 1782450000003
}
```

错误示例：

```json
{
  "req_id": "req-demo-001",
  "device_id": "dev01",
  "type": "diagnosis",
  "status": "error",
  "error_code": "validation_error",
  "error_message": "missing or invalid field: payload_hash",
  "result": null,
  "received_ts_ms": 1782450000000,
  "bridge_ts_ms": 1782450000001
}
```

### 4.4 错误码

| `error_code` | 触发条件 | Provider 是否调用 |
|---|---|---:|
| `validation_error` | JSON 无效、payload 不是 object、缺少或错误字段、主题与 payload 的 `device_id` 不一致、不支持的 `type`、负时间戳、非法 `context`、payload 超过 64 KiB 等。 | 否 |
| `conflict` | 同一个 `req_id` 已经见过，但本次 `payload_hash` 不同。 | 否 |
| `timeout` | Provider 开始前、Provider 处理期间或返回后已超过 `REQUEST_TIMEOUT_MS`。 | 可能已调用 |
| `provider_error` | Provider 返回不可恢复错误、重试预算耗尽、MiMo 非法结构化输出，或 fallback 被关闭/不适用。 | 是 |
| `internal_error` | Bridge 内部出现未预期异常，或 fallback 构造失败。 | 可能已调用 |

错误响应的 `result` 始终为 `null`。`error_message` 只包含安全文本，不应包含 API key、完整上游响应或其他敏感信息。

如果无法安全得到 `req_id` 或 `device_id`，Bridge 不会发布错误响应，因为无法安全构造响应主题。例如 JSON 完全无法解析，或请求缺少 `req_id` 时，通常只能记录日志并丢弃。

## 5. `result` 诊断结果 schema

`status=success` 时，诊断结果位于 `result`。Provider 输出在发布前必须通过 schema 校验。

| 字段 | 类型 | 规则 |
|---|---|---|
| `diagnosis_summary` | string | 必填，去除首尾空白后不能为空。 |
| `risk_level` | string | 必填，只能是 `low`、`medium`、`high`。 |
| `possible_causes` | array[string] | 必填，允许空数组。 |
| `recommended_actions` | array[string] | 必填，允许空数组。 |
| `need_shutdown` | boolean | 必填；`0`/`1` 等整数不接受。 |
| `confidence` | number | 可选，范围为 `[0, 1]`；布尔值不接受。 |
| `reasons` | array[string] | 可选。 |
| `recommendations` | array[string] | 可选，兼容字段。 |
| `source` | string | Bridge 当前使用 `mimo`、`stub` 或 `fallback`。 |
| `advisory_only` | boolean | Stub 和 fallback 模板会设置为 `true`；所有 AI 结果都必须按 advisory 处理。 |
| `fallback_reason` | string | 仅 fallback 结果使用，说明触发降级的安全原因。 |
| 其他字段 | 任意 JSON 类型 | 允许透传，以保持向前兼容。 |

Bridge 不会因为 `need_shutdown=true` 或其他 AI 字段直接执行设备写操作。设备侧仍需执行自己的 schema 校验、风险检查、必要的测试读和本地确认流程。

### 5.1 Stub 结果

默认 `PROVIDER=stub`，不需要 MiMo 凭据，返回确定性的本地验证结果：

```json
{
  "diagnosis_summary": "本地 StubProvider 未调用在线 MiMo。",
  "risk_level": "low",
  "possible_causes": [],
  "recommended_actions": [
    "将 PROVIDER 设置为 mimo 以执行在线诊断。"
  ],
  "need_shutdown": false,
  "confidence": 0.0,
  "source": "stub",
  "advisory_only": true
}
```

### 5.2 Fallback 结果

当 MiMo/Provider 发生可降级的 `provider_error`，且总体请求 deadline 仍有剩余时间、`FALLBACK_ENABLED=true` 时，Bridge 返回 `status=success`，但 `result.source` 为 `fallback`。`risk_level` 由 `context.event.severity` 推导：`critical`/`error` 为 `high`，`warning` 为 `medium`，其余情况（含无 event）为 `low`。下面是无 severity 时的模板结果：

```json
{
  "diagnosis_summary": "云端 AI 诊断暂时不可用，当前返回本地模板结果。",
  "risk_level": "low",
  "possible_causes": [
    "云端 AI 服务暂时不可用（provider 失败）。"
  ],
  "recommended_actions": [
    "请稍后重试诊断。",
    "继续本地监控，并检查最新告警和遥测值。"
  ],
  "need_shutdown": false,
  "confidence": 0.0,
  "source": "fallback",
  "advisory_only": true,
  "fallback_reason": "云端 AI 服务暂时不可用，已使用本地模板结果。原始原因：mimo provider error (HTTP 500)"
}
```

Fallback 不适用于 deadline 已耗尽、schema 校验失败等情况；这些情况仍会发布 `timeout` 或 `provider_error`。

## 6. 幂等和重复消息

幂等键为：

```text
req_id + payload_hash
```

当前实现使用线程安全的进程内内存存储，并按 `req_id` 检测 hash 冲突：

| 情况 | Bridge 行为 | Provider 调用 |
|---|---|---:|
| 首次出现 | 原子占用，按正常流程处理。 | 1 次 |
| 相同 key 且仍在处理 | 发布 `status=processing`，不重复启动工作。 | 0 次 |
| 相同 key 且已有成功/错误终态 | 原样重发已保存的完整 envelope，包括原始时间戳。 | 0 次 |
| 相同 `req_id` 但 hash 不同 | 发布 `status=error`、`error_code=conflict`。 | 0 次 |

已验收偏差（相对手册 §16.4，2026-08-16 记录）：

- 手册 §16.4 建议「已失败：按失败类型决定是否允许重试」。当前实现**统一重放存储的错误响应，不按失败类型决定重试**：失败终态与成功终态一样被保存并原样重放，重复请求不会触发第二次 Provider 调用。理由：保持 `provider_error` / `timeout` 响应确定性，避免重试风暴；需要重试时由调用方使用新的 `req_id` 重新发起。
- 幂等状态仅保存于当前进程，Bridge 重启后全部丢失，不是 restart-safe 的生产持久化方案。该限制作为已知限制记录（手册未强制持久化，生产化前需升级为持久化需求）。

## 7. MiMo 上游 HTTPS（Bridge 内部附录）

只有 `PROVIDER=mimo` 时启用。该接口不暴露给设备，也不改变 MQTT 请求/响应格式。

### 7.1 请求

```text
POST {MIMO_BASE_URL}/chat/completions
Authorization: Bearer {MIMO_API_KEY}
Content-Type: application/json
```

请求 JSON 当前为：

```json
{
  "model": "mimo-v2.5",
  "messages": [
    {
      "role": "system",
      "content": "<skill text plus JSON schema instructions>"
    },
    {
      "role": "user",
      "content": "<bounded normalized diagnosis request JSON>"
    }
  ],
  "temperature": 0,
  "response_format": {
    "type": "json_object"
  }
}
```

Bridge 从 `choices[0].message.content` 取结果；字符串内容会先解析为 JSON，object 内容可直接校验。无法解析或不符合诊断 schema 的结果不会作为成功发布。

### 7.2 重试和失败映射

- `429`、`5xx`、网络异常和单次 HTTP timeout：在 `MIMO_MAX_RETRIES` 范围内重试，退避基于 `MIMO_RETRY_BACKOFF_MS` 并带 jitter。
- `400`、`401`、`403`：不重试，直接归类为 `provider_error`，但当前实现允许进入 fallback。
- 其他非 `200` 状态：归类为 `provider_error`，当前实现允许进入 fallback。
- 上游响应 schema 无效：归类为 `provider_error`，不进入 fallback。
- 总体 deadline 耗尽：归类为 `timeout`，不进入 fallback。
- 每次 HTTP attempt 的 timeout 不会超过剩余的总体 deadline。

## 8. 运行配置

配置通过环境变量或项目根目录 `.env` 加载。默认启动命令为 `python -m ai_bridge`。

### 8.1 MQTT、流程和 Stub

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `MQTT_HOST` | `localhost` | MQTT Broker 主机。 |
| `MQTT_PORT` | `1883` | MQTT Broker 端口，范围 `1-65535`。 |
| `MQTT_USERNAME` | 空 | 可选用户名。 |
| `MQTT_PASSWORD` | 空 | 可选密码。 |
| `MQTT_CLIENT_ID` | `ai-bridge-dev` | Bridge MQTT client ID。 |
| `MQTT_TLS` | `false` | 是否启用 MQTT over TLS（MQTTS）。`false` 时证书路径配置被忽略。 |
| `MQTT_CA_PATH` | 空 | CA bundle 文件路径；为空时使用系统 CA 存储。 |
| `MQTT_CLIENT_CERT_PATH` | 空 | mTLS 客户端证书路径；必须与 `MQTT_CLIENT_KEY_PATH` 成对配置。 |
| `MQTT_CLIENT_KEY_PATH` | 空 | mTLS 客户端私钥路径；必须与 `MQTT_CLIENT_CERT_PATH` 成对配置。 |
| `REQUEST_TIMEOUT_MS` | `30000` | 单个 AI 请求的总体 deadline，必须为正数。 |
| `PROVIDER` | `stub` | `stub` 或 `mimo`。 |
| `STUB_DELAY_MS` | `0` | Stub 人为延迟，必须非负，主要用于超时验证。 |
| `LOG_LEVEL` | `INFO` | 日志级别：`CRITICAL`、`ERROR`、`WARNING`、`INFO` 或 `DEBUG`。 |
| `SKILLS_DIR` | 包内 `ai_bridge/skills` | 诊断 skill Markdown 所在目录。 |
| `DIAGNOSIS_SKILL` | `industrial_fault_diagnosis` | skill 文件名，必须匹配 `^[a-z0-9_]+$`。 |
| `FALLBACK_ENABLED` | `true` | 是否启用可降级 Provider 错误的模板成功结果。 |

TLS 校验规则（启动时 fail fast）：`MQTT_TLS=true` 时，客户端证书与私钥必须成对出现（只配一个会启动报错）；已配置的路径必须是存在的文件（否则启动报错）。`MQTT_TLS=false` 时证书路径配置全部忽略，保持明文开发姿态。端口不强制 8883，由 `MQTT_PORT` 指定。Bridge 不提供任何跳过证书校验的 insecure 开关。

### 8.2 MiMo

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `MIMO_BASE_URL` | `https://token-plan-cn.xiaomimimo.com/v1` | MiMo API base URL，Bridge 追加 `/chat/completions`。 |
| `MIMO_MODEL` | `mimo-v2.5` | MiMo 模型 ID。 |
| `MIMO_API_KEY` | 无 | Secret；`PROVIDER=mimo` 时必填，启动时缺失会快速失败。 |
| `MIMO_HTTP_TIMEOUT_MS` | `15000` | 单次 HTTP attempt 的上限，必须为正数，实际不会超过总体 deadline。 |
| `MIMO_MAX_RETRIES` | `2` | 最大重试次数，范围 `0-5`；默认最多 `3` 次 HTTP attempt。 |
| `MIMO_RETRY_BACKOFF_MS` | `500` | 重试退避基准毫秒数，必须非负。 |

`MIMO_API_KEY` 只能通过部署环境注入，不能进入 Git、测试 fixture、MQTT payload、日志或文档。

## 9. 本地验证

启动本地 Mosquitto（仅开发环境）：

```bash
docker compose -f deploy/dev/docker-compose.yml up -d
```

启动 Bridge：

```bash
python -m ai_bridge
```

默认使用 Stub Provider 发送一条诊断请求：

```bash
python -m ai_bridge.cli.synthetic_publisher --device-id dev01
```

正常情况下会在 `vg/dev01/ai/response/{req_id}` 收到一个 `processing`，随后收到 `success` 终态。若没有终态，synthetic publisher 会以超时失败；它不会改变 Bridge 的请求契约。

生产环境不要复用本地 Docker 配置中的明文匿名 MQTT。

## 10. 当前限制和未实现边界

- 没有 HTTP REST API，也没有设备到 Bridge 的直连 socket。
- 当前只支持 `type=diagnosis`；其他类型会返回 `validation_error`。
- TTS、ASR、手册解析、语音分片、OTA 等主题目前不是本 Bridge 的已实现接口。
- 幂等状态仅保存于当前进程，Bridge 重启后全部丢失。
- 后端当前不重新计算 `payload_hash`；调用方必须自行保证 hash 与请求体一致。
- 普通 MQTT payload 受 64 KiB 限制；音频、PDF、图片、完整手册或固件不能作为单条普通 MQTT 消息发送。
- AI 结果始终是 advisory；Bridge 不直接授权设备写入或停机。
- 设备状态上报主题 `vg/{device_id}/status` 属于**规划中的合同**，当前代码未实现（见附录 A）。

### 10.1 路线图（规划中，未实现）

手册 §8.4/§10.2 设想的多类 MiMo 调用中，以下能力**均为规划项，当前未实现**，已从本任务拆分为后续任务：

| 规划能力 | 说明 |
|---|---|
| 自然语言传感器配置生成（`type=sensor_config`） | 将自然语言/手册寄存器表转换为候选传感器配置；对应 skill `sensor_config_generator.md` 尚未创建。 |
| 手册解析 | 云端解析上传手册，产出 `manual_profile`/`sensor_profile`。 |
| 巡检报告 | 周期性/按需生成设备巡检报告。 |
| TTS | 诊断摘要的云端语音合成与 `tts/*` 主题。 |
| 分类型超时 | 按任务类型区分超时窗口（配置生成 15-30s、手册解析 60-180s 等）；当前为单一 `REQUEST_TIMEOUT_MS`。 |

## 11. 代码和测试索引

| 内容 | 代码位置 |
|---|---|
| 主题、QoS、retain | [`ai_bridge/contracts/topics.py`](../ai_bridge/contracts/topics.py) |
| 请求字段和校验 | [`ai_bridge/contracts/request.py`](../ai_bridge/contracts/request.py) |
| 响应 envelope 和错误码 | [`ai_bridge/contracts/envelope.py`](../ai_bridge/contracts/envelope.py) |
| 请求编排、幂等、超时、fallback | [`ai_bridge/application/handle_request.py`](../ai_bridge/application/handle_request.py) |
| 进程内幂等存储 | [`ai_bridge/persistence/idempotency.py`](../ai_bridge/persistence/idempotency.py) |
| 诊断结果 schema | [`ai_bridge/providers/schema.py`](../ai_bridge/providers/schema.py) |
| Stub Provider | [`ai_bridge/providers/stub.py`](../ai_bridge/providers/stub.py) |
| MiMo HTTPS Provider | [`ai_bridge/providers/mimo.py`](../ai_bridge/providers/mimo.py) |
| context 规范化和 prompt | [`ai_bridge/runtime/json_validator.py`](../ai_bridge/runtime/json_validator.py)、[`ai_bridge/runtime/prompt_builder.py`](../ai_bridge/runtime/prompt_builder.py) |
| 环境配置 | [`ai_bridge/configuration/settings.py`](../ai_bridge/configuration/settings.py) |
| 合同测试 | [`tests/contract/`](../tests/contract/) |

---

# 附录 A：设备状态上报主题（规划中，尚未实现）

> **状态标注：`规划中`。** 本节记录 `vg/{device_id}/status` 主题的设计合同与 QoS/retain 取舍，作为后续实现与对接的依据。
> 当前 `ai_bridge` 代码和本仓库**均未实现**该主题（`ai_bridge/contracts/topics.py` 只定义了 `vg/+/ai/request` 和响应主题）。在代码落地前，请勿把它当作可用接口。

## A.1 主题契约

| 项目 | 约定 |
|---|---|
| 主题 | `vg/{device_id}/status` |
| 方向 | 设备 → 云（Bridge/订阅方只订阅，不发布）|
| QoS | `0` |
| Retain | `true` |
| Payload | UTF-8 JSON object，如 `{"online": true, "link": "wifi", "version": "1.2.0"}` |

## A.2 为什么用 QoS 0 + retain（设计依据）

`status` 与 AI 请求/响应是**性质不同的两类消息**，策略刻意区分：

| 消息 | 语义 | 策略 | 理由 |
|---|---|---|---|
| AI 请求/响应 | 一次性事务（一次诊断，结果只消费一次）| QoS 1 + retain false | 不能丢、不能重复消费；重复靠 `req_id + payload_hash` 幂等去重 |
| `vg/{device_id}/status` | 最新状态值（在线/版本/链路，会不断刷新覆盖）| **QoS 0 + retain true** | 高频覆盖、丢得起；retain 保证订阅方重连即得最新值 |

- **retain 的价值**：状态是"当前值"语义。订阅方（如 Bridge、云端）即使在设备发布时才离线、事后才连上，也能在重连订阅时立刻拿到设备**最后一次发布**的状态，无需等设备下次上报。
- **QoS 0 合理**：状态会周期性/变化时刷新，偶尔丢一两条代价极低，下一条立即覆盖。不值得为这种低频价值、高频覆盖的消息付出 QoS 1 的确认/存储开销。**丢得起，所以用 0。**

### A.2.1 QoS 1 + retain 的取舍（备用方案）

| | **QoS 0 + retain** | **QoS 1 + retain** |
|---|---|---|
| 投递保障 | 至多一次，可能丢、可能乱序 | 至少一次，不丢，但可能重复 |
| 发布确认 | 无 | Broker 确认收到（PUBACK）|
| 在线漏收 | 可能漏中间态 | 基本不漏（除非断连）|
| retain 值的可信度 | 设备最后一次"发出"的消息 | 设备最后一次"被确认"的消息 |
| 成本 | 最低 | 稍高（多一次确认往返）|

- **QoS 0 + retain**：重连能拿到最新值，但实时在线时可能漏收个别中间态。适合 `status`/心跳类。
- **QoS 1 + retain**：既保证实时不漏，又保证 retain 存的"最新值"是已确认到达的。适合**丢不得的关键状态**（如"设备已停机""配置版本变更"）。当前 `status` 摘要类用 QoS 0 足够。

## A.3 必须遵守的边界

- **retain ≠ 在线判定**：retain 消息会一直留存，设备掉线也不会自动清除。订阅方**不能**仅凭收到 retain 状态判断设备在线。
- **在线判定应依赖**：
  1. **遗嘱消息（LWT）**：设备连接时设置 `will`（发布到 `vg/{device_id}/status`，payload 标记离线，retain=true），异常掉线时由 Broker 自动发布，覆盖旧的"在线"状态；
  2. 或**定期心跳 + 超时判离线**（连续 N 个周期未收到即判定离线）。
- **主动清除 retain**：设备正常下线/重启前，应发布**空 payload 的 retain 消息**清除旧状态，避免残留过期的"在线"误导订阅方。
- 该主题的 retain 状态**不应被当作 AI 请求的触发源**；诊断仍需走 `vg/{device_id}/ai/request` 的正常请求流程。
