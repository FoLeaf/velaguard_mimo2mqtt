# 优化云看板 UI 设计 - 执行计划 (implement.md)

## 1. 执行清单 (Checklist)

- [x] **Step 1: 建立 shadcn/ui 设计系统样式基础 (styles.css)**
  - 定义 Zinc 色系的 CSS 变量系统（:root 亮色与 .dark 暗色）。
  - 编写现代卡片 (card, card-header, card-title, card-content, card-footer)。
  - 编写徽章 (badge, badge-destructive, badge-outline, badge-secondary 等)。
  - 编写按钮与输入框 (btn, btn-outline, input, select, tabs)。
  - 编写现代表格 (table, th, td, table-row-hover)。
  - 编写工具提示 (Tooltip)、空状态 (Empty State)、脉冲圆点 (Pulse Dot) 等组件样式。
  - 编写图表 SVG 样式与网格辅助线。

- [x] **Step 2: 重构 HTML 结构 (index.html)**
  - 引入现代字体栈与 Lucide 风格内嵌 SVG 图标。
  - 升级 Header（品牌 VG 徽标、Segmented Control 导航标签、连接状态徽标、主题切换按钮）。
  - 设备总览视图：加入顶部 4 块 KPI 指标卡骨架、搜索过滤工具栏、设备卡片网格容器。
  - 设备详情视图：加入面包屑导航、设备硬件横幅、点位搜索框、点表容器、升级版趋势图容器。
  - 告警视图与报文视图：升级为现代卡片包裹与清爽布局。

- [x] **Step 3: 升级前端交互与渲染逻辑 (app.js)**
  - 状态管理：增加主题状态 (theme: dark | light)、设备筛选状态 (deviceSearch, deviceFilter)、点表筛选状态 (pointSearch)。
  - 主题切换支持：初始化读取 localStorage，切换时无缝切换 document.documentElement.classList.toggle('dark')。
  - KPI 统计计算与渲染：自动从设备列表、告警列表、测点信息聚合计算在线率、告警数、总测点数并渲染。
  - 设备卡片与点表渲染：增加即时关键字搜索和状态过滤。
  - 趋势图表全面升级：
    - 渲染现代渐变填充（<linearGradient>）。
    - 渲染水平刻度线与网格。
    - 添加鼠标交互层（mousemove / mouseleave 显示指示竖线与浮动 Tooltip）。
    - 计算并展示 Min / Max / Avg / 最新值统计标签。
  - 原始报文体验优化：提供便捷复制 JSON 内容至剪贴板功能（带微动效反馈）。

- [x] **Step 4: 兼容性与视觉质感测试验证**
  - 运行 pytest tests/unit/test_dashboard_http.py 确保所有 HTTP 接口和静态路由 100% 兼容（7 passed）。
  - 运行 pytest -q 全量测试（122 passed, 1 skipped）。
  - 运行 python scripts/demo_dashboard_seed.py 验证联调通过。

---

## 2. 验证命令

` ash
# 1. 运行已有单元测试与合约测试
pytest tests/unit/test_dashboard_http.py -q
pytest tests/unit -q

# 2. 视觉联调与演练
python scripts/demo_dashboard_seed.py
`
