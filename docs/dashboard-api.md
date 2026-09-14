# VelaGuard 云看板契约（dashboard-api v1）

> 本文档是云看板（本仓库 `dashboard/`）对**板端上报**与**浏览器访问**两端的完整契约。
> 板端实现方（TeamFalcons 固件仓库）按第 1-2 节实现上报；规范原文见
> `.trellis/spec/backend/mqtt-dashboard-contracts.md` 的
> "Scenario: Dashboard Consumption Contract"（英文，冲突时以 spec 为准）。

## 0. 总览

```text
VelaGuard 板端 ──MQTT──▶ Mosquitto Broker ◀──MQTT 订阅（只读）── 云看板采集服务
                                                            │
                                                    SQLite（状态/告警/点表/遥测）
                                                            │
                                              HTTP（只读 API + 静态网页）◀── 浏览器
```

- 主题根：`vg/{device_id}/...`，无环境前缀。
- 云看板**只读**：不向 `vg/{device_id}/...` 发布任何消息，不能确认/清除告警、不能下发配置（V5 边界）。
- 消息均为 UTF-8 JSON，单条软上限 **64 KiB**。
- 时间约定：设备字段 `ts_ms` / `uptime_ms` / `time_quality` 原样保留；云端只额外记录 `received_ts_ms`。
- 解析宽容：未知字段一律保留透传；非法消息被**隔离**（记录原因，不影响其他消息），服务不崩溃。

## 1. 板端上报主题

| 主题 | 方向 | QoS | Retained | 用途 |
|---|---|---:|---|---|
| `vg/{id}/status` | 板→云 | 0 | **是**（含 LWT） | 设备在线状态 |
| `vg/{id}/telemetry` | 板→云 | 0 | 否 | 周期遥测数组 |
| `vg/{id}/alarm` | 板→云 | 1 | 否 | 告警触发/恢复事件 |
| `vg/{id}/point_table` | 板→云 | 1 | **是** | 点表快照（看板自动同步点表的数据源） |

会话行为：固定 `client_id`、`clean_session=true`、断线重连后重新订阅（云侧）；关键事件（alarm）依赖板端本地 pending 队列补发，MQTT 会话不提供应用层持久化。LWT 发布到 status 主题：`{"device_id":"...","online":false}`（retained）。

## 2. 载荷格式（板端需实现）

### 2.1 status（QoS0，retained）

```json
{"device_id":"vg-xxx","online":true,"firmware":"0.1.0","build_mode":"TEST",
 "network":"rj45","uptime_ms":12345,"ts_ms":1789266000000,"time_quality":"unknown"}
```

- `device_id` 必须与主题中 `{device_id}` 一致；`online` 必须是布尔。
- `network` 约定 `rj45|esp01|none`；`time_quality` 约定 `unknown|rtc|ntp|cloud`；未知值会被保留显示。
- LWT 最小载荷 `{"device_id":"...","online":false}` 合法。

### 2.2 telemetry（QoS0，非保留，建议周期 30 s）

```json
[{"id":"temp","value":36.5,"ok":true,"age_ms":120},
 {"id":"flood","value":0,"ok":true,"age_ms":130}]
```

- 顶层数组；`id` 对应点表中的点位 id；`ok` 缺省视为 `true`；`age_ms` 可省略。
- `value` 支持数字或字符串；点位不在点表中时仍会存储并在看板"点表外实时值"中显示。

### 2.3 alarm（QoS1，非保留）

```json
{"ts":1789266000000,"device_id":"vg-xxx","alarm_id":"vg-xxx-<boot_id>-<seq>",
 "id":"temp","kind":"threshold_high","value":36.5,"thr":35,"state":"raised"}
```

- `state` 必须是 `raised` 或 `cleared`；`id`（或 `sensor_id`）为点位 id；`ts`/`ts_ms` 均可。
- `alarm_id` 建议遵循手册 §16.3 `{device_id}-{boot_id}-{seq}`；缺省时看板以 `(device, 点位, kind)` 作为去重键。
- 重复 `raised` 只刷新 `last_seen`；`cleared` 关闭告警；无在告告警的 `cleared` 只记录事件。
- `ack` 等额外字段原样保留展示，但云端不会确认/清除告警（V5）。

### 2.4 point_table（QoS1，**retained**，板端启动与点表变更时上报）

载荷即 TeamFalcons 设备点表 JSON（`docs/velaguard-host-nsh-protocol.md` §4 格式）：

```json
{"schema_version":1,"bus":{"device":"/dev/rs485","baud":9600},"hits":[1,2],
 "points":[{"id":"temp","name":"温度","addr":1,"fc":3,"reg":0,"qty":1,
            "dtype":"int16","scale":0.1,"unit":"C","cmp":"ge","warn":40,"crit":55,"fail_n":3}]}
```

- `schema_version` 当前必须为 `1`；`points` 非空；`id` 匹配 `[A-Za-z0-9_]{1,23}`。
- `warn`/`crit` 可省略但**不可为 null**（TeamFalcons 规则）。
- retained 语义与 status 相同：配置快照，晚启动的看板能立即取得当前点表。
- 每次上报都会在看板中生成一个点表同步版本记录（含完整 JSON），便于回溯。

## 3. 隔离（quarantine）规则

以下消息不进入业务表，只进入原始报文缓冲并记录原因（`warn` 日志）：

| 原因 | 触发条件 |
|---|---|
| `non_json_payload` / `non_utf8_payload` | 无法解析 |
| `payload_not_object` / `payload_not_array` | 顶层结构错误 |
| `device_id_mismatch` | 主题与载荷 device_id 不一致 |
| `missing_field:*` / `invalid_field:*` / `null_field:*` | 必填缺失/类型错误/null 阈值 |
| `unsupported_schema_version` | 点表 schema_version ≠ 1 |
| `payload_too_large` | 超过 64 KiB（只保留前 512 字节预览） |
| `unknown_topic` / `unknown_kind` | 主题不在看板消费范围 |

## 4. HTTP API（浏览器/运维用，全部只读 GET）

| 端点 | 说明 |
|---|---|
| `GET /` 、`/app.js`、`/styles.css` | 看板静态页（中文，2 s 轮询） |
| `GET /api/devices` | 设备列表：在线状态、固件、网络、活动告警数、点表点位数、最近上报 |
| `GET /api/devices/{id}` | 设备详情：status 原文、点表（自动同步）+ 每点最新值、点表外实时值、点表同步版本 |
| `GET /api/devices/{id}/history?point=<id>&minutes=<n>` | 遥测历史（默认 60 分钟，上限 1440 分钟 / 2000 点） |
| `GET /api/alarms` | 活动告警 + 最近告警事件（默认 200 条） |
| `GET /api/messages?limit=<n>` | 最近原始报文（默认 100，上限 500，含隔离消息与原因） |

无任何写端点；服务不向 MQTT 发布消息。

## 5. 运行

```bash
pip install -e .
# 本地 broker（dev）：docker compose -f deploy/dev/docker-compose.yml up -d mosquitto
vg-dashboard                       # 或 python -m dashboard
# 另开终端：模拟板端
python -m dashboard.tools.synthetic_board --device-id vg-demo01
# 浏览器打开 http://localhost:8080
```

环境变量见 `.env.example`（MQTT 连接使用 `MQTT_*`；看板使用 `HTTP_HOST/HTTP_PORT/DB_PATH/HISTORY_RETENTION_HOURS/MESSAGE_BUFFER_LIMIT/ALARM_EVENT_LIMIT/CLEANUP_INTERVAL_S`）。

看板独立使用 `dashboard/transport/mqtt.py` 和 `dashboard/observability/`，运行时仅需看板配置。MQTT 客户端只订阅显式配置的主题；模拟板端默认不订阅任何主题。

## 6. 已知限制（ MVP 范围）

- 采集服务离线期间的告警依赖板端 pending 队列补发（板端 C1 计划项）；MQTT 会话本身不补发。
- SQLite 为单文件存储，保留期默认 24 小时（遥测历史）；原始报文默认 500 条环形。
- 生产部署需 MQTTS + 每设备凭据 + ACL（对齐 TeamFalcons C2 计划），本仓库 TLS 配置已就绪（`MQTT_TLS` 及证书路径）。
