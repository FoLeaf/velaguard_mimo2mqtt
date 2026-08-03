# VelaGuard 项目手册

## 1. 项目概述

### 1.1 项目名称

VelaGuard：基于 openvela 的工业边缘 AI-Agent 网关

### 1.2 一句话定位

VelaGuard 是一个运行在 STM32H750B-DK 上的独立工业边缘 AI 网关，用于接入 Modbus/工业传感器，完成本地采集、异常告警、自然语言配置、AI 诊断、音频提醒和安全确认。

### 1.3 项目目标

VelaGuard 的目标不是做一个普通 AI 聊天屏幕，而是做一个可以独立运行的工业现场网关：

- 能直接接入工业传感器和设备。
- 能通过 openvela 完成本地 HMI、网络、文件系统和任务管理。
- 能通过 RJ45 或 ESP-01 Wi-Fi 接入云服务器 AI Bridge，并通过 MQTT 请求 MiMo 能力。
- 能用自然语言生成传感器采集配置。
- 能读取传感器用户手册并辅助生成寄存器配置。
- 能在异常发生时主动告警，并给出 AI 诊断建议。
- 能通过本地屏幕和音频提醒现场人员。
- 能保证 AI 不直接控制设备，关键操作必须本地确认。
- 能通过 MQTT-only OTA 完成受控固件升级，支持签名校验、staging 写入和失败回滚。

### 1.4 目标用户

- 小型自动化现场运维人员
- 实验室设备管理员
- 工控/嵌入式系统集成调试人员
- 工业传感器部署和维护人员

### 1.5 核心价值

传统工业网关通常只能采集和转发数据。VelaGuard 在此基础上增加 AI-Agent 能力：

- 把传感器用户手册转换为可执行采集配置。
- 把自然语言需求转换为 Modbus 寄存器采集规则。
- 把原始告警转换为可解释的排查建议。
- 把边缘设备能力封装为可控工具，供 AI 安全调用。
- 在断网或 AI 不可用时仍保留本地告警和基本诊断能力。

## 2. 产品边界

### 2.1 系统形态

VelaGuard 是独立网关，不依赖长期连接电脑运行。

标准运行链路：

```text
工业传感器 / 设备
  ↓ RS485 / Modbus RTU / 可选 CAN
STM32H750B-DK + openvela
  ↓ RJ45 Ethernet 或 ESP-01 Wi-Fi
MQTT Broker / AI Bridge 云服务器
  ↓ HTTPS
MiMo API / TTS / ASR / 云端手册解析服务
```

开发和维护时可以保留 USB CDC 或 UART 调试口，但它不是正式运行依赖。

网络接入采用双模设计：

- RJ45 Ethernet：主网络，优先用于 MQTT、手机局域网访问和大文件下载。
- ESP-01 Wi-Fi：备用网络，用 UART AT 指令或定制固件接入 Wi-Fi。
- USB CDC / UART：只作为调试、日志和救援配置通道，不作为正式运行链路。

无论网络是否可用，VelaGuard 都必须保持本地采集、规则判断、告警弹窗、日志保存和本地告警音可用。AI 诊断、自然语言配置、手册解析和 TTS 属于联网增强能力。OTA 属于受控维护能力，必须复用 MQTT/MQTTS 链路，不要求板端额外引入 HTTPS 下载器。

### 2.2 AI 控制边界

AI 可以做：

- 解析自然语言需求。
- 生成传感器配置建议。
- 解释传感器手册中的寄存器表。
- 生成异常诊断报告。
- 生成巡检报告。
- 推荐排查步骤。

AI 不可以直接做：

- 直接写入寄存器。
- 直接修改采集配置。
- 直接控制执行器。
- 直接关闭告警。
- 直接覆盖本地安全规则。

所有写入类动作必须经过：

```text
AI 生成建议
→ 板端 schema 校验
→ 风险检查
→ LVGL 页面预览
→ 用户本地确认
→ 应用配置或执行动作
```

## 3. 硬件资源

### 3.1 主控平台

| 资源 | 用途 |
|---|---|
| STM32H750B-DK | 主控开发板，运行 openvela |
| Cortex-M7 | 负责采集、规则、UI、网络、JSON 处理 |
| SDRAM | LVGL framebuffer、网络缓冲、AI 响应缓存 |
| QSPI Flash / eMMC | 固件、资源文件、配置、日志、音频片段、OTA staging image |

### 3.2 人机交互资源

| 外设 | 用途 |
|---|---|
| 4.3 寸 LCD | 工业仪表盘、告警详情、AI 诊断报告 |
| 电容触摸屏 | 配置确认、页面切换、告警处理 |
| 板载按键 | 快速确认、返回、静音、调试动作 |
| LED | 正常、告警、联网、采集状态提示 |

### 3.3 工业接入资源

| 外设 | 用途 |
|---|---|
| UART | 连接 RS485 收发器 |
| RS485 模块 | 接入 Modbus RTU 传感器 |
| CAN FD | 可选，用于工业 CAN 或车载协议扩展 |
| GPIO | 告警输出、继电器控制、外部状态输入 |
| I2C / SPI | 可选扩展本地传感器 |

### 3.4 网络资源

| 外设 | 用途 |
|---|---|
| Ethernet RJ45 | 主网络接入，DHCP、DNS、MQTT、手机局域网访问、音频/OTA 分片传输 |
| ESP-01 Wi-Fi 模块 | 备用网络接入，通过 UART AT 指令或定制固件连接云服务器 |
| USB CDC / UART | 调试日志、救援配置、开发期备用通信 |

网络优先级建议：

```text
RJ45 Ethernet 可用
  → 使用 RJ45
RJ45 不可用且 ESP-01 Wi-Fi 可用
  → 使用 Wi-Fi
两者都不可用
  → 进入离线模式，本地采集和告警继续运行
```

### 3.5 音频资源

| 外设 | 用途 |
|---|---|
| 音频 Codec / SAI / I2S | 播放告警音和诊断播报 |
| 本地 WAV/PCM 文件 | 离线告警提示音 |
| 云端 TTS 音频 | 将 AI 诊断文本转换为语音播报 |

音频不是核心判断链路。即使音频不可用，屏幕告警和日志仍必须正常工作。

## 4. 总体架构

### 4.1 架构总览

```text
┌──────────────────────────────────────────────┐
│                手机 / Web 配置端              │
│  自然语言输入 / 上传手册 / 查看设备状态        │
└───────────────────────┬──────────────────────┘
                        │ HTTP / LAN
                        ↓
┌──────────────────────────────────────────────┐
│        STM32H750B-DK + openvela 网关          │
│                                              │
│  ┌──────────────┐  ┌──────────────────────┐  │
│  │  LVGL HMI    │  │  Audio Alert / TTS    │  │
│  └──────┬───────┘  └──────────┬───────────┘  │
│         │                     │              │
│  ┌──────↓─────────────────────↓───────────┐  │
│  │          VelaGuard Agent Runtime        │  │
│  │  Tools / Skills / Safety Guard / JSON   │  │
│  └──────┬──────────────┬──────────────┬───┘  │
│         │              │              │      │
│  ┌──────↓──────┐ ┌─────↓─────┐ ┌─────↓─────┐│
│  │ Rule Engine │ │ Config DB │ │ Event Log ││
│  └──────┬──────┘ └───────────┘ └───────────┘│
│         │                                    │
│  ┌──────↓────────────┐   ┌────────────────┐ │
│  │ Modbus Collector  │   │ NetworkManager │ │
│  └──────┬────────────┘   └───────┬────────┘ │
└─────────┼────────────────────────┼──────────┘
          │ RS485                  │ MQTT
          ↓                        ↓
┌──────────────────┐       ┌──────────────────┐
│ 工业传感器/设备   │       │ AI Bridge 云服务  │
└──────────────────┘       └──────────────────┘
```

### 4.2 板端软件分层

```text
Application Layer
  hmi_app
  sensor_setup_app
  diagnosis_app
  web_config_app

Agent Layer
  vela_agent_runtime
  tool_router
  skill_manager
  safety_guard
  prompt_builder

Service Layer
  modbus_collector
  rule_engine
  sensor_registry
  config_store
  event_store
  audio_service
  network_manager
  mqtt_client
  ota_service

openvela / NuttX Layer
  task / pthread
  file system
  sockets
  mbedTLS
  UART
  Ethernet
  LCD / Touch
  Audio
```

## 5. 功能模块

### 5.1 传感器注册中心

负责管理所有传感器和采集点。

主要能力：

- 新增传感器。
- 删除传感器。
- 启停传感器。
- 查询传感器状态。
- 维护寄存器映射。
- 维护采样周期。
- 维护单位、倍率、数据类型。
- 维护报警规则。

传感器配置示例：

```json
{
  "device_id": "motor_temp_01",
  "name": "Cooling Pump Temperature",
  "protocol": "modbus_rtu",
  "slave_addr": 1,
  "serial": {
    "port": "/dev/ttyS1",
    "baudrate": 9600,
    "parity": "N",
    "data_bits": 8,
    "stop_bits": 1
  },
  "registers": [
    {
      "key": "temperature",
      "label": "Motor Temperature",
      "function_code": 3,
      "addr": 40001,
      "data_type": "int16",
      "scale": 0.1,
      "offset": 0,
      "unit": "C"
    }
  ],
  "poll_interval_ms": 2000,
  "rules": [
    {
      "rule_id": "temperature_high",
      "expr": "temperature > 70",
      "severity": "warning",
      "message": "Motor temperature is too high"
    }
  ]
}
```

### 5.2 Modbus 采集服务

负责从 RS485/Modbus RTU 设备读取数据。

Modbus RTU 协议栈优先基于 nanoMODBUS 实现。nanoMODBUS 只要求用户提供 transport read/write 回调，适合在 openvela/NuttX 上通过串口字符设备完成适配。

主要能力：

- 周期读取 Holding Register。
- 周期读取 Input Register。
- 支持多个寄存器点位。
- 支持倍率和偏移量换算。
- 支持通信失败重试。
- 支持离线检测。
- 支持手动测试读取。
- 将采样结果发布给规则引擎和 UI。

openvela 适配结构：

```text
modbus_collector
  → nanoMODBUS client
  → modbus_port_openvela.c
  → /dev/ttySx
  → UART
  → RS485 transceiver
  → Modbus sensor
```

`modbus_port_openvela.c` 负责：

- 打开串口设备。
- 配置波特率、校验位、停止位。
- 实现 nanoMODBUS 的 read/write 回调。
- 处理读超时和字节超时。
- 控制 RS485 DE/RE 方向脚，或调用系统提供的 RS485 ioctl。
- 在发送后保留必要的总线静默时间。

第一阶段只启用 Modbus client/master 能力。如果不需要板端作为从站，应禁用 nanoMODBUS server 代码以减小体积。

采样数据示例：

```json
{
  "device_id": "motor_temp_01",
  "timestamp": "2026-06-23T10:30:00+08:00",
  "values": {
    "temperature": 82.4
  },
  "quality": "good"
}
```

### 5.3 规则引擎

负责本地实时判断，不依赖云端 AI。

支持规则：

- 超阈值
- 低于阈值
- 通信离线
- 数值突变
- 持续异常
- 恢复正常

规则输出事件：

```json
{
  "event_id": "evt_0001",
  "device_id": "motor_temp_01",
  "type": "threshold_high",
  "severity": "warning",
  "title": "Motor temperature high",
  "current_value": 82.4,
  "rule": "temperature > 70",
  "history": [65.1, 66.0, 72.8, 82.4],
  "timestamp": "2026-06-23T10:30:00+08:00"
}
```

### 5.4 AI-Agent Runtime

负责把本地能力封装成工具，并通过 MQTT 与云服务器 AI Bridge 安全交互。AI Bridge 再调用 MiMo API、TTS、ASR 和手册解析服务。

核心组成：

- `tool_router`：工具调用路由。
- `skill_manager`：加载和管理 Skill。
- `prompt_builder`：构造诊断和配置生成提示词。
- `ai_bridge_client`：通过 MQTT 请求云服务器 AI Bridge。
- `safety_guard`：校验 AI 输出。
- `json_validator`：校验结构化配置。

可用工具：

```text
list_sensors()
read_sensor(device_id)
read_history(device_id, minutes)
get_alarm(event_id)
validate_sensor_config(config_json)
preview_sensor_config(config_json)
apply_sensor_config(config_json)
save_diagnosis(event_id, diagnosis_json)
play_alert_sound(sound_id)
```

写入类工具必须经过本地确认：

```text
apply_sensor_config()
clear_alarm()
set_alarm_rule()
write_device_register()
```

### 5.5 自然语言添加传感器

用户可以通过触摸屏或手机页面输入自然语言。

输入示例：

```text
添加一台 Modbus 温湿度传感器，地址 1，温度寄存器 40001，湿度寄存器 40002，每 2 秒采集一次，温度超过 70 度报警。
```

处理流程：

```text
用户输入自然语言
→ 网关通过 MQTT 请求 AI Bridge
→ MiMo 返回 sensor_config JSON
→ 板端做 schema 校验
→ 板端做风险校验
→ LVGL 显示配置预览
→ 用户点击测试读取
→ 读取成功后用户确认添加
→ 保存配置
→ 开始采集
```

板端必须检查：

- 协议是否合法。
- 从站地址是否合法。
- 寄存器地址是否合法。
- 功能码是否合法。
- 采样周期是否过短。
- 报警阈值是否合理。
- 是否与已有设备冲突。

### 5.6 上传传感器用户手册

用户可以通过手机 Web 页面上传传感器用户手册。

推荐处理方式：

```text
手机上传 PDF / 图片 / 文档
→ 云端手册解析服务
→ 提取通信参数和寄存器表
→ 生成 register_map
→ 网关拉取或接收 sensor_profile
→ 用户选择要采集的字段
→ MiMo 生成最终采集配置
→ 网关校验并确认
```

手册解析结果示例：

```json
{
  "manual_id": "manual_temp_humi_x1",
  "sensor_name": "RS485 Temperature Humidity Sensor",
  "protocol": "modbus_rtu",
  "default_serial": {
    "baudrate": 9600,
    "parity": "N",
    "data_bits": 8,
    "stop_bits": 1
  },
  "register_map": [
    {
      "key": "temperature",
      "label": "Temperature",
      "function_code": 3,
      "addr": 40001,
      "data_type": "int16",
      "scale": 0.1,
      "unit": "C"
    },
    {
      "key": "humidity",
      "label": "Humidity",
      "function_code": 3,
      "addr": 40002,
      "data_type": "int16",
      "scale": 0.1,
      "unit": "%"
    }
  ]
}
```

### 5.7 AI 异常诊断

异常发生后，用户可以点击 AI 诊断。

AI 输入上下文：

- 当前异常事件
- 当前采样值
- 最近历史数据
- 传感器配置
- 报警规则
- 用户手册摘要
- 设备说明

AI 输出结构：

```json
{
  "summary": "电机温度持续超过阈值",
  "risk_level": "medium",
  "possible_causes": [
    "负载过高",
    "散热异常",
    "温度传感器安装松动"
  ],
  "recommended_actions": [
    "检查电机负载是否异常",
    "检查风扇或散热通道",
    "复测温度传感器连接"
  ],
  "need_shutdown": false,
  "confidence": 0.76
}
```

### 5.8 音频提醒与播报

音频功能包括：

- 本地告警提示音。
- 告警等级差异化提示音。
- AI 诊断摘要播报。
- 网络失败或采集失败提示音。

音频链路：

```text
告警发生
→ 播放本地 alert.wav
→ AI 诊断完成
→ 请求云端 TTS 生成音频
→ AI Bridge 通过 MQTT 返回短音频或音频分片
→ audio_service 播放
```

音频策略：

- 告警音必须本地可播放。
- TTS 播报失败不影响屏幕诊断结果。
- 用户可以静音。
- 高等级告警可以重复提示。
- 板端不为 TTS 播放额外引入 HTTPS 下载链路，优先复用 MQTT/MQTTS。

### 5.9 手机远程配置

H750B-DK 通过以太网加入局域网后，可以提供一个轻量 Web 配置入口。

手机端功能：

- 查看当前设备状态。
- 添加传感器。
- 输入自然语言配置。
- 上传用户手册。
- 查看配置预览。
- 查看告警日志。
- 触发 AI 诊断。

手机端的关键操作仍需本地安全策略保护。涉及设备写入或规则变更时，网关屏幕应显示确认页。

### 5.10 日志和报告

系统保存：

- 采样摘要
- 告警事件
- AI 诊断结果
- 配置变更记录
- 手册解析记录
- 网络调用错误
- 用户确认记录

事件日志示例：

```json
{
  "log_id": "log_0001",
  "type": "diagnosis",
  "event_id": "evt_0001",
  "device_id": "motor_temp_01",
  "diagnosis_summary": "电机温度持续超过阈值",
  "created_at": "2026-06-23T10:31:00+08:00",
  "source": "mimo",
  "saved": true
}
```

### 5.11 MQTT-only OTA 固件升级

OTA 用于远程维护 VelaGuard 固件，但不能破坏独立网关和本地安全闭环。OTA 协议采用 MQTT-only 拉取式分片传输，不在 H750B-DK 主流程中引入 HTTPS 固件下载器。

OTA 链路：

```text
云端发布 OTA Offer
→ VelaGuard 收到升级提示
→ UI 显示版本、大小、签名、风险和变更摘要
→ 用户本地确认或进入维护窗口
→ VelaGuard 逐片请求 firmware chunk
→ 云端通过 MQTT 返回 chunk data
→ 板端写入 staging image
→ 校验 sha256 + 数字签名
→ 重启切换新固件
→ 自检通过后 confirm
→ 自检失败则 rollback
```

OTA 约束：

- 固件包不通过 HTTPS 下载。
- 固件包不由云端无节制推送，必须由设备拉取 chunk。
- 每片 chunk 大小建议 4KB 或 8KB。
- 每次只允许有限数量 inflight chunk，避免挤占 Modbus、UI 和告警任务。
- OTA 必须校验 sha256 和数字签名，只有 hash 不够。
- 高等级 active alarm、存储异常、供电不稳或本地安全状态异常时不允许升级。
- 新固件启动后必须完成自检并标记 confirmed，否则回滚。
- OTA 进度、失败原因、确认和回滚都必须写入结构化事件。

## 6. UI 设计

### 6.1 UI 设计原则

- 工业风格，清晰、克制、信息密度适中。
- 首页必须一眼看出设备是否正常。
- 告警和诊断必须比配置入口更突出。
- 不在屏幕上堆长说明文字。
- 所有危险动作必须有二次确认。
- 触摸控件尺寸要适合 4.3 寸屏。
- 状态颜色统一：绿色正常、黄色预警、红色告警、灰色离线、蓝色联网/AI。

### 6.2 页面结构

```text
首页 / 总览
  ├─ 设备详情
  ├─ 实时趋势
  ├─ 告警详情
  │   └─ AI 诊断
  ├─ 添加传感器
  │   ├─ 自然语言输入
  │   ├─ 手册导入结果
  │   └─ 配置预览
  ├─ 日志
  ├─ 系统状态
  └─ OTA 更新
```

### 6.3 首页 / 总览页

显示内容：

- 顶部状态栏：网络、MiMo、采集、音频、时间。
- 设备状态卡片：设备名、当前值、状态、更新时间。
- 告警摘要：当前告警数量、最高告警等级。
- 快捷操作：添加传感器、查看日志、静音。

布局示意：

```text
┌────────────────────────────────────┐
│ VelaGuard   NET OK  MiMo OK  10:30 │
├────────────────────────────────────┤
│ Cooling Pump Motor                 │
│ Temp 82.4 C       WARNING          │
│ Last update: 2s ago                │
├────────────────────────────────────┤
│ Alarms: 1       Highest: Warning   │
├───────────┬───────────┬────────────┤
│ Details   │ Diagnose  │ Add Sensor │
└───────────┴───────────┴────────────┘
```

### 6.4 设备详情页

显示内容：

- 当前值
- 通信质量
- 采样周期
- 寄存器地址
- 阈值规则
- 最近采样时间

### 6.5 实时趋势页

显示内容：

- 最近 1 分钟或 5 分钟曲线。
- 阈值线。
- 异常点标记。
- 当前值大号显示。

### 6.6 告警详情页

显示内容：

- 告警标题。
- 异常类型。
- 当前值和阈值。
- 持续时间。
- 历史值片段。
- 按钮：AI 诊断、静音、标记处理。

### 6.7 AI 诊断页

显示内容：

- 现象摘要。
- 风险等级。
- 可能原因。
- 建议排查步骤。
- 可信度。
- 按钮：保存报告、播放语音、确认已处理。

### 6.8 添加传感器页

输入方式：

- 自然语言添加。
- 从手册添加。
- 手动添加。

自然语言输入页：

```text
┌────────────────────────────────────┐
│ Add Sensor                         │
├────────────────────────────────────┤
│ "添加一台温湿度传感器..."          │
│                                    │
├────────────────────────────────────┤
│ [Generate Config] [Cancel]         │
└────────────────────────────────────┘
```

配置预览页必须显示：

- 设备名称
- 协议
- 从站地址
- 波特率
- 寄存器列表
- 单位和倍率
- 报警规则
- 测试读取结果

按钮：

- 测试读取
- 确认添加
- 返回修改
- 放弃

### 6.9 系统状态页

显示内容：

- IP 地址
- AI Bridge / MiMo 状态
- 最近一次 API 延迟
- RS485 状态
- 文件系统状态
- 音频状态
- 固件版本
- OTA 状态
- 日志容量

## 7. 交互流程

### 7.1 正常采集流程

```text
设备上电
→ openvela 启动
→ 加载配置
→ 初始化网络、LCD、触摸、音频、RS485
→ 启动 Modbus 采集
→ 首页显示实时状态
→ 规则引擎持续判断
```

### 7.2 异常诊断流程

```text
采样值异常
→ 规则引擎生成告警事件
→ UI 弹出告警
→ 播放本地告警音
→ 用户点击 AI 诊断
→ Agent 读取事件、历史、配置、手册摘要
→ 通过 MQTT 请求 AI Bridge
→ 返回结构化诊断
→ UI 显示诊断页
→ 用户保存或播放语音
```

### 7.3 自然语言添加传感器流程

```text
用户输入自然语言
→ 网关通过 MQTT 请求 AI Bridge
→ MiMo 返回候选配置
→ 网关校验配置
→ UI 展示配置预览
→ 用户点击测试读取
→ 读取成功
→ 用户确认添加
→ 配置落盘
→ 传感器进入采集循环
```

### 7.4 上传手册添加传感器流程

```text
手机打开网关 Web 页面
→ 上传传感器手册
→ 云端解析手册
→ 返回寄存器表
→ 用户自然语言选择采集项
→ MiMo 生成配置
→ 网关校验
→ 屏幕预览
→ 用户确认
→ 开始采集
```

### 7.5 音频播报流程

```text
告警触发
→ 播放本地提示音
→ AI 诊断完成
→ 用户点击播放诊断
→ 网关通过 MQTT 请求 TTS 音频
→ AI Bridge 通过 MQTT 返回短音频或音频分片
→ 网关接收后播放
```

### 7.6 MQTT-only OTA 流程

```text
云端发布 OTA Offer
→ 网关通过 MQTT 收到升级信息
→ UI 显示版本、大小、签名和风险
→ 用户本地确认或维护窗口允许升级
→ 网关请求 chunk
→ 云端返回 chunk data
→ 网关写入 staging image
→ 校验 sha256 和数字签名
→ 重启切换新固件
→ 自检通过后 confirm
→ 失败则 rollback 并记录事件
```

## 8. 网络与 API

### 8.1 双模网络管理

网关通过 `network_manager` 统一管理 RJ45 Ethernet 和 ESP-01 Wi-Fi。

`network_manager` 对上层提供统一状态：

```text
NET_DOWN
NET_CONNECTING
NET_ONLINE_RJ45
NET_ONLINE_WIFI
NET_DEGRADED
```

职责：

- 监测 RJ45 link 状态。
- 管理 DHCP、DNS 和 IP 状态。
- 管理 ESP-01 Wi-Fi 连接。
- 在 RJ45 和 Wi-Fi 之间切换活动网络。
- 维护 MQTT 长连接。
- 网络断开后自动重连。
- 向 UI 发布网络状态。
- 向业务层发布 online/offline 事件。

### 8.2 重连策略

网络重连采用指数退避，并设置上限，避免网络故障时持续高频重连。

推荐参数：

```text
初始退避：1 秒
倍率：2
最大退避：60 秒
抖动：±20%
稳定在线 5 分钟后重置退避
```

示例：

```text
1s → 2s → 4s → 8s → 16s → 32s → 60s → 60s ...
```

RJ45 和 Wi-Fi 分别维护退避状态。RJ45 检测到物理 link 恢复时，可以立即触发一次连接尝试；如果失败，再进入退避。

### 8.3 MQTT 与 AI Bridge

VelaGuard 不直接把复杂 MiMo HTTPS API 暴露给板端业务逻辑，而是通过 MQTT Broker 请求云服务器 AI Bridge。

```text
VelaGuard
  ↓ MQTT
MQTT Broker
  ↓ MQTT
AI Bridge
  ↓ HTTPS
MiMo API / TTS / ASR / 手册解析服务
```

板端需要支持：

- DHCP
- DNS
- MQTT 长连接
- MQTT QoS 0/1
- MQTT retained / LWT 状态
- 正式环境 MQTT over TLS；测试环境可在受控局域网使用明文 MQTT
- JSON 请求/响应
- 超时处理
- 重试
- 证书、用户名、密码或设备 Token 配置
- API 调用日志

推荐 Topic：

```text
vg/{device_id}/telemetry
vg/{device_id}/alarm
vg/{device_id}/ai/request
vg/{device_id}/ai/response/{req_id}
vg/{device_id}/tts/request
vg/{device_id}/tts/response/{req_id}
vg/{device_id}/voice/start
vg/{device_id}/voice/chunk/{session_id}
vg/{device_id}/voice/end/{session_id}
vg/{device_id}/voice/result/{session_id}
vg/{device_id}/ota/offer
vg/{device_id}/ota/accept
vg/{device_id}/ota/chunk/request
vg/{device_id}/ota/chunk/data
vg/{device_id}/ota/progress
vg/{device_id}/ota/result
vg/{device_id}/ota/confirm
vg/{device_id}/config/candidate
vg/{device_id}/status
```

### 8.4 MiMo 调用类型

调用场景：

- 自然语言生成传感器配置。
- 手册寄存器表解释。
- 异常诊断。
- 巡检报告。
- TTS 文本生成或音频生成请求。

### 8.5 本地 Web API

用于手机远程访问。

示例接口：

```text
GET  /api/status
GET  /api/sensors
GET  /api/alarms
POST /api/sensors/nl-generate
POST /api/manuals/upload
POST /api/diagnosis/run
POST /api/audio/play
```

手机端提交的配置不能绕过板端安全确认。

### 8.6 MQTT-only OTA 协议

OTA 复用 MQTT/MQTTS，不在板端引入 HTTPS 固件下载。MQTT 负责控制面和固件分片数据面。

推荐消息：

| Topic | 方向 | QoS | retained | 用途 |
|---|---|---:|---|---|
| `vg/{device_id}/ota/offer` | 云端 → 设备 | 1 | 否 | 通知可升级版本 |
| `vg/{device_id}/ota/accept` | 设备 → 云端 | 1 | 否 | 本地确认后接受升级 |
| `vg/{device_id}/ota/chunk/request` | 设备 → 云端 | 1 | 否 | 请求指定 chunk |
| `vg/{device_id}/ota/chunk/data` | 云端 → 设备 | 1 | 否 | 返回固件分片 |
| `vg/{device_id}/ota/progress` | 设备 → 云端 | 1 | 否 | 上报下载、校验、切换进度 |
| `vg/{device_id}/ota/result` | 设备 → 云端 | 1 | 否 | 上报成功、失败或回滚结果 |
| `vg/{device_id}/ota/confirm` | 设备 → 云端 | 1 | 否 | 新固件自检通过后确认 |

OTA Offer 至少包含：

```json
{
  "ota_id": "ota_2026_001",
  "version": "1.2.0",
  "size": 524288,
  "chunk_size": 4096,
  "sha256": "",
  "signature": "",
  "min_bootloader_version": "1.0.0",
  "release_notes": "",
  "risk_level": "low|medium|high"
}
```

设备端必须先确认 `device_id`、固件版本、硬件型号、签名策略和本地安全状态，再进入 chunk 拉取。

## 9. 文件与数据存储

建议目录结构：

```text
/data/velaguard/
  configs/
    sensors.json
    network.json
    rules.json
  skills/
    industrial_fault_diagnosis.md
    sensor_config_generator.md
  manuals/
    manual_index.json
    profiles/
  logs/
    events.log
    diagnosis.log
    api.log
  audio/
    alert_warning.wav
    alert_critical.wav
    tts_cache.wav
  ota/
    staging/
    manifest.json
    rollback.json
```

### 9.1 配置存储原则

- 配置必须 JSON schema 校验。
- 写入前先保存临时文件。
- 写入成功后再替换正式配置。
- 启动时如果配置损坏，回退到最近备份。

### 9.2 日志存储原则

- 日志按大小滚动。
- 告警日志优先保留。
- API 调试日志可裁剪。
- 用户确认记录不可随意覆盖。

### 9.3 OTA 存储原则

- OTA 固件先写入 staging image，不能直接覆盖当前运行固件。
- OTA manifest、chunk 接收进度、校验结果和回滚状态必须可恢复。
- staging image 校验失败时必须删除或标记为 invalid。
- 新固件自检通过前，旧固件必须仍可回滚。
- OTA 写入优先级低于 Modbus 采集、告警 UI 和本地日志。

## 10. Skill 设计

### 10.1 工业异常诊断 Skill

文件名：

```text
/data/velaguard/skills/industrial_fault_diagnosis.md
```

用途：

- 根据传感器事件、历史数据、阈值和设备说明生成诊断建议。

输出格式必须是 JSON：

```json
{
  "summary": "",
  "risk_level": "low|medium|high",
  "possible_causes": [],
  "recommended_actions": [],
  "need_shutdown": false,
  "confidence": 0.0
}
```

### 10.2 传感器配置生成 Skill

文件名：

```text
/data/velaguard/skills/sensor_config_generator.md
```

用途：

- 将自然语言和手册寄存器表转换为传感器配置。

输出格式必须是 JSON：

```json
{
  "device_id": "",
  "name": "",
  "protocol": "modbus_rtu",
  "slave_addr": 1,
  "serial": {},
  "registers": [],
  "poll_interval_ms": 2000,
  "rules": []
}
```

## 11. 安全设计

### 11.1 操作安全

安全原则：

- AI 只生成建议，不直接执行。
- 写入配置必须人工确认。
- 控制设备必须二次确认。
- 高风险操作默认禁用。
- 所有配置变更必须记录日志。

### 11.2 数据安全

需要保护：

- AI Bridge 设备 Token
- 网络配置
- 设备配置
- 用户上传手册
- 诊断日志
- OTA 签名公钥、升级 manifest 和回滚状态

API Key 不应显示在 UI 中。日志中不记录完整密钥。

### 11.3 工业安全

对于可能影响设备运行的动作：

- 显示风险等级。
- 显示变更前后差异。
- 要求本地触摸确认。
- 允许取消。
- 保留回滚配置。

### 11.4 构建模式与 OTA 安全

构建模式分为：

- `test`：允许代码中覆盖 `DEVID`，允许局域网明文 MQTT 调试，允许开发签名 OTA。
- `production`：不开放运行时修改 `device_id` 的接口，默认要求 MQTTS、token、ACL 和生产签名。

OTA 安全要求：

- 生产固件只接受生产签名。
- 签名校验失败不得切换固件。
- 高等级 active alarm 存在时不得开始固件切换。
- OTA 操作必须写入结构化事件。
- OTA 失败必须可回滚或保持当前固件继续运行。

## 12. 异常与降级

### 12.1 网络失败

表现：

- RJ45 未连接或 DHCP 失败。
- ESP-01 Wi-Fi 未连接或云服务器不可达。
- MQTT 断开。
- MiMo / AI Bridge 不可用。
- 手册解析不可用。
- TTS 不可用。

系统行为：

- 本地采集继续。
- 本地规则继续。
- 屏幕告警继续。
- 本地告警音继续。
- 配置和日志继续读写。
- 使用预置诊断模板。
- 显示网络状态异常。
- 进入自动重连状态，并按指数退避重试。
- 将需要联网的诊断、TTS、手册解析请求标记为 pending 或 failed。

### 12.2 Modbus 失败

表现：

- 读取超时。
- CRC 错误。
- 从站无响应。

系统行为：

- 重试。
- 标记通信质量。
- 达到超时阈值后生成离线告警。
- 在测试读取页提示可能原因。

### 12.3 AI 输出非法

表现：

- JSON 格式错误。
- 字段缺失。
- 寄存器地址非法。
- 规则表达式非法。

系统行为：

- 拒绝应用。
- 显示错误原因。
- 允许重新生成。
- 保存调试日志。

### 12.4 音频失败

表现：

- 音频设备初始化失败。
- TTS 下载失败。
- 文件格式不支持。

系统行为：

- 屏幕告警不受影响。
- LED 或本地蜂鸣替代。
- 记录音频错误。

### 12.5 OTA 失败

表现：

- OTA Offer 不合法。
- chunk 丢失或校验失败。
- staging image 写入失败。
- sha256 或签名校验失败。
- 新固件自检失败。

系统行为：

- 拒绝或中止升级。
- 保持当前固件继续运行。
- 标记 staging image 为 invalid。
- 写入 error 日志和 `events.jsonl`。
- 如果已经切换到新固件且自检失败，回滚到上一版固件。
- OTA 失败不得影响本地采集、告警、UI 和日志。

## 13. 典型演示场景

### 13.1 场景一：自然语言添加温度传感器

用户输入：

```text
添加一台 Modbus 温度传感器，从站地址 1，寄存器 40001，倍率 0.1，超过 70 度报警。
```

系统展示配置预览，测试读取成功后开始采集。

### 13.2 场景二：上传手册添加采集项

用户通过手机上传传感器手册，然后输入：

```text
根据手册采集温度和湿度，温度超过 70 度报警，湿度低于 30% 提醒。
```

系统从手册解析结果中找到寄存器表，生成配置，并要求用户确认。

### 13.3 场景三：异常发生并 AI 诊断

传感器温度升高至 82.4 C。

系统行为：

- 首页状态变为黄色或红色。
- 播放告警音。
- 弹出告警详情。
- 用户点击 AI 诊断。
- MiMo 返回原因和排查建议。
- 用户保存诊断报告。

### 13.4 场景四：网络失败降级

断开网络后触发异常。

系统行为：

- 仍然完成本地告警。
- 提示 MiMo 不可用。
- 使用本地模板生成基础建议。
- 网络恢复后可补充 AI 诊断。

### 13.5 场景五：MQTT-only OTA 升级

云端发布一个测试固件 OTA Offer。

系统行为：

- 系统状态页显示可升级版本。
- 用户本地确认升级。
- 设备通过 MQTT 拉取 chunk。
- UI 显示下载、校验和切换进度。
- 校验失败时拒绝升级。
- 自检失败时回滚。

## 14. 项目交付物

项目最终应包含：

- openvela 应用源码。
- LVGL HMI。
- Modbus 采集模块。
- 规则引擎。
- MQTT AI Bridge 客户端。
- 自然语言传感器配置功能。
- 手册解析对接功能。
- AI 诊断 Skill。
- 音频提醒功能。
- MQTT-only OTA 功能。
- 本地 Web 配置页面。
- README。
- 架构图。
- 接线说明。
- 演示视频。
- AI Coding 日志。

## 15. 验收标准

系统应满足：

- H750B-DK 不依赖电脑即可运行主流程。
- 可通过 RS485 读取至少一个 Modbus 设备或模拟器。
- 可通过 RJ45 或 ESP-01 Wi-Fi 连接 MQTT 云服务器。
- 可通过自然语言生成传感器配置。
- 可展示配置预览并要求用户确认。
- 可检测超阈值、离线、突变异常。
- 异常发生时 UI 主动告警。
- 可生成结构化 AI 诊断报告。
- 可保存告警和诊断日志。
- 可播放本地告警音。
- 可通过 MQTT-only OTA 接收升级 offer、拉取 chunk、校验签名并支持回滚。
- MiMo 或网络失败时，本地采集和告警不受影响。
- AI 不能绕过本地确认直接修改配置或控制设备。

## 16. 已确认架构决策补充

本章节记录设计评审中已经收敛的约束，后续实现以本章节为准。

### 16.1 设备身份与 MQTT 鉴权

设备身份规则：

- 量产默认 `device_id = velaguard_{STM32_UID 派生短 ID}`。
- 测试阶段允许在代码中通过 `DEVID` 或等价编译期宏覆盖 `device_id`。
- 量产固件不提供 UI、MQTT、串口 CLI、HTTP 等运行时修改 `device_id` 的接口。
- `display_name` 可修改，仅用于 UI 展示和测试区分，不参与 MQTT 权限边界。

MQTT token 采用带产品密钥的 HMAC 公式生成，不能使用普通 hash：

```text
mqtt_token = base64url(
  HMAC-SHA256(PRODUCT_AUTH_SECRET, "velaguard:mqtt:v1:" + device_id)
)
```

正式环境必须支持 token 版本轮换：

```text
token_v1 = HMAC(PRODUCT_AUTH_SECRET_V1, "velaguard:mqtt:v1:" + device_id)
token_v2 = HMAC(PRODUCT_AUTH_SECRET_V2, "velaguard:mqtt:v2:" + device_id)
```

云端可在迁移期同时接受新旧版本；单台设备泄露时通过 Broker denylist 禁止该 `device_id` 登录。

### 16.2 Broker、AI Bridge 与 MQTT 权限

通信链路固定为：

```text
VelaGuard
  ↓ MQTT
MQTT Broker
  ↓ MQTT
AI Bridge
  ↓ HTTPS
MiMo API / TTS / ASR / 手册解析服务
```

VelaGuard 与 AI Bridge 不直接互连，二者都是 MQTT Broker 的客户端。

正式环境策略：

- MQTT over TLS。
- 每设备独立账号或 token。
- Broker ACL 限制设备只能访问自己的 `vg/{device_id}/...` topic。
- AI Bridge 使用独立账号，只允许订阅请求 topic、发布响应 topic。
- 测试环境可在局域网使用明文 MQTT，但量产固件应关闭。

Topic 根路径使用：

```text
vg/{device_id}/...
```

不增加环境前缀。测试稳定后可通过 reset Broker 或更换 Broker 数据上线。

QoS 策略：

| 类型 | QoS | 说明 |
|---|---:|---|
| `telemetry` | 0 | 常规遥测，允许丢少量数据 |
| `trend` | 0 | 高频趋势数据，优先保持实时性 |
| `status` | 0 | 当前状态，允许用 retained 保存最新值 |
| `alarm` | 1 | 告警事件需要至少送达一次 |
| `ai/request` / `ai/response` | 1 | AI 请求响应需要可重试 |
| `config/candidate` | 1 | 候选配置不能静默丢失 |
| `tts/request` / `tts/response` | 1 | TTS 任务需要明确结果 |
| `voice/start` / `voice/chunk` / `voice/end` / `voice/result` | 1 | 语音上传需要分片确认 |
| `ota/offer` / `ota/chunk` / `ota/result` / `ota/confirm` | 1 | OTA 控制与分片需要可靠送达 |
| `ack/confirm` | 1 | 用户确认类事件需要可靠送达 |

Retained 只用于当前状态类 topic，例如 `vg/{device_id}/status`。请求、响应、事件、遥测、趋势数据不使用 retained。

MQTT 会话策略：

- 固定 `client_id`。
- v1 使用 `clean_session=true`。
- 重连后重新订阅。
- 使用 LWT 发布离线状态。
- 关键事件依赖本地 pending 队列重发，而不是依赖持久 MQTT session。

### 16.3 ID、时间戳与幂等

ID 体系：

- `req_id`：请求级 ID，发起方生成，响应必须原样带回。
- `event_id`：事件级 ID，设备生成并持久递增，云端用它去重。
- `alarm_id`：告警实例 ID，同一个未恢复告警保持同一个 ID，恢复后再次触发才生成新 ID。

推荐格式：

```text
{device_id}-{boot_id}-{seq}
```

其中 `boot_id` 每次启动生成并写入日志，关键事件的 `event_seq` 需要持久化，避免断电后重复。

时间字段统一使用 Unix 毫秒时间戳，并同时记录设备运行时长：

```json
{
  "ts_ms": 1782450000000,
  "uptime_ms": 345678,
  "time_quality": "unknown|rtc|ntp|cloud"
}
```

网络恢复后不回改历史事件时间；云端另存 `received_ts_ms`。

### 16.4 AI Bridge 超时、重试与大 payload

所有 AI 请求必须包含：

- `req_id`
- `device_id`
- `created_ts_ms`
- `type`
- `payload_hash`

AI Bridge 使用 `req_id + payload_hash` 做幂等键。重复请求的处理方式：

- 已完成：重发同一个 response。
- 处理中：返回或发布 `status=processing`。
- 已失败：按失败类型决定是否允许重试。

推荐超时：

| 任务 | 超时 |
|---|---:|
| 自然语言配置 | 15-30 秒 |
| 手册解析 | 60-180 秒，优先异步任务 |
| ASR / TTS | 15-60 秒，按音频长度调整 |

MQTT 只承载控制 JSON、小文本和短结果。音频、PDF、图片、完整手册不塞进单条 MQTT。

H750B-DK 录音上传采用分片：

- 每片 4KB 或 8KB。
- QoS 1。
- payload 优先使用二进制。
- topic 示例：`vg/{device_id}/voice/chunk/{session_id}/{seq}`。
- metadata 包含 `total_chunks`、`sha256`、`duration_ms`、`codec`。

手册/PDF 推荐由手机或 Web 上传到云端，设备只接收解析后的 `manual_profile`。

OTA 固件包属于例外的大 payload，但仍不使用板端 HTTPS 下载。OTA 采用设备拉取式 MQTT 分片，每片 4KB 或 8KB，并限制 inflight chunk 数量。

### 16.5 网络、ESP-01 与启动降级

网络只允许一个活动出口：

- RJ45 优先。
- ESP-01 作为备用链路。
- 不做双链路同时发送。
- RJ45 恢复后需要经过稳定窗口再切回。

ESP-01 约束：

- 独立 3.3V 稳压，峰值按 300-500mA 设计。
- UART 独占，不与 Modbus RTU 共用。
- AT 驱动做成状态机，不阻塞采集任务。
- 失败后指数退避，退避上限可配置。
- 连续失败达到阈值后通过 GPIO 硬复位或断电重启 ESP-01。
- ESP-01 故障只能影响云端能力，不能影响采集、告警、UI 和本地日志。

启动顺序：

```text
最小硬件 / 日志 / 看门狗 / 文件系统
→ 加载配置，失败则默认配置
→ Modbus 采集任务
→ 本地告警规则
→ LVGL UI
→ 本地音频告警
→ network_manager
→ MQTT
→ AI Bridge / 远程配置 / TTS / ASR
```

增强模块失败不能拖垮本地安全闭环。

### 16.6 Modbus 状态与告警模型

Modbus 状态：

- `online`：正常采集。
- `degraded`：有错误但尚未判定离线。
- `offline`：进入低频探测，不清除之前的传感器告警。
- `recovering`：恢复确认模式，恢复全量读取，但需要连续成功后才回到 `online`。

告警模型：

- 系统内部允许多个 active alarm。
- 首页显示最高优先级/主状态。
- 告警详情页展示全部当前告警。
- `acknowledge` 只表示用户已确认，不等于告警恢复。
- 同一个未恢复告警重复触发时更新同一个 `alarm_id`，不创建重复告警。

告警时间字段：

- `first_seen_ts`：首次检测时间。
- `last_seen_ts`：最近一次检测时间。
- `ack_ts`：用户确认时间，可为 `null`。
- `resolved_ts`：实际恢复时间，可为 `null`。

阈值告警采用持续时间窗口，不默认使用回差：

```text
value > threshold 持续 trigger_duration_ms 后触发
value <= threshold 持续 restore_duration_ms 后恢复
```

突变告警采用窗口差值和持续时间：

```text
abs(current - value_N_seconds_ago) >= delta 持续 trigger_duration_ms 后触发
```

### 16.7 日志系统

日志采用 Log4j2-inspired / Minecraft-like rolling logger 风格，不在嵌入式端引入真正 Log4j2。

日志文件：

- `latest.log`：当前人类可读日志。
- `debug.log`：可选 debug 详细日志。
- `archive/*.log`：滚动归档日志。
- `events.jsonl`：结构化业务事件。

日志事件模型：

```text
timestamp + logger/category + level + message + key=value fields
```

日志等级：

- `debug`
- `info`
- `warn`
- `error`

不同输出端可以有不同过滤规则：

- 文件 appender。
- 串口 appender。
- UI appender。
- cloud appender。

云端默认只上传结构化事件和关键 error/warn 摘要，不上传完整 `latest.log`。

### 16.8 配置、文件系统与 UI 确认

配置采用双槽提交：

- `config_a.json`
- `config_b.json`

每份配置包含：

- `schema_version`
- `seq`
- `crc32` 或 `sha256`
- `committed=true`

启动时选择 `seq` 最新且校验通过的配置；都损坏则进入 factory/default 配置。日志允许损坏截断，pending 队列可跳过坏记录，告警状态可从当前传感器值重建。

配置版本：

- 所有配置必须有 `schema_version`。
- 固件声明 `min_supported_schema` 和 `current_schema`。
- 旧版本通过迁移函数升级。
- 未来版本拒绝加载。
- 缺字段用默认值补齐并写 warn 日志。
- 关键字段非法时禁用对应模块，不拖垮全系统。

UI 权限：

- 首页只显示状态和告警，不放危险操作。
- 低风险操作普通确认。
- 中风险操作二次确认。
- 高风险操作长按确认或输入确认码。
- 远程候选配置进入待确认列表，不抢占告警页面。
- 高等级告警存在时 UI 优先展示告警。
- 所有配置变更写入 `events.jsonl`，记录来源：`local_ui`、`remote_candidate`、`factory_default`。

### 16.9 MQTT-only OTA

OTA 采用 MQTT-only pull-based 方案：

- MQTT/MQTTS 同时承担 OTA 控制面和固件 chunk 数据面。
- 不在板端引入 HTTPS 固件下载器。
- 云端只发布 OTA Offer，设备确认后主动请求 chunk。
- 设备端控制 chunk 大小、请求节奏和 inflight 数量。
- 固件写入 staging image，不能直接覆盖当前运行固件。
- 完整镜像必须通过 sha256 和数字签名校验。
- 新固件启动后必须自检并 mark confirmed。
- 新固件未确认或自检失败时必须 rollback。
- OTA 失败不得影响本地采集、告警、UI 和日志。

推荐 OTA topic：

```text
vg/{device_id}/ota/offer
vg/{device_id}/ota/accept
vg/{device_id}/ota/chunk/request
vg/{device_id}/ota/chunk/data
vg/{device_id}/ota/progress
vg/{device_id}/ota/result
vg/{device_id}/ota/confirm
```

### 16.10 测试与量产构建边界

构建模式必须显式区分：

```text
VG_BUILD_MODE=test
VG_BUILD_MODE=production
```

`test` 构建允许：

- 通过代码或编译期宏覆盖 `DEVID`。
- 使用局域网明文 MQTT 调试。
- 输出更详细的 debug 日志。
- 接受开发签名 OTA。

`production` 构建要求：

- `device_id` 从 STM32 UID 派生。
- 不开放运行时修改 `device_id` 的接口。
- 默认使用 MQTTS、token 和 Broker ACL。
- 不在 UI、日志、串口、MQTT payload 中暴露完整 token。
- 只接受生产签名 OTA。
