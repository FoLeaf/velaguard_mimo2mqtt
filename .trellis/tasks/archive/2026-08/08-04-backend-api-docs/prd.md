# 当前后端接口文档

## 目标

新增一份面向设备端、调试面板和联调人员的当前后端接口文档，准确描述仓库已经实现的 AI Bridge MQTT 请求/响应契约。

## 范围

- MQTT 连接约定、主题、QoS 和 retained 策略。
- `type=diagnosis` 请求字段、校验规则和 `context` 结构。
- `processing`、`success`、`error` 响应包及错误码。
- `req_id + payload_hash` 的进程内幂等行为。
- Stub、MiMo、fallback 三种当前结果来源及诊断结果 schema。
- 运行配置、MiMo 上游 HTTPS 调用和本地验证方式。
- 明确当前没有 HTTP REST 接口，且未实现的 TTS/ASR/手册解析等能力不写成已实现接口。

## 交付物

- `docs/backend-api.md`：中文 Markdown 文档。
- `README.md`：增加文档入口链接。

## 验收标准

以下各项已于 2026-08-16 逐条对照源码与测试验收通过（发现并修正了 §4.3/§5.1/§5.2 及 README 中过时的英文 stub/fallback 示例文案）：

1. 文档中的主题、QoS、字段名、状态和错误码与当前源码及契约测试一致。
2. 文档明确说明验证失败时只有在能够安全关联 `req_id` 和 `device_id` 时才发布错误响应。
3. 文档明确说明幂等存储为进程内内存实现，重启后状态丢失。
4. 文档明确区分设备可见的 MQTT 契约与 MiMo 私有 HTTPS 上游，且不包含任何真实密钥。
5. 文档不把规划中的接口或仓库外设备能力描述为当前已实现能力。
