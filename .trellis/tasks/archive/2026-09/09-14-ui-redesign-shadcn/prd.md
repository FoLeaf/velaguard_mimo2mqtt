# 优化云看板 UI 设计（参考 shadcn-ui）

## 1. 目标 (Goal)

参考 [shadcn/ui](https://github.com/shadcn-ui/ui) 的现代极简设计系统（Zinc / Neutral 色系、精致卡片、现代数据表格、微交互状态指示、KPI 统计卡片、优雅图表等），全面重构与美化 VelaGuard 云看板的前端界面，在**保持零构建、轻量高效、与 Python stdlib HTTP 服务 100% 兼容**的前提下，将简陋的工程看板升级为达到现代企业级 SaaS 质感的工业 IoT 监控控制台。

---

## 2. 现状与已确认事实 (Confirmed Facts)

1. **现有架构**：
   - 前端由 3 个原生静态文件组成：`dashboard/web/index.html`、`dashboard/web/styles.css`、`dashboard/web/app.js`。
   - 后端使用 Python 核心库 `http.server.ThreadingHTTPServer`（定义于 `dashboard/http/server.py`），通过 `_STATIC_FILES` 字典服务静态文件，并通过 REST API（`/api/devices`、`/api/devices/{id}`、`/api/devices/{id}/history`、`/api/alarms`、`/api/messages`）提供数据。
   - 前端采用只读客户端轮询模式（`setInterval(refresh, 2000)`），无写接口（符合 V5 边界）。
2. **测试与兼容性约束**：
   - 单元测试 `tests/unit/test_dashboard_http.py` 严格校验 `/`、`/app.js`、`/styles.css` 的可访问性与状态码 200。
   - 任何改动必须保证纯 Python 环境无需安装 Node/npm 构建流程即可直接启动并正常工作（`python -m dashboard` 与 `python scripts/demo_dashboard_seed.py`）。
3. **现有功能视图**：
   - 视图 1：设备总览（设备网格卡片）。
   - 视图 2：设备详情（设备基本信息、活动告警表、按点表同步实时值、点表外实时值、SVG 趋势图）。
   - 视图 3：告警中心（全局活动告警表、告警历史事件流）。
   - 视图 4：原始报文（最近 100 条 MQTT 报文、隔离报文高亮、JSON 展开）。

---

## 3. 需求范围 (Requirements)

### 3.1 设计系统与主题规范 (shadcn/ui Design Tokens)
- **色系与变量**：引入 shadcn/ui 的 Zinc / Neutral 语义化色彩令牌（CSS Variables）：
  - `--background`、`--foreground`
  - `--card`、`--card-foreground`
  - `--popover`、`--popover-foreground`
  - `--primary`、`--primary-foreground`
  - `--secondary`、`--secondary-foreground`
  - `--muted`、`--muted-foreground`
  - `--accent`、`--accent-foreground`
  - `--destructive`、`--destructive-foreground`
  - `--border`、`--input`、`--ring`、`--radius`
- **精致暗色 / 亮色支持**：默认采用深邃通透的 Zinc 950 暗黑工业质感，同时支持一键切换亮色模式（存储于 `localStorage`）。
- **字体与排版**：采用精美的高级 Sans-serif 字体回退栈（Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei"），紧凑标题（`letter-spacing: -0.02em`）、表格数字全采用等宽对齐（`font-variant-numeric: tabular-nums`）。

### 3.2 顶部全局导航 (Header & Navigation)
- **品牌与状态**：
  - 现代化品牌标志（带渐变质感或精致图标的 `VG` 徽标）+ "VelaGuard 云看板" 标题。
  - 右侧连接状态采用 shadcn 风格的 Status Badge：在线时为微带呼吸动画的祖母绿圆点，断联时为醒目的警示红色。
  - 添加亮色/暗色主题切换按钮（带 Sun/Moon 图标）。
- **导航标签 (Tabs)**：
  - 采用 shadcn Tabs 风格的胶囊/分段切换器（Segmented Control），带平滑过渡背景与活动阴影。
  - 在“告警”导航项上显示动态活动告警数量红点徽标（Badge）。

### 3.3 设备总览视图升级 (Fleet Overview)
- **KPI 统计指标看板 (Metric Summary Cards)**：
  - 顶部增加 4 块现代 Metric Cards（参考 shadcn Dashboard 模板）：
    1. **设备总数 / 在线率**：在线台数、离线台数及百分比进度条。
    2. **活动告警**：严重告警与一般告警数量分布。
    3. **同步测点**：已接入与自动点表同步的总点位数。
    4. **报文吞吐与健康度**：近时接收报文总数与隔离报文数。
- **设备卡片与筛选 (Device Cards & Search)**：
  - 增加即时搜索栏（按 Device ID 搜索）与状态筛选器（全部 / 在线 / 离线 / 告警中）。
  - 设备卡片重构为标准 shadcn `Card` 规范：
    - `CardHeader`：设备 ID、在线/离线状态 Pill、活动告警 Badge。
    - `CardContent`：双列对齐的基础元数据（固件版本、网络形态、运行时长、测点数量、最近上报时间）。
    - `CardFooter`：鼠标悬浮微交互、清晰的“查看设备详情 →”指示。

### 3.4 设备详情视图升级 (Device Detail View)
- **面包屑与设备信息横幅**：
  - 顶部提供清晰的面包屑路径（`设备总览 / {device_id}`）与返回按钮。
  - 设备详情头部集成设备状态、运行参数卡片。
- **实时点表数据展示 (Points Table)**：
  - 采用 shadcn `Table` 样式：精巧表头、行悬停高亮、斑马纹/细微边框。
  - 点位增加快速搜索过滤框（支持按 ID 或名称过滤，测点多时体验极佳）。
  - 数值、单位、状态指示灯精致化，报警阈值（warn/crit）以视觉层级区分。
- **趋势图表升级 (Trend Chart)**：
  - 彻底美化内置 SVG 趋势图，呈现类似 Recharts / shadcn Charts 的现代风格：
    - 平滑曲线与半透明渐变面积填充（Gradient Area Fill）。
    - 精美网格辅助线（Subtle Grid Lines）与坐标刻度。
    - 鼠标悬浮十字准星（Crosshair）与交互 Tooltip（显示具体时刻与数值）。
    - 顶部快捷时间范围胶囊切换（5m / 30m / 1h / 6h）。
    - 图表上方提供 Min / Max / Avg / 最新值统计微卡。

### 3.5 告警视图与原始报文流升级 (Alarms & Messages)
- **告警列表**：
  - 活动告警与历史告警清晰分栏或标签页。
  - 严重级别彩色语义 Badge（Critical: 红色渐变边框，Warning: 琥珀金，Recovered: 翠绿）。
- **原始报文流**：
  - 代码/控制台风格视窗，区分普通报文与隔离报文。
  - 格式化 JSON 预览，增加“一键复制 JSON”便捷按钮。

---

## 4. 验收标准 (Acceptance Criteria)

- [x] **视觉质感**：界面视觉全面达到 shadcn/ui 设计水准（Zinc 色系、精良卡片投影、精致圆角与线条、现代化排版）。
- [x] **零构建与零新依赖**：项目无需 `npm install` 或构建步骤，依然仅由 `index.html`、`styles.css`、`app.js` 构成，直接使用 `python -m dashboard` 或 `python scripts/demo_dashboard_seed.py` 即可完整渲染。
- [x] **功能与交互完整性**：
  - 设备总览具有 4 个 KPI 指标卡，并支持设备卡片搜索与状态过滤。
  - 设备详情点表数据表格样式升级，支持点位搜索。
  - 趋势图具备渐变面积底色、参考网格及悬停 Tooltip 交互。
  - 支持 Dark / Light 模式一键切换。
  - 原始报文提供便捷的 JSON 复制功能。
- [x] **测试与质量**：
  - `pytest` 全部测试通过（122 passed, 1 skipped），不破坏已有 HTTP API 及静态文件服务契约。
  - `node --check dashboard/web/app.js` 语法检测通过；本地 demo 联调脚本验证通过。

---

## 5. 超出范围 (Out of Scope)

- 引入 React / Vue / Next.js 等需要前端打包编译的重型框架。
- 增加后端写接口（严格遵循 V5 只读边界）。
- 更改 MQTT 主题契约与 SQLite 数据库表结构。
