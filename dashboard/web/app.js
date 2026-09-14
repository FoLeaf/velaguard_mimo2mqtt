/* VelaGuard 云看板前端：只读轮询，无构建步骤。
 * 设计规范：shadcn/ui 现代设计语言
 */
"use strict";

const POLL_MS = 2000;
const state = {
  view: "devices",
  deviceId: null,
  devices: [],
  detail: null,
  alarms: { active: [], events: [] },
  messages: [],
  connFail: false,
  deviceSearch: "",
  deviceFilter: "all",
  pointSearch: "",
  trendSamples: [],
  trendMinutes: 30,
};

const $ = (id) => document.getElementById(id);

/* --------------------------------------------------------------------------
   1. 基础辅助函数
   -------------------------------------------------------------------------- */
function fmtTime(ms) {
  if (!ms) return "-";
  const d = new Date(ms);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function fmtTimeShort(ms) {
  if (!ms) return "-";
  const d = new Date(ms);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function fmtUptime(ms) {
  if (typeof ms !== "number" || ms < 0) return "-";
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}天 ${h}时 ${m}分`;
  if (h > 0) return `${h}时 ${m}分`;
  if (m > 0) return `${m}分 ${s % 60}秒`;
  return `${s}秒`;
}

function pointStatusHtml(alarms, ok) {
  if (alarms && alarms.length) {
    const level = alarms[0].payload && alarms[0].payload.level;
    const label = level ? `告警 ${level}` : "告警";
    return `<span class="badge badge-alarm">${escapeHtml(label)}</span>`;
  }
  if (ok === undefined) return "-";
  return ok
    ? `<span class="badge badge-online"><span class="ok-dot"></span>正常</span>`
    : `<span class="badge badge-alarm"><span class="bad-dot"></span>异常</span>`;
}

function fmtValue(value) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") {
    return Math.abs(value) < 1e9 ? String(Math.round(value * 1000) / 1000) : String(value);
  }
  return String(value);
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function prettyJson(text) {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

async function fetchJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/* 轮询缓存，未变化则跳过 DOM 重绘，保护用户交互 */
function renderIfChanged(key, data, renderFn) {
  const sig = JSON.stringify(data);
  if (renderIfChanged._cache[key] === sig) return false;
  renderIfChanged._cache[key] = sig;
  renderFn();
  return true;
}
renderIfChanged._cache = {};

/* --------------------------------------------------------------------------
   2. 主题切换 (Light / Dark)
   -------------------------------------------------------------------------- */
function initTheme() {
  const saved = localStorage.getItem("vg-theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const isDark = saved ? saved === "dark" : prefersDark;
  setTheme(isDark ? "dark" : "light");

  const btn = $("theme-toggle");
  if (btn) {
    btn.addEventListener("click", () => {
      const current = document.documentElement.classList.contains("dark") ? "dark" : "light";
      const next = current === "dark" ? "light" : "dark";
      setTheme(next);
      localStorage.setItem("vg-theme", next);
    });
  }
}

function setTheme(theme) {
  const root = document.documentElement;
  const sun = $("theme-icon-sun");
  const moon = $("theme-icon-moon");
  if (theme === "dark") {
    root.classList.add("dark");
    if (sun) sun.style.display = "block";
    if (moon) moon.style.display = "none";
  } else {
    root.classList.remove("dark");
    if (sun) sun.style.display = "none";
    if (moon) moon.style.display = "block";
  }
}

/* --------------------------------------------------------------------------
   3. 导航与视图切换
   -------------------------------------------------------------------------- */
function showView(view) {
  state.view = view;
  for (const el of document.querySelectorAll(".view")) el.classList.add("hidden");
  const target = $("view-" + view);
  if (target) target.classList.remove("hidden");

  for (const btn of document.querySelectorAll(".nav-tab")) {
    btn.classList.toggle("active", btn.dataset.view === view);
  }
  refresh();
}

/* --------------------------------------------------------------------------
   4. KPI 指标统计更新
   -------------------------------------------------------------------------- */
function updateKpiMetrics() {
  const total = state.devices.length;
  const online = state.devices.filter((d) => d.online).length;
  const offline = total - online;
  const pct = total > 0 ? Math.round((online / total) * 100) : 0;

  $("kpi-total-devices").textContent = String(total);
  $("kpi-device-sub").textContent = `在线 ${online} · 离线 ${offline} (${pct}%)`;
  const prog = $("kpi-online-progress");
  if (prog) prog.style.width = `${pct}%`;

  const activeAlarms = (state.alarms && state.alarms.active) ? state.alarms.active.length : 0;
  $("kpi-active-alarms").textContent = String(activeAlarms);
  $("kpi-alarm-sub").innerHTML = activeAlarms > 0
    ? `<span style="color: var(--status-crit); font-weight: 600;">${activeAlarms} 条未恢复告警</span>`
    : `系统状态正常，无活动告警`;

  const navBadge = $("nav-alarms-badge");
  if (navBadge) {
    navBadge.textContent = String(activeAlarms);
    navBadge.style.display = activeAlarms > 0 ? "inline-flex" : "none";
  }

  const totalPoints = state.devices.reduce((acc, d) => acc + (d.point_count || 0), 0);
  $("kpi-total-points").textContent = String(totalPoints);

  const msgCount = (state.messages || []).length;
  const quarantined = (state.messages || []).filter((m) => m.quarantine_reason).length;
  $("kpi-messages-count").textContent = String(msgCount);
  $("kpi-messages-sub").innerHTML = quarantined > 0
    ? `<span style="color: var(--status-warn); font-weight: 600;">${quarantined} 条被隔离</span>`
    : `最新报文流校验通过`;
}

/* --------------------------------------------------------------------------
   5. 设备总览 (Fleet Overview)
   -------------------------------------------------------------------------- */
function renderDevices() {
  updateKpiMetrics();
  const grid = $("device-grid");
  const query = (state.deviceSearch || "").trim().toLowerCase();
  const filter = state.deviceFilter || "all";

  let list = state.devices;
  if (filter === "online") list = list.filter((d) => d.online);
  else if (filter === "offline") list = list.filter((d) => !d.online);
  else if (filter === "alarm") list = list.filter((d) => d.active_alarms > 0);

  if (query) {
    list = list.filter((d) => {
      const idMatch = d.device_id.toLowerCase().includes(query);
      const st = d.status || {};
      const fwMatch = (st.firmware || "").toLowerCase().includes(query);
      const netMatch = (st.network || "").toLowerCase().includes(query);
      return idMatch || fwMatch || netMatch;
    });
  }

  $("device-count-info").textContent = `显示 ${list.length} / 共 ${state.devices.length} 台设备`;

  if (!state.devices.length) {
    grid.innerHTML = `
      <div class="card empty" style="grid-column: 1 / -1;">
        <svg class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="14" x="2" y="5" rx="2"/><line x1="2" x2="22" y1="10" y2="10"/></svg>
        <div style="font-weight: 600; font-size: 0.9375rem; margin-bottom: 0.25rem;">暂无接入设备</div>
        <div>等待板端上报 <code>vg/{device_id}/status</code>… 可在终端运行 <code>python scripts/demo_dashboard_seed.py</code> 模拟数据。</div>
      </div>`;
    return;
  }

  if (!list.length) {
    grid.innerHTML = `
      <div class="card empty" style="grid-column: 1 / -1;">
        <svg class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
        <div style="font-weight: 600; font-size: 0.9375rem; margin-bottom: 0.25rem;">未找到匹配设备</div>
        <div>请尝试更改搜索关键词或状态过滤选项。</div>
      </div>`;
    return;
  }

  grid.innerHTML = "";
  for (const dev of list) {
    const card = document.createElement("div");
    card.className = "device-card";
    const st = dev.status || {};
    const alarmBadge = dev.active_alarms > 0
      ? `<span class="badge badge-alarm">${dev.active_alarms} 活动告警</span>` : "";

    card.innerHTML = `
      <div class="device-card-header">
        <div class="device-id-wrap">
          <div class="device-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M7 7h.01"/><path d="M17 7h.01"/><path d="M7 17h.01"/><path d="M17 17h.01"/></svg>
          </div>
          <span class="device-name">${escapeHtml(dev.device_id)}</span>
        </div>
        <div>
          ${dev.online
            ? `<span class="badge badge-online"><span class="ok-dot"></span>在线</span>`
            : `<span class="badge badge-offline"><span class="ok-dot" style="background:var(--status-offline)"></span>离线</span>`}
        </div>
      </div>
      <div class="device-card-body">
        <div class="meta-row"><span class="meta-label">固件版本</span><span class="meta-value">${escapeHtml(st.firmware || "-")}</span></div>
        <div class="meta-row"><span class="meta-label">构建模式</span><span class="meta-value">${escapeHtml(st.build_mode || "-")}</span></div>
        <div class="meta-row"><span class="meta-label">网络通道</span><span class="meta-value">${escapeHtml(st.network || "-")}</span></div>
        <div class="meta-row"><span class="meta-label">运行时长</span><span class="meta-value">${fmtUptime(st.uptime_ms)}</span></div>
        <div class="meta-row"><span class="meta-label">测点数量</span><span class="meta-value">${dev.point_count} 点</span></div>
        <div class="meta-row"><span class="meta-label">最近上报</span><span class="meta-value">${fmtTime(dev.received_ts_ms)}</span></div>
      </div>
      <div class="device-card-footer">
        <div>${alarmBadge || `<span class="badge badge-secondary">正常运转</span>`}</div>
        <span class="detail-link-arrow">进入详情 &rarr;</span>
      </div>
    `;
    card.addEventListener("click", () => {
      state.deviceId = dev.device_id;
      showView("detail");
    });
    grid.appendChild(card);
  }
}

/* --------------------------------------------------------------------------
   6. 设备详情 (Device Detail)
   -------------------------------------------------------------------------- */
function renderDetail() {
  const d = state.detail;
  const header = $("device-header");
  const breadcrumbId = $("detail-breadcrumb-id");

  if (!d) {
    if (breadcrumbId) breadcrumbId.textContent = "未找到设备";
    header.innerHTML = `<div class="empty">设备不存在或尚未上报有效状态。</div>`;
    $("device-alarms-wrap").innerHTML = "";
    $("point-table-wrap").innerHTML = "";
    $("unsynced-wrap").innerHTML = "";
    return;
  }

  if (breadcrumbId) breadcrumbId.textContent = d.device_id;

  const st = d.status || {};
  const alarmCount = d.active_alarms || (d.alarms || []).length;

  header.innerHTML = `
    <div class="device-banner-left">
      <div class="device-icon" style="width: 2rem; height: 2rem;">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M7 7h.01"/><path d="M17 7h.01"/><path d="M7 17h.01"/><path d="M17 17h.01"/></svg>
      </div>
      <div>
        <div class="device-banner-id">${escapeHtml(d.device_id)}</div>
      </div>
      ${d.online ? `<span class="badge badge-online"><span class="ok-dot"></span>在线</span>` : `<span class="badge badge-offline">离线</span>`}
      ${alarmCount > 0 ? `<span class="badge badge-alarm">${alarmCount} 活动告警</span>` : `<span class="badge badge-secondary">无活动告警</span>`}
    </div>
    <div class="device-banner-meta">
      <span>固件 <strong>${escapeHtml(st.firmware || "-")}</strong></span>
      <span>构建 <strong>${escapeHtml(st.build_mode || "-")}</strong></span>
      <span>网络 <strong>${escapeHtml(st.network || "-")}</strong></span>
      <span>时间质量 <strong>${escapeHtml(st.time_quality || "-")}</strong></span>
      <span>运行 <strong>${fmtUptime(st.uptime_ms)}</strong></span>
    </div>
  `;

  // 1. 活动告警表格
  const alarmRows = (d.alarms || []).map((al) => {
    const p = al.payload || {};
    return `<tr>
      <td><code>${escapeHtml(al.point_id || "-")}</code></td>
      <td>${escapeHtml(p.kind || "-")}</td>
      <td><span class="badge badge-warn">${escapeHtml(p.level || "alarm")}</span></td>
      <td class="num">${fmtValue(p.value)}</td>
      <td class="num">${fmtValue(p.thr)}</td>
      <td><span class="badge badge-alarm">raised</span></td>
      <td>${fmtTime(al.first_seen_ts_ms)}</td>
      <td>${fmtTime(al.last_seen_ts_ms)}</td>
    </tr>`;
  }).join("");
  $("device-alarms-wrap").innerHTML = alarmRows
    ? `<table>
        <thead><tr><th>点位 ID</th><th>告警类型</th><th>级别</th><th>触发数值</th><th>门限阈值</th><th>状态</th><th>首次触发</th><th>最近触发</th></tr></thead>
        <tbody>${alarmRows}</tbody>
      </table>`
    : `<div class="empty" style="padding: 1.5rem;"><svg class="empty-icon" style="width: 1.75rem; height: 1.75rem;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>当前设备运行健康，无活动告警</div>`;

  // 2. 点表数据（支持关键词快速搜索）
  const pointQuery = (state.pointSearch || "").trim().toLowerCase();
  let pointsList = d.points || [];
  if (pointQuery) {
    pointsList = pointsList.filter((p) => {
      const idMatch = (p.id || "").toLowerCase().includes(pointQuery);
      const nameMatch = (p.name || "").toLowerCase().includes(pointQuery);
      return idMatch || nameMatch;
    });
  }

  const rows = pointsList.map((p) => {
    const lat = p.latest || {};
    return `<tr>
      <td><code>${escapeHtml(p.id)}</code></td>
      <td style="font-weight: 500;">${escapeHtml(p.name || "-")}</td>
      <td class="num" style="font-weight: 600; color: hsl(var(--foreground)); font-size: 0.875rem;">${fmtValue(lat.value)}<span class="unit-tag">${escapeHtml(p.unit || "")}</span></td>
      <td>${pointStatusHtml(p.alarms, lat.ok)}</td>
      <td class="num">${lat.age_ms === undefined || lat.age_ms === null ? "-" : lat.age_ms + "ms"}</td>
      <td class="num">${p.addr === null || p.addr === undefined ? "-" : p.addr}</td>
      <td class="num">${p.reg === null || p.reg === undefined ? "-" : p.reg}</td>
      <td><span class="badge badge-outline">${escapeHtml(p.dtype || "-")}</span></td>
      <td class="num">${p.warn === null || p.warn === undefined ? "-" : `<span style="color:var(--status-warn)">${p.warn}</span>`}</td>
      <td class="num">${p.crit === null || p.crit === undefined ? "-" : `<span style="color:var(--status-crit)">${p.crit}</span>`}</td>
      <td>${fmtTime(lat.received_ts_ms)}</td>
    </tr>`;
  }).join("");

  $("point-table-wrap").innerHTML = (d.points && d.points.length)
    ? (rows ? `<table>
        <thead><tr>
          <th>点位 ID</th><th>名称</th><th>实时数值</th><th>状态</th>
          <th>新鲜度 (age)</th><th>总线地址</th><th>寄存器</th><th>数据类型</th><th>预警线</th><th>告警线</th><th>上报时间</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>` : `<div class="empty" style="padding: 1.5rem;">未找到与 "${escapeHtml(pointQuery)}" 匹配的测点</div>`)
    : `<div class="empty" style="padding: 1.5rem;">点表尚未同步。等待板端上报 <code>vg/{device_id}/point_table</code></div>`;

  // 3. 点表外实时值
  const unsynced = (d.unsynced_latest || []).map((s) => `
    <tr>
      <td><code>${escapeHtml(s.point_id)}</code></td>
      <td class="num" style="font-weight: 600;">${fmtValue(s.value)}</td>
      <td>${pointStatusHtml(s.alarms, s.ok)}</td>
      <td class="num">${s.age_ms === null ? "-" : s.age_ms + "ms"}</td>
      <td>${fmtTime(s.received_ts_ms)}</td>
    </tr>`).join("");
  $("unsynced-wrap").innerHTML = unsynced
    ? `<table><thead><tr><th>点位 ID</th><th>最新数值</th><th>状态</th><th>新鲜度</th><th>上报时间</th></tr></thead><tbody>${unsynced}</tbody></table>`
    : `<div class="empty" style="padding: 1.5rem;">全部实时测点均已在点表中成功映射</div>`;
}

function refreshTrendPointOptions(d) {
  const select = $("trend-point");
  const prev = select.value;
  const options = (d && d.points ? d.points : [])
    .filter((p) => p.latest && typeof p.latest.value === "number")
    .map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name ? `${p.name} (${p.id})` : p.id)}</option>`);
  if (!options.length) {
    select.innerHTML = `<option value="">暂无数值测点</option>`;
    $("trend-chart").innerHTML = `<div class="empty">暂无数值测点可供绘制趋势曲线。</div>`;
    $("trend-stats-bar").style.display = "none";
    return;
  }
  select.innerHTML = options.join("");
  if (prev && [...select.options].some((o) => o.value === prev)) select.value = prev;
}

/* --------------------------------------------------------------------------
   7. 趋势图渲染 (Modern SVG Chart with Gradient & Tooltip)
   -------------------------------------------------------------------------- */
async function renderTrend() {
  const wrap = $("trend-chart");
  const meta = $("trend-meta");
  if (state.view !== "detail" || !state.deviceId) return;
  const pointId = $("trend-point").value;
  if (!pointId) return;

  const minutes = state.trendMinutes || parseInt($("trend-range").value, 10) || 30;
  try {
    const data = await fetchJson(
      `/api/devices/${encodeURIComponent(state.deviceId)}/history?point=${encodeURIComponent(pointId)}&minutes=${minutes}`
    );
    state.trendSamples = data.samples || [];
    drawTrendChart(state.trendSamples, minutes, pointId);
  } catch (err) {
    wrap.innerHTML = `<div class="empty">趋势数据获取失败：${escapeHtml(err.message)}</div>`;
    $("trend-stats-bar").style.display = "none";
  }
}

function drawTrendChart(samples, minutes, pointId) {
  const wrap = $("trend-chart");
  const meta = $("trend-meta");
  const statsBar = $("trend-stats-bar");
  const numeric = samples.filter((s) => typeof s.value === "number");

  if (numeric.length < 2) {
    wrap.innerHTML = `<div class="empty">样本不足（已收集 ${samples.length} 条），等待设备更多数据上报…</div>`;
    statsBar.style.display = "none";
    meta.textContent = "";
    return;
  }

  statsBar.style.display = "grid";
  const values = numeric.map((s) => s.value);
  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const avgVal = values.reduce((a, b) => a + b, 0) / values.length;
  const lastSample = numeric[numeric.length - 1];

  $("trend-stat-latest").textContent = fmtValue(lastSample.value);
  $("trend-stat-min").textContent = fmtValue(minVal);
  $("trend-stat-max").textContent = fmtValue(maxVal);
  $("trend-stat-avg").textContent = fmtValue(Math.round(avgVal * 100) / 100);

  meta.textContent = `点位 ${pointId} · 采集窗口最近 ${minutes} 分钟 · 共 ${numeric.length} 个数据点`;

  const W = 640, H = 240;
  const PAD_L = 48, PAD_R = 20, PAD_T = 20, PAD_B = 30;
  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;

  const xs = numeric.map((s) => s.received_ts_ms);
  const x0 = xs[0], x1 = xs[xs.length - 1];

  let y0 = minVal, y1 = maxVal;
  if (y0 === y1) { y0 -= 1; y1 += 1; }
  const span = y1 - y0;
  y0 -= span * 0.08;
  y1 += span * 0.08;

  const px = (t) => PAD_L + ((t - x0) / Math.max(1, x1 - x0)) * plotW;
  const py = (v) => H - PAD_B - ((v - y0) / (y1 - y0)) * plotH;

  const polyPoints = numeric.map((s) => `${px(s.received_ts_ms).toFixed(1)},${py(s.value).toFixed(1)}`);
  const linePointsStr = polyPoints.join(" ");
  const areaPointsStr = `${px(x0).toFixed(1)},${H - PAD_B} ${linePointsStr} ${px(x1).toFixed(1)},${H - PAD_B}`;

  const badPoints = numeric
    .filter((s) => !s.ok)
    .map((s) => `<circle cx="${px(s.received_ts_ms).toFixed(1)}" cy="${py(s.value).toFixed(1)}" r="4" fill="var(--status-crit)" stroke="#fff" stroke-width="1.5" />`)
    .join("");

  // 参考水平网格线（3 条）
  const gridY1 = py(y1);
  const gridYMid = py((y0 + y1) / 2);
  const gridY0 = py(y0);

  wrap.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" id="trend-svg">
      <defs>
        <linearGradient id="trendGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#3b82f6" stop-opacity="0.32" />
          <stop offset="100%" stop-color="#3b82f6" stop-opacity="0.0" />
        </linearGradient>
      </defs>

      <!-- 网格与刻度线 -->
      <line x1="${PAD_L}" y1="${gridY1}" x2="${W - PAD_R}" y2="${gridY1}" stroke="hsl(var(--border))" stroke-dasharray="3,3" stroke-width="1" />
      <line x1="${PAD_L}" y1="${gridYMid}" x2="${W - PAD_R}" y2="${gridYMid}" stroke="hsl(var(--border))" stroke-dasharray="3,3" stroke-width="1" />
      <line x1="${PAD_L}" y1="${gridY0}" x2="${W - PAD_R}" y2="${gridY0}" stroke="hsl(var(--border))" stroke-width="1" />

      <!-- Y 轴刻度文字 -->
      <text x="${PAD_L - 8}" y="${gridY1 + 3}" text-anchor="end" font-size="10" fill="hsl(var(--muted-foreground))" font-variant-numeric="tabular-nums">${fmtValue(y1)}</text>
      <text x="${PAD_L - 8}" y="${gridYMid + 3}" text-anchor="end" font-size="10" fill="hsl(var(--muted-foreground))" font-variant-numeric="tabular-nums">${fmtValue((y0 + y1) / 2)}</text>
      <text x="${PAD_L - 8}" y="${gridY0 + 3}" text-anchor="end" font-size="10" fill="hsl(var(--muted-foreground))" font-variant-numeric="tabular-nums">${fmtValue(y0)}</text>

      <!-- X 轴刻度文字 -->
      <text x="${PAD_L}" y="${H - 10}" font-size="10" fill="hsl(var(--muted-foreground))">${fmtTimeShort(x0)}</text>
      <text x="${W - PAD_R}" y="${H - 10}" text-anchor="end" font-size="10" fill="hsl(var(--muted-foreground))">${fmtTimeShort(x1)}</text>

      <!-- 渐变底色与折线 -->
      <polygon points="${areaPointsStr}" fill="url(#trendGrad)" />
      <polyline points="${linePointsStr}" fill="none" stroke="#3b82f6" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
      ${badPoints}

      <!-- 悬停指示标线 -->
      <line id="crosshair-line" x1="0" y1="${PAD_T}" x2="0" y2="${H - PAD_B}" stroke="hsl(var(--muted-foreground))" stroke-dasharray="3,3" stroke-width="1" style="display:none;" />
      <circle id="crosshair-dot" cx="0" cy="0" r="4.5" fill="#3b82f6" stroke="#fff" stroke-width="2" style="display:none;" />

      <!-- 交互透明响应层 -->
      <rect id="chart-overlay" x="${PAD_L}" y="${PAD_T}" width="${plotW}" height="${plotH}" fill="transparent" style="cursor: crosshair;" />
    </svg>
    <div id="chart-tooltip" class="chart-tooltip"></div>
  `;

  setupChartInteractivity(numeric, px, py, PAD_L, PAD_R, plotW);
}

function setupChartInteractivity(numeric, px, py, PAD_L, PAD_R, plotW) {
  const overlay = $("chart-overlay");
  const svg = $("trend-svg");
  const crosshair = $("crosshair-line");
  const dot = $("crosshair-dot");
  const tooltip = $("chart-tooltip");
  if (!overlay || !svg || !tooltip) return;

  overlay.addEventListener("mousemove", (e) => {
    const rect = svg.getBoundingClientRect();
    const mouseSvgX = ((e.clientX - rect.left) / rect.width) * 640;

    // 二分或线性查找到最近样本
    let closest = numeric[0];
    let minDiff = Math.abs(px(closest.received_ts_ms) - mouseSvgX);
    for (let i = 1; i < numeric.length; i++) {
      const diff = Math.abs(px(numeric[i].received_ts_ms) - mouseSvgX);
      if (diff < minDiff) {
        minDiff = diff;
        closest = numeric[i];
      }
    }

    const curX = px(closest.received_ts_ms);
    const curY = py(closest.value);

    crosshair.setAttribute("x1", curX);
    crosshair.setAttribute("x2", curX);
    crosshair.style.display = "block";

    dot.setAttribute("cx", curX);
    dot.setAttribute("cy", curY);
    dot.style.display = "block";

    // 相对像素定位 Tooltip
    const relX = (curX / 640) * rect.width;
    const relY = (curY / 240) * rect.height;

    tooltip.innerHTML = `
      <div style="font-weight: 600; font-size: 0.8125rem;">${fmtValue(closest.value)}</div>
      <div style="color: hsl(var(--muted-foreground)); font-size: 0.6875rem;">${fmtTime(closest.received_ts_ms)}</div>
      ${closest.ok ? "" : `<div style="color: var(--status-crit); font-size: 0.6875rem; font-weight:600;">异常采样</div>`}
    `;
    tooltip.style.left = `${relX}px`;
    tooltip.style.top = `${relY}px`;
    tooltip.style.display = "block";
  });

  overlay.addEventListener("mouseleave", () => {
    if (crosshair) crosshair.style.display = "none";
    if (dot) dot.style.display = "none";
    if (tooltip) tooltip.style.display = "none";
  });
}

/* --------------------------------------------------------------------------
   8. 告警中心 (Alarms View)
   -------------------------------------------------------------------------- */
function renderAlarms() {
  updateKpiMetrics();
  const a = state.alarms || { active: [], events: [] };
  const activeRows = (a.active || []).map((al) => {
    const p = al.payload || {};
    return `<tr>
      <td><strong>${escapeHtml(al.device_id)}</strong></td>
      <td><code>${escapeHtml(al.point_id || "-")}</code></td>
      <td>${escapeHtml(p.kind || "-")}</td>
      <td class="num">${fmtValue(p.value)}</td>
      <td class="num">${fmtValue(p.thr)}</td>
      <td><span class="badge badge-alarm">raised</span></td>
      <td>${fmtTime(al.first_seen_ts_ms)}</td>
      <td>${fmtTime(al.last_seen_ts_ms)}</td>
    </tr>`;
  }).join("");
  $("active-alarms").innerHTML = activeRows
    ? `<table><thead><tr><th>设备</th><th>点位</th><th>类型</th><th>触发值</th><th>门限值</th><th>状态</th><th>首次触发</th><th>最近触发</th></tr></thead><tbody>${activeRows}</tbody></table>`
    : `<div class="empty"><svg class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>当前全网无活动告警，所有设备运行稳定</div>`;

  const eventRows = (a.events || []).map((ev) => {
    const p = ev.payload || {};
    const badge = ev.state === "raised"
      ? `<span class="badge badge-alarm">触发 (Raised)</span>`
      : `<span class="badge badge-online">恢复 (Cleared)</span>`;
    return `<tr>
      <td>${fmtTime(ev.received_ts_ms)}</td>
      <td><strong>${escapeHtml(ev.device_id)}</strong></td>
      <td><code>${escapeHtml(ev.point_id || "-")}</code></td>
      <td>${escapeHtml(p.kind || "-")}</td>
      <td class="num">${fmtValue(p.value)}</td>
      <td class="num">${fmtValue(p.thr)}</td>
      <td>${badge}</td>
      <td>${ev.device_ts_ms ? fmtTime(ev.device_ts_ms) : "-"}</td>
    </tr>`;
  }).join("");
  $("alarm-events").innerHTML = eventRows
    ? `<table><thead><tr><th>接收时间</th><th>设备</th><th>点位</th><th>类型</th><th>触发值</th><th>门限值</th><th>事件状态</th><th>设备采样时刻</th></tr></thead><tbody>${eventRows}</tbody></table>`
    : `<div class="empty">暂无告警历史事件记录</div>`;
}

/* --------------------------------------------------------------------------
   9. 原始报文 (Messages View)
   -------------------------------------------------------------------------- */
function renderMessages() {
  updateKpiMetrics();
  const rows = state.messages.map((m, idx) => {
    const cls = m.quarantine_reason ? "quarantined" : "";
    const jsonStr = prettyJson(m.payload);
    return `<tr class="${cls}">
      <td>${fmtTime(m.received_ts_ms)}</td>
      <td><code>${escapeHtml(m.topic)}</code></td>
      <td><span class="badge badge-outline">${escapeHtml(m.kind || "-")}</span></td>
      <td>${m.quarantine_reason
        ? `<span class="badge badge-warn">隔离: ${escapeHtml(m.quarantine_reason)}</span>`
        : `<span class="badge badge-online">通过校验</span>`}</td>
      <td>
        <details>
          <summary style="cursor: pointer; color: hsl(var(--muted-foreground)); font-size: 0.75rem;">展开 Payload</summary>
          <div class="json-preview-wrap">
            <pre id="json-pre-${idx}">${escapeHtml(jsonStr)}</pre>
            <button class="btn-copy" onclick="copyPayload(${idx})">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
              <span>复制 JSON</span>
            </button>
          </div>
        </details>
      </td>
    </tr>`;
  }).join("");
  $("raw-messages").innerHTML = rows
    ? `<table><thead><tr><th>收到时间</th><th>MQTT 主题 (Topic)</th><th>报文类型</th><th>校验状态</th><th>载荷内容</th></tr></thead><tbody>${rows}</tbody></table>`
    : `<div class="empty">暂无报文数据</div>`;
}

window.copyPayload = function (idx) {
  const pre = $("json-pre-" + idx);
  if (!pre) return;
  const text = pre.textContent;
  navigator.clipboard.writeText(text).then(() => {
    const btn = pre.nextElementSibling;
    if (btn) {
      const span = btn.querySelector("span");
      if (span) {
        const old = span.textContent;
        span.textContent = "✓ 已复制";
        setTimeout(() => { span.textContent = old; }, 1500);
      }
    }
  });
};

/* --------------------------------------------------------------------------
   10. 轮询同步与服务端连接状态
   -------------------------------------------------------------------------- */
async function refresh() {
  try {
    if (state.view === "devices") {
      const [devData, alarmData, msgData] = await Promise.all([
        fetchJson("/api/devices"),
        fetchJson("/api/alarms"),
        fetchJson("/api/messages?limit=100"),
      ]);
      state.devices = devData.devices || [];
      state.alarms = alarmData || { active: [], events: [] };
      state.messages = msgData.messages || [];
      renderIfChanged("devices", state.devices, renderDevices);
    } else if (state.view === "detail" && state.deviceId) {
      state.detail = await fetchJson(`/api/devices/${encodeURIComponent(state.deviceId)}`);
      const changed = renderIfChanged("detail", state.detail, renderDetail);
      if (changed) refreshTrendPointOptions(state.detail);
      await renderTrend();
    } else if (state.view === "alarms") {
      state.alarms = await fetchJson("/api/alarms");
      renderIfChanged("alarms", state.alarms, renderAlarms);
    } else if (state.view === "messages") {
      const data = await fetchJson("/api/messages?limit=100");
      state.messages = data.messages || [];
      renderIfChanged("messages", state.messages, renderMessages);
    }
    setConn(true);
  } catch (err) {
    setConn(false);
  }
}

function setConn(ok) {
  state.connFail = !ok;
  const badge = $("conn-badge");
  const text = $("conn-text");
  if (!badge) return;
  badge.className = `conn-pill ${ok ? "conn-ok" : "conn-fail"}`;
  if (text) text.textContent = ok ? "采集服务正常" : "服务连接中断";
}

/* --------------------------------------------------------------------------
   11. 初始化与事件监听绑定
   -------------------------------------------------------------------------- */
function initEventListeners() {
  initTheme();

  // 导航切换
  document.querySelectorAll(".nav-tab").forEach((btn) => {
    btn.addEventListener("click", () => showView(btn.dataset.view));
  });

  const backBtn = $("back-to-devices");
  if (backBtn) backBtn.addEventListener("click", () => showView("devices"));

  // 设备搜索过滤
  const devSearch = $("device-search-input");
  if (devSearch) {
    devSearch.addEventListener("input", (e) => {
      state.deviceSearch = e.target.value;
      renderDevices();
    });
  }

  // 状态筛选胶囊
  const filterPills = $("device-filter-pills");
  if (filterPills) {
    filterPills.querySelectorAll(".filter-pill").forEach((pill) => {
      pill.addEventListener("click", () => {
        filterPills.querySelectorAll(".filter-pill").forEach((p) => p.classList.remove("active"));
        pill.classList.add("active");
        state.deviceFilter = pill.dataset.filter;
        renderDevices();
      });
    });
  }

  // 测点搜索过滤
  const pointSearch = $("point-search-input");
  if (pointSearch) {
    pointSearch.addEventListener("input", (e) => {
      state.pointSearch = e.target.value;
      renderDetail();
    });
  }

  // 趋势图选择
  const trendPoint = $("trend-point");
  if (trendPoint) trendPoint.addEventListener("change", renderTrend);

  const trendRange = $("trend-range");
  if (trendRange) trendRange.addEventListener("change", renderTrend);

  // 趋势图时间范围快捷胶囊
  const rangePills = $("trend-range-pills");
  if (rangePills) {
    rangePills.querySelectorAll(".range-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        rangePills.querySelectorAll(".range-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        const mins = parseInt(btn.dataset.minutes, 10);
        state.trendMinutes = mins;
        if (trendRange) trendRange.value = String(mins);
        renderTrend();
      });
    });
  }
}

initEventListeners();
showView("devices");
setInterval(refresh, POLL_MS);
