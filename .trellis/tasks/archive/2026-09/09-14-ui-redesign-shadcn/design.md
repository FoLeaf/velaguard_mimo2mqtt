# 优化云看板 UI 设计 - 技术设计 (design.md)

## 1. 架构与设计原则

保持轻量与现代化：
1. **纯现代原生技术栈（Zero-Build）**：
   - 采用标准 HTML5、现代 CSS（CSS Variables, Flexbox, CSS Grid, clamp, backdrop-filter）、Vanilla JS（ES2020+）。
   - 保持 0 个外部运行时依赖，不引入任何大型 JS 库，不增加构建流水线。
2. **完整复刻 shadcn/ui 设计语言**：
   - 使用与 shadcn/ui 完全一致的色彩系统（Zinc 调色板），支持全局 CSS 变量切换 Dark/Light 模式。
   - 引入精致的微阴影、圆角（radius 0.5rem - 0.75rem）、细微单像素边框（order-border）。
   - 图标使用极简内嵌 SVG（Lucide 风格，尺寸 16x16 / 20x20，stroke-width 2）。
3. **保留服务端只读与流式轮询契约**：
   - 严格兼容现有的 4 个 API 端点：
     - /api/devices
     - /api/devices/{id}
     - /api/devices/{id}/history?point={point}&minutes={minutes}
     - /api/alarms
     - /api/messages?limit={limit}
   - 维持 
enderIfChanged 缓存更新机制，避免全量重建 DOM 导致交互状态丢失。

---

## 2. 组件与视觉设计方案

### 2.1 CSS 变量与设计令牌 (Design Tokens)
定义在 :root（Light Mode）与 .dark（Dark Mode）中：
- 背景与文字：--background, --foreground, --muted, --muted-foreground
- 卡片系统：--card, --card-foreground, --border, --border-hover
- 主题交互：--primary, --primary-foreground, --accent, --ring
- 语义色彩：
  - 成功/正常：--success: #10b981 (Emerald), --success-bg: rgba(16, 185, 129, 0.1)
  - 警告：--warning: #f59e0b (Amber), --warning-bg: rgba(245, 158, 11, 0.1)
  - 危险/告警：--destructive: #ef4444 (Red), --destructive-bg: rgba(239, 68, 68, 0.1)
  - 离线/失联：--offline: #71717a (Zinc 500)

### 2.2 顶部栏与导航 (Header & Navigation)
- 布局：Sticky 顶部，高度 56px，背景透明加高斯模糊（ackdrop-filter: blur(8px)）。
- 左侧：SVG 图标 + 渐变/微发光 VG 标志 + 标题 + 运行模式 Badge。
- 中间：Segmented Pill Tabs（设备总览、告警中心、原始报文），带未读告警红点。
- 右侧：
  - 服务端连接状态 Badge（带呼吸灯脉冲效果）。
  - 主题切换按钮（Sun/Moon 图标微动画）。

### 2.3 设备总览升级 (Fleet Overview)
- **4 大 KPI 指标卡片 (Metrics Grid)**：
  - 卡片 1：设备监控状态（在线数 / 总数，在线率百分比环或条）。
  - 卡片 2：活动告警（当前未恢复告警数量，按严重度区分）。
  - 卡片 3：测点总数（已接入硬件点表中的点位总和）。
  - 卡片 4：报文吞吐（最近接收报文状态与隔离报文占比）。
- **工具栏 (Toolbar)**：
  - 快速搜索框（Input with search icon）。
  - 状态过滤胶囊（全部 / 在线 / 离线 / 告警）。
- **设备卡片 (Device Card)**：
  - 标准 shadcn Card 结构，悬浮上浮与边框微亮动效。
  - 点击跳转详情。

### 2.4 设备详情升级 (Device Detail View)
- 面包屑导航与快捷返回。
- 设备硬件属性标签组（固件、构建模式、网络类型、时间质量、启动时长）。
- 实时点表数据表：
  - 顶置搜索过滤点位功能。
  - 数值着色与单位 Badge。
  - 报警阈值高亮。
- 趋势图表：
  - 类似 Recharts 的专业 SVG 绘图。
  - 渐变填充背景、水平辅助虚线、平滑曲线。
  - 悬浮跟随十字标线与时刻浮层（Tooltip）。
  - 时间跨度快捷切换（5m/30m/1h/6h）。
  - 极值统计（Min / Max / Avg / 最新）。

### 2.5 告警与报文视图 (Alarms & Messages)
- 告警按设备与严重程度展示清晰的 Badge 与时间戳。
- 原始报文控制台：终端暗黑高亮显示 JSON，一键复制载荷按钮。
