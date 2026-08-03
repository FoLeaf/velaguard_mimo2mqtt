# VelaGuard 推进方案

## 1. 推进原则

本方案以 `VelaGuard_项目手册.md` 为基准，目标是把 VelaGuard 做成一个独立运行的 STM32H750B-DK 工业边缘 AI 网关，而不是依赖电脑 Sidecar 的调试型 Demo。

核心推进原则：

- 先验证硬件和 openvela 关键风险，再扩展 AI 功能。
- 先保证本地采集、告警、UI 可独立闭环，再接入 MiMo。
- 先让 H750B-DK 通过 MQTT 稳定连接云服务器 AI Bridge，再考虑手机远程配置。
- 上传手册、TTS 等重计算能力可以依赖云端轻服务，但板子本身必须保持独立网关形态。
- OTA 复用 MQTT/MQTTS 链路，采用 MQTT-only 拉取式分片传输，不在板端引入 HTTPS 固件下载器。
- 所有 AI 生成结果都必须经过板端校验和用户确认。
- 每一阶段都要能形成可演示状态，避免功能堆到最后才集成。

## 2. 总体路线

推荐按 7 个阶段推进：

```text
阶段 0：环境与基线确认
阶段 1：openvela 独立网关底座与双模网络
阶段 2：工业采集与本地告警闭环
阶段 3：MQTT AI Bridge 与 AI 诊断闭环
阶段 4：自然语言添加传感器
阶段 5：手机远程配置与手册上传
阶段 6：音频、MQTT-only OTA、稳定性、比赛交付打磨
```

总体依赖关系：

```text
openvela + LVGL + RJ45/ESP-01 双模网络 + MQTT
  ↓
Modbus 采集 + 规则引擎 + 日志
  ↓
MQTT AI Bridge + AI 诊断
  ↓
自然语言配置
  ↓
手机 Web + 手册上传
  ↓
音频播报 + MQTT-only OTA + 演示打磨
```

## 3. 阶段 0：环境与基线确认

### 3.1 目标

确认开发环境、openvela 分支、H750B-DK 板级支持、烧录调试链路可用。

### 3.2 关键任务

- 拉取 openvela 大赛指定分支。
- 确认 STM32H750B-DK board config。
- 编译最小固件。
- 烧录运行。
- 串口看到启动日志。
- LCD 显示基础 LVGL 页面。
- 触摸输入可用。
- 确认 QSPI / SDRAM / 文件系统状态。

### 3.3 验收标准

- 固件可稳定启动。
- 屏幕显示一个自定义 VelaGuard 启动画面。
- 触摸事件可以被应用层收到。
- 串口日志可以输出。
- 能读写 `/data/velaguard/` 下的测试文件。

### 3.4 主要风险

| 风险 | 影响 | 应对 |
|---|---|---|
| H750B-DK board config 不完整 | 项目无法进入业务开发 | 先跑官方 LVGL defconfig，再逐步补外设 |
| QSPI / SDRAM 配置问题 | UI 和文件系统不稳定 | 降低 UI 资源复杂度，先保证核心功能 |
| 烧录调试链路不稳定 | 开发效率低 | 固定一种稳定烧录方式和串口日志方式 |

## 4. 阶段 1：openvela 独立网关底座与双模网络

### 4.1 目标

让 H750B-DK 具备独立联网、基础 UI、配置读写、系统状态展示和 MQTT 云端连接能力。网络接入同时支持 RJ45 Ethernet 和 ESP-01 Wi-Fi。

### 4.2 关键任务

#### 网络

- 启用 RJ45 Ethernet。
- 接入 ESP-01 Wi-Fi 模块。
- 支持 DHCP 获取 IP。
- 支持 DNS。
- 支持 MQTT 连接云服务器。
- 支持 MQTT QoS 0/1。
- 支持 MQTT LWT 在线状态。
- 支持网络断开自动重连。
- 实现指数退避重连，设置最大退避上限。
- 实现基础 `network_manager`。

#### 网络优先级

- RJ45 可用时优先使用 RJ45。
- RJ45 不可用时切换 ESP-01 Wi-Fi。
- 两者都不可用时进入离线模式。
- 离线模式下 Modbus 采集、规则引擎、告警、日志、本地音频必须继续运行。

#### UI

- 实现首页状态栏。
- 显示网络状态、IP、采集状态、MiMo 状态。
- 实现系统状态页。

#### 存储

- 建立 `/data/velaguard/` 目录结构。
- 实现 `config_store`。
- 支持 JSON 配置读写。
- 支持配置损坏时回退默认配置。

### 4.3 验收标准

- 网关插网线后能自动获取 IP。
- 网关能通过 RJ45 连接 MQTT Broker。
- 拔掉网线后，系统能切换到 ESP-01 Wi-Fi 并恢复 MQTT。
- RJ45 和 Wi-Fi 都不可用时，UI 显示离线状态，但本地功能继续运行。
- 网络重连符合指数退避策略，最大退避不超过配置上限。
- UI 能显示网络模式、IP、MQTT 状态和最近重连次数。
- 重启后配置仍能保留。

### 4.4 阶段产物

- `network_manager`
- `ethernet_bearer`
- `esp01_wifi_bearer`
- `mqtt_client`
- `config_store`
- `hmi_app` 基础框架
- 系统状态页
- 基础配置文件

### 4.5 主要风险

| 风险 | 影响 | 应对 |
|---|---|---|
| Ethernet 驱动启用困难 | 主网络不可用 | 保留 ESP-01 Wi-Fi 备用网络，但仍优先修复 RJ45 |
| ESP-01 AT 链路不稳定 | Wi-Fi 备用网络不可靠 | 将 ESP-01 封装为独立 bearer，失败不影响 RJ45 |
| MQTT/TLS 内存占用高 | 云端连接不稳定 | 控制 payload 大小，保持单连接，必要时先使用内网 MQTT 验证 |
| JSON 解析内存压力 | 配置和 API 易崩 | 使用固定大小 buffer 和字段白名单 |

## 5. 阶段 2：工业采集与本地告警闭环

### 5.1 目标

实现不依赖 AI 的本地工业网关能力：Modbus 采集、规则判断、告警弹窗、日志保存。

### 5.2 关键任务

#### Modbus 采集

- 接入 RS485 模块。
- 基于 nanoMODBUS 实现 Modbus RTU 主站。
- 编写 `modbus_port_openvela.c` 适配层。
- 用 openvela/NuttX 串口字符设备实现 nanoMODBUS read/write 回调。
- 处理 RS485 DE/RE 方向控制。
- 支持读取 Holding Register。
- 支持读取 Input Register。
- 支持倍率、单位、数据类型转换。
- 支持读取失败重试。
- 支持通信离线判断。

#### 规则引擎

- 实现超阈值检测。
- 实现通信离线检测。
- 实现数值突变检测。
- 实现告警恢复。

#### UI

- 实现设备总览页。
- 实现设备详情页。
- 实现实时趋势页。
- 实现告警弹窗。
- 实现告警详情页。

#### 日志

- 保存告警事件。
- 保存最近历史采样摘要。
- 保存用户处理记录。

### 5.3 验收标准

- 能读取至少 1 个 Modbus 设备或模拟器的 1-3 个寄存器。
- 采样值每 1-2 秒刷新。
- 手动注入超阈值后，UI 主动弹出告警。
- 断开 RS485 后，系统能生成离线告警。
- 告警日志重启后仍可查看。
- 即使没有网络，本地采集和告警仍然正常。

### 5.4 阶段产物

- `modbus_collector`
- `modbus_port_openvela.c`
- `sensor_registry`
- `rule_engine`
- `event_store`
- 设备总览页
- 告警详情页
- 实时趋势页

### 5.5 主要风险

| 风险 | 影响 | 应对 |
|---|---|---|
| nanoMODBUS 在 openvela 上未直接适配 | Modbus 采集开发受阻 | 只补 transport 回调和串口配置，不改 nanoMODBUS 核心 |
| RS485 硬件接线不稳定 | 采集不可靠 | 准备真实传感器和 Modbus 模拟器两套方案 |
| Modbus 地址/功能码混乱 | 读取失败 | UI 中提供测试读取页 |
| 规则误报 | 演示体验差 | 规则先做简单、可解释、可手动注入 |

## 6. 阶段 3：MQTT AI Bridge 与 AI 诊断闭环

### 6.1 目标

网关通过 MQTT 向云服务器 AI Bridge 发送 AI 请求，由云服务器调用 MiMo API，并将结构化诊断结果通过 MQTT 返回网关。

### 6.2 关键任务

#### MQTT AI 客户端

- 实现 `ai_bridge_client`。
- 支持 `ai/request` 和 `ai/response/{req_id}`。
- 支持请求 ID、超时、重试和去重。
- 支持 MQTT 断线后的请求失败处理。
- 支持响应 JSON 提取。

#### 云服务器 AI Bridge

- 接收 VelaGuard MQTT 请求。
- 调用 MiMo API。
- 调用 TTS / ASR / 手册解析服务。
- 缓存常见 fallback 响应。
- 将结果发布回 VelaGuard。
- MiMo API Key 只保存在云服务器。
- 支持超时、重试和错误码处理。

#### Agent Runtime

- 实现 `tool_router`。
- 实现 `prompt_builder`。
- 实现 `skill_manager`。
- 实现 `safety_guard`。
- 实现 `json_validator`。

#### 诊断 Skill

- 编写 `industrial_fault_diagnosis.md`。
- 约束 MiMo 输出固定 JSON。
- 将事件、历史值、规则和设备说明拼成上下文。

#### UI

- 实现 AI 诊断页。
- 支持诊断中、成功、失败、降级四种状态。
- 支持保存诊断报告。

### 6.3 验收标准

- 用户点击 `AI 诊断` 后，网关发布 MQTT AI 请求。
- 云服务器调用 MiMo 后发布结构化诊断 JSON。
- UI 显示现象、风险等级、可能原因、建议步骤。
- MiMo 或云服务器失败时，系统使用本地 fallback 模板。
- 诊断结果可以保存到日志。

### 6.4 阶段产物

- `ai_bridge_client`
- 云服务器 `ai_bridge`
- `vela_agent_runtime`
- `industrial_fault_diagnosis.md`
- AI 诊断页
- 诊断日志

### 6.5 主要风险

| 风险 | 影响 | 应对 |
|---|---|---|
| MiMo API 延迟高 | 诊断等待时间长 | 云服务器设置超时，UI 显示进度，准备 fallback |
| AI 输出不是合法 JSON | 配置和诊断不可用 | 强 schema 校验，非法则拒绝 |
| MQTT 响应丢失 | 诊断请求无结果 | 使用 req_id、QoS 1、超时和重试 |

## 7. 阶段 4：自然语言添加传感器

### 7.1 目标

用户通过自然语言让网关生成传感器配置，并经本地确认后开始采集。

### 7.2 关键任务

#### 配置生成

- 编写 `sensor_config_generator.md` Skill。
- 定义传感器配置 JSON schema。
- 调用 MiMo 生成候选配置。
- 实现配置字段白名单。
- 实现配置风险检查。

#### UI

- 实现添加传感器页。
- 实现自然语言输入页。
- 实现配置预览页。
- 实现测试读取页。
- 实现确认添加流程。

#### 采集接入

- 新配置写入 `sensor_registry`。
- 配置落盘。
- Modbus 采集服务动态加载新设备。

### 7.3 验收标准

用户输入：

```text
添加一台 Modbus 温度传感器，从站地址 1，寄存器 40001，倍率 0.1，超过 70 度报警。
```

系统应做到：

- 生成合法 JSON 配置。
- UI 展示配置预览。
- 用户可以测试读取。
- 测试成功后确认添加。
- 新传感器进入采集总览。
- 异常规则生效。

### 7.4 阶段产物

- `sensor_config_generator.md`
- 添加传感器页
- 配置预览页
- 测试读取页
- 动态传感器注册流程

### 7.5 主要风险

| 风险 | 影响 | 应对 |
|---|---|---|
| AI 生成配置不准确 | 读取失败 | 必须测试读取后才能保存 |
| 自然语言歧义 | 配置错误 | UI 显示缺失字段，要求用户补充 |
| 动态配置影响采集稳定性 | 系统异常 | 新配置先沙箱测试，再进入正式采集 |

## 8. 阶段 5：手机远程配置与手册上传

### 8.1 目标

通过手机访问 H750B-DK 网关，实现远程查看、自然语言添加传感器、上传手册并生成配置。

### 8.2 关键任务

#### 本地 Web 服务

- 实现轻量 HTTP server。
- 提供手机 Web UI。
- 提供状态查询 API。
- 提供传感器查询 API。
- 提供告警查询 API。
- 提供自然语言生成接口。

#### 手册上传

- 手机上传 PDF/图片/文档。
- 网关将文件转发给云端手册解析服务，或上传到云端获取 `manual_id`。
- 云端返回 `sensor_profile`。
- 网关保存手册解析结果。
- 用户选择采集项。
- 调用 MiMo 生成最终配置。

#### 安全确认

- 手机端可以提交配置建议。
- 关键配置变更仍需板端 LVGL 确认。
- UI 显示远程请求来源。

### 8.3 验收标准

- 手机浏览器能打开网关页面。
- 手机能查看当前传感器和告警。
- 手机能输入自然语言添加传感器。
- 手机能上传用户手册。
- 系统能从手册解析结果生成候选配置。
- 板端屏幕显示配置确认页。
- 未经板端确认，配置不能正式生效。

### 8.4 阶段产物

- 本地 Web UI
- 本地 Web API
- 手册上传接口
- `manual_profile` 存储
- 远程配置确认流程

### 8.5 主要风险

| 风险 | 影响 | 应对 |
|---|---|---|
| MCU 处理上传文件压力大 | 系统卡顿 | 文件只做转发或限制大小，解析放云端 |
| 手机 Web UI 占资源 | 影响采集 | 页面保持轻量，避免复杂前端框架 |
| 远程配置安全风险 | 误操作 | 板端二次确认强制保留 |

## 9. 阶段 6：音频、MQTT-only OTA、稳定性、比赛交付打磨

### 9.1 目标

完善告警音、AI 诊断播报、MQTT-only OTA、系统稳定性、演示脚本、README、视频和答辩材料。

### 9.2 关键任务

#### 音频

- 播放本地告警 WAV/PCM。
- 支持静音。
- 支持不同告警等级不同音效。
- 支持 AI 诊断文本转 TTS 音频并播放。
- 音频失败时不影响 UI 和告警。
- TTS 音频优先通过 MQTT/MQTTS 短音频或分片返回，不在板端引入额外 HTTPS 下载链路。

#### MQTT-only OTA

- 实现 OTA Offer 接收和 UI 展示。
- 实现本地确认或维护窗口策略。
- 实现 `ota/accept`、`ota/chunk/request`、`ota/chunk/data`、`ota/progress`、`ota/result`、`ota/confirm` 消息。
- 实现设备拉取式 chunk 下载，限制 chunk size 和 inflight 数量。
- 写入 staging image 或 staging 文件。
- 校验 sha256 和数字签名。
- 校验失败时拒绝升级并记录 error 事件。
- 支持新固件自检确认和失败回滚；如果当前 bootloader/分区条件不足，至少完成协议状态机、staging 校验和回滚状态记录。
- OTA 不得阻塞 Modbus 采集、告警 UI、本地日志和本地告警音。

#### 稳定性

- 连续采集测试。
- 断网恢复测试。
- Modbus 断连恢复测试。
- AI Bridge / MiMo API 超时测试。
- 配置损坏恢复测试。
- OTA chunk 丢失、校验失败、签名失败、下载中断和回滚测试。
- 多次异常注入测试。

#### 演示

- 固定 5 分钟演示脚本。
- 准备真实传感器方案。
- 准备 Modbus 模拟器方案。
- 准备网络失败降级演示。
- 准备一键重置演示状态。

#### 交付材料

- README。
- 架构图。
- 接线说明。
- API 说明。
- Skill 文件。
- AI Coding 日志。
- 演示视频。
- PPT。

### 9.3 验收标准

- 本地告警音可播放。
- AI 诊断可选择语音播报。
- MQTT-only OTA 可完成 offer、确认、chunk 拉取、staging 写入、hash/signature 校验、进度上报和失败处理。
- Demo 连续完整演示 5 次不失败。
- 网络断开时本地采集和告警不中断。
- MiMo 不可用时 fallback 诊断可用。
- OTA 失败不影响本地采集、告警、UI 和日志。
- 项目文档能让评委快速理解 openvela 使用点、AI 使用点和硬件工程量。

### 9.4 阶段产物

- `audio_service`
- `ota_service`
- 本地音频资源
- OTA 测试固件包或测试 staging image
- 演示脚本
- README
- PPT
- 视频素材
- 测试记录

## 10. 推荐时间安排

假设从 2026-06-23 开始，比赛提交截止按 2026-09-20 计算，建议留出最后一周作为不可动用缓冲。

| 时间 | 阶段 | 目标 |
|---|---|---|
| 2026-06-23 至 2026-06-30 | 阶段 0 | openvela、烧录、LVGL、文件系统基线 |
| 2026-07-01 至 2026-07-14 | 阶段 1 | RJ45/ESP-01 双模联网、MQTT、配置存储、系统状态页 |
| 2026-07-15 至 2026-07-31 | 阶段 2 | nanoMODBUS 采集、本地规则、告警 UI、日志 |
| 2026-08-01 至 2026-08-12 | 阶段 3 | MQTT AI Bridge、AI 诊断、Skill、fallback |
| 2026-08-13 至 2026-08-25 | 阶段 4 | 自然语言添加传感器、配置预览、测试读取 |
| 2026-08-26 至 2026-09-05 | 阶段 5 | 手机 Web、手册上传、远程配置确认 |
| 2026-09-06 至 2026-09-13 | 阶段 6 | 音频、MQTT-only OTA、稳定性、演示脚本、文档 |
| 2026-09-14 至 2026-09-20 | 缓冲与提交 | 只修 bug、录视频、整理提交材料 |

## 11. 关键技术门槛与决策点

### 11.1 双模网络 / MQTT 是否可用

这是项目能否作为独立网关的第一关键门槛。

通过标准：

- RJ45 DHCP 成功。
- RJ45 MQTT 连接成功。
- ESP-01 Wi-Fi 连接成功。
- ESP-01 MQTT 连接成功。
- RJ45 和 Wi-Fi 切换后业务能恢复。
- 网络故障后指数退避重连生效。
- 连续 MQTT 请求/响应不崩溃。

如果不通过：

- 优先修 RJ45 和 MQTT。
- ESP-01 作为备用网络，不替代 RJ45 主链路。
- USB CDC 只作为开发期调试和临时 fallback。

### 11.2 Modbus 采集是否稳定

这是工业网关身份的核心。

通过标准：

- 连续读取稳定。
- 通信失败可恢复。
- 异常能触发本地规则。

如果不通过：

- 减少设备数量。
- 先只做一个传感器。
- 准备 Modbus 模拟器。

### 11.3 MiMo 输出是否可控

AI 输出必须结构化且可校验。

通过标准：

- 输出 JSON 稳定。
- 缺字段可识别。
- 非法配置会被拒绝。

如果不通过：

- 收紧 prompt。
- 减少输出字段。
- 使用模板化 JSON。

### 11.4 音频驱动是否可控

音频是加分项，不应拖垮主线。

通过标准：

- 可播放本地短音频。
- TTS 失败不影响告警。

如果不通过：

- 保留屏幕告警。
- 改用蜂鸣器或 LED。
- 不让音频成为 Demo 必要条件。

### 11.5 MQTT-only OTA 是否可控

OTA 是维护能力，不应拖垮主线。优先验证协议闭环和安全校验，再考虑真实固件切换深度。

通过标准：

- 能收到 OTA Offer。
- 能在 UI 上显示版本、大小、签名和风险。
- 能本地确认后发起 OTA。
- 能按 chunk request/data 拉取 staging image。
- 能校验 sha256 和数字签名。
- 能上报 progress/result/confirm。
- 校验失败或中断时能安全失败，不影响本地采集和告警。

如果不通过：

- 保留 MQTT-only OTA 协议状态机和 staging 校验演示。
- 暂不把真实固件切换作为比赛主演示依赖。
- 不退回板端 HTTPS 下载方案。
- 不让 OTA 阻塞最小可演示闭环。

## 12. 最小可演示闭环

无论后续功能多少，最小可演示闭环必须始终保持可运行：

```text
H750B-DK 上电
→ openvela 启动
→ LVGL 首页显示设备状态
→ Modbus 读取温度
→ 注入温度超限
→ UI 弹出告警
→ 播放本地告警音
→ 点击 AI 诊断
→ H750B-DK 通过 MQTT 请求 AI Bridge
→ 显示诊断报告
→ 保存日志
```

这个闭环是比赛演示的主线，任何新增功能都不能破坏它。

## 13. 功能优先级

### 13.1 必须完成

- openvela 启动
- LVGL UI
- RJ45 Ethernet 联网
- ESP-01 Wi-Fi 备用联网
- MQTT 云端连接
- Modbus 采集
- 本地规则引擎
- 告警弹窗
- AI 诊断
- 诊断日志
- 本地告警音
- MQTT-only OTA 协议闭环
- 自定义 Skill

### 13.2 强烈建议完成

- 自然语言添加传感器
- 配置预览
- 测试读取
- 手机 Web 状态页
- 网络失败 fallback
- MiMo 输出 schema 校验
- OTA staging 校验和失败回滚状态记录

### 13.3 加分功能

- 上传用户手册并生成配置
- AI 诊断 TTS 播报
- 真实固件双槽切换与自动回滚演示
- 多传感器趋势图
- CAN FD 扩展
- 多节点协同
- 巡检报告

### 13.4 明确不应优先投入

- 复杂语音识别
- 多协议全平台化
- 大型前端页面
- AI 直接控制执行器
- 复杂 PDF 本地解析
- 过度抽象的通用 Agent 框架

## 14. 每周工作节奏建议

每周保持固定产出：

- 一个可运行固件。
- 一个演示视频片段。
- 一份问题清单。
- 一份 AI Coding 日志。
- 一次风险复盘。

每次新增功能必须回答：

- 是否仍能独立运行？
- 是否影响最小演示闭环？
- 是否需要本地确认？
- 是否能在 UI 上被评委看懂？
- 是否体现 openvela 能力？
- 是否复用既有 MQTT/MQTTS 链路，避免新增板端 HTTPS 复杂度？

## 15. 最终演示结构

推荐 5 分钟演示顺序：

```text
0:00 - 0:30  项目定位：独立工业边缘 AI 网关
0:30 - 1:20  自然语言添加传感器或展示已配置设备
1:20 - 2:10  Modbus 实时采集和趋势显示
2:10 - 3:00  注入异常，屏幕主动告警，播放告警音
3:00 - 4:00  点击 AI 诊断，MiMo 返回结构化报告
4:00 - 4:30  展示日志、Skill、openvela 使用点
4:30 - 5:00  展示网络失败 fallback、手机远程配置或 MQTT-only OTA offer
```

演示时必须强调：

- H750B-DK 独立运行。
- openvela 承担图形、网络、文件系统和应用框架。
- AI 不是聊天壳，而是参与配置生成和故障诊断。
- 本地规则和安全确认保证工业现场可靠性。

## 16. 贯穿性验收约束

以下约束不绑定某一个阶段，而是贯穿所有开发和演示验收。

### 16.1 独立网关约束

VelaGuard 必须始终满足：

- H750B-DK 不依赖长期连接电脑运行。
- USB CDC / UART 只作为开发调试和救援通道。
- 网络、MQTT、AI Bridge、MiMo、TTS、ASR 不可用时，本地采集、规则告警、LVGL、日志、本地告警音仍可运行。
- 新增功能不得阻塞 Modbus 采集任务和本地告警任务。

### 16.2 身份与安全约束

- 量产 `device_id` 从 STM32 UID 派生。
- 测试阶段可通过代码里的 `DEVID` 覆盖。
- 量产固件不开放运行时修改 `device_id` 的接口。
- MQTT token 使用 `HMAC(PRODUCT_AUTH_SECRET, device_id)` 派生，不能使用纯 hash。
- 正式环境必须使用 MQTT over TLS、每设备 token、Broker ACL。
- token 公式必须带版本号，云端支持新旧 token 迁移和单设备 denylist。

### 16.3 MQTT 与 AI Bridge 约束

- VelaGuard 只连接 MQTT Broker，不直接调用 MiMo HTTPS API。
- AI Bridge 作为独立服务订阅 Broker，请求 MiMo/TTS/ASR/手册解析后再发布 MQTT 响应。
- Topic 根路径固定为 `vg/{device_id}/...`，不加环境前缀。
- `status` 可 retained；请求、响应、告警、遥测、趋势不 retained。
- 高频趋势和普通遥测使用 QoS 0。
- 告警、AI 请求响应、候选配置、TTS、语音分片、OTA、确认事件使用 QoS 1。
- v1 使用固定 `client_id`、`clean_session=true`、LWT、重连后重新订阅。

### 16.4 离线、重连与 ESP-01 约束

- 网络采用单活动链路，RJ45 优先，ESP-01 备用，不做双链路同时发送。
- 断网后指数退避重连，退避上限可配置。
- RJ45 恢复后需要稳定窗口再切回。
- ESP-01 独立供电、独占 UART、AT 状态机驱动。
- ESP-01 连续失败后支持 GPIO 硬复位或断电重启。
- ESP-01 故障不得影响 RJ45、Modbus、本地告警和 UI。

### 16.5 日志、事件与时间约束

- 日志采用 Log4j2-inspired / Minecraft-like rolling logger 风格。
- 保留 `latest.log`、可选 `debug.log`、`archive/*.log`、`events.jsonl`。
- 日志等级至少包括 `debug`、`info`、`warn`、`error`。
- 不同输出端可设置不同最小等级和 category filter。
- 事件必须带 `ts_ms`、`uptime_ms`、`time_quality`。
- 网络恢复后不回改历史事件时间，云端另存 `received_ts_ms`。
- `req_id`、`event_id`、`alarm_id` 必须支持重试、去重和重启后追踪。

### 16.6 告警与 Modbus 状态约束

- 系统内部允许多个 active alarm。
- 首页显示最高优先级状态，详情页展示全部告警。
- `ack` 不等于 `resolved`。
- 同一未恢复告警更新同一个 `alarm_id`。
- 阈值告警使用触发持续时间和恢复持续时间，不默认使用回差。
- Modbus 状态至少包括 `online`、`degraded`、`offline`、`recovering`。
- `offline` 仍执行低频探测；`recovering` 是连续成功确认模式。

### 16.7 配置与文件系统约束

- 配置采用双槽提交和校验字段。
- 所有配置带 `schema_version`。
- 固件负责旧版本迁移、未来版本拒绝、缺字段补默认并写 warn。
- AI 生成的候选配置必须经设备端 schema 校验、风险检查、测试读取和本地确认。
- 测试读取失败的配置只能保存为 disabled draft，不能 active。
- 文件系统损坏时，日志可截断、pending 队列可跳坏记录、告警状态可重建。

### 16.8 UI 与误操作约束

- 首页只展示状态和告警，不放危险操作。
- 配置操作进入设置或配置页。
- 低风险操作普通确认，中风险二次确认，高风险长按确认或确认码。
- 远程配置只进入候选列表，不抢占告警页面。
- 高等级告警存在时，UI 优先展示告警。
- 所有配置变更写入结构化事件，并记录来源。

### 16.9 MQTT-only OTA 约束

- OTA 采用 MQTT-only pull-based 方案，不在板端引入 HTTPS 固件下载器。
- 云端只发布 OTA Offer，设备本地确认后主动请求 chunk。
- OTA chunk 大小和 inflight 数量必须受控，不能挤占 Modbus、UI、告警和日志任务。
- OTA 固件先写入 staging image 或 staging 文件，不能直接覆盖当前运行固件。
- OTA 必须校验 sha256 和数字签名。
- 校验失败、中断、写入失败或自检失败时必须安全失败或回滚。
- OTA 失败不得影响本地采集、告警、UI 和日志。
- 生产构建只接受生产签名；测试构建可以接受开发签名。

### 16.10 测试与量产构建约束

- 构建模式必须显式区分 `VG_BUILD_MODE=test` 和 `VG_BUILD_MODE=production`。
- `test` 构建允许代码中覆盖 `DEVID`、局域网明文 MQTT、详细 debug 日志和开发签名 OTA。
- `production` 构建从 STM32 UID 派生 `device_id`，不开放运行时修改接口。
- `production` 构建默认使用 MQTTS、token、Broker ACL 和生产签名 OTA。
- 完整 token、产品密钥、MiMo API Key、OTA 私钥不得出现在 UI、日志、串口输出或 MQTT payload 中。
