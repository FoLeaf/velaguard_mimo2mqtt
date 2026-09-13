/* VelaGuard 云看板前端：只读轮询，无构建步骤。 */
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
};

const $ = (id) => document.getElementById(id);

/* 轮询期间数据未变化则跳过重绘，避免点击目标被替换。 */
function renderIfChanged(key, data, renderFn) {
  const sig = JSON.stringify(data);
  if (renderIfChanged._cache[key] === sig) return false;
  renderIfChanged._cache[key] = sig;
  renderFn();
  return true;
}
renderIfChanged._cache = {};

function fmtTime(ms) {
  if (!ms) return "-";
  const d = new Date(ms);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function fmtUptime(ms) {
  if (typeof ms !== "number" || ms < 0) return "-";
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}天${h}时${m}分`;
  if (h > 0) return `${h}时${m}分`;
  if (m > 0) return `${m}分${s % 60}秒`;
  return `${s}秒`;
}

function fmtValue(value) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") {
    return Math.abs(value) < 1e9 ? String(Math.round(value * 1000) / 1000) : String(value);
  }
  return String(value);
}

async function fetchJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/* ---------- 导航 ---------- */

function showView(view) {
  state.view = view;
  for (const el of document.querySelectorAll(".view")) el.classList.add("hidden");
  $("view-" + view).classList.remove("hidden");
  for (const btn of document.querySelectorAll(".nav-btn")) {
    btn.classList.toggle("active", btn.dataset.view === view);
  }
  refresh();
}

/* ---------- 设备总览 ---------- */

function renderDevices() {
  const grid = $("device-grid");
  if (!state.devices.length) {
    grid.innerHTML = `<div class="empty">暂无设备数据。等待板端上报 vg/{device_id}/status …（可用 python -m dashboard.tools.synthetic_board 模拟）</div>`;
    return;
  }
  grid.innerHTML = "";
  for (const dev of state.devices) {
    const card = document.createElement("div");
    card.className = "device-card";
    const st = dev.status || {};
    const alarmBadge = dev.active_alarms > 0
      ? `<span class="badge badge-alarm">告警 ${dev.active_alarms}</span>` : "";
    card.innerHTML = `
      <div class="device-title">
        <span class="device-name">${escapeHtml(dev.device_id)}</span>
        ${dev.online
          ? `<span class="badge badge-online">在线</span>`
          : `<span class="badge badge-offline">离线</span>`}
      </div>
      <div class="meta-row"><span>固件</span><span class="v">${escapeHtml(st.firmware || "-")}</span></div>
      <div class="meta-row"><span>构建模式</span><span class="v">${escapeHtml(st.build_mode || "-")}</span></div>
      <div class="meta-row"><span>网络</span><span class="v">${escapeHtml(st.network || "-")}</span></div>
      <div class="meta-row"><span>运行时长</span><span class="v">${fmtUptime(st.uptime_ms)}</span></div>
      <div class="meta-row"><span>点表点位</span><span class="v">${dev.point_count}</span></div>
      <div class="meta-row"><span>最近上报</span><span class="v">${fmtTime(dev.received_ts_ms)}</span></div>
      ${alarmBadge ? `<div style="margin-top:8px">${alarmBadge}</div>` : ""}
    `;
    card.addEventListener("click", () => {
      state.deviceId = dev.device_id;
      showView("detail");
    });
    grid.appendChild(card);
  }
}

/* ---------- 设备详情 ---------- */

function renderDetail() {
  const d = state.detail;
  const header = $("device-header");
  if (!d) {
    header.innerHTML = `<span class="empty">设备不存在或尚未上报。</span>`;
    $("point-table-wrap").innerHTML = "";
    $("unsynced-wrap").innerHTML = "";
    return;
  }
  const st = d.status || {};
  header.innerHTML = `
    <span>${escapeHtml(d.device_id)}</span>
    ${d.online ? `<span class="badge badge-online">在线</span>` : `<span class="badge badge-offline">离线</span>`}
    <span class="meta-row" style="padding:0"><span>固件 ${escapeHtml(st.firmware || "-")}</span></span>
    <span class="meta-row" style="padding:0"><span>网络 ${escapeHtml(st.network || "-")}</span></span>
    <span class="meta-row" style="padding:0"><span>时间质量 ${escapeHtml(st.time_quality || "-")}</span></span>
  `;

  const rows = (d.points || []).map((p) => {
    const lat = p.latest || {};
    return `<tr>
      <td><code>${escapeHtml(p.id)}</code></td>
      <td>${escapeHtml(p.name || "-")}</td>
      <td class="num">${fmtValue(lat.value)}</td>
      <td>${escapeHtml(p.unit || "")}</td>
      <td>${lat.ok === undefined ? "-" : (lat.ok ? `<span class="ok-dot"></span>正常` : `<span class="bad-dot"></span>异常`)}</td>
      <td class="num">${lat.age_ms === undefined || lat.age_ms === null ? "-" : lat.age_ms}</td>
      <td class="num">${p.addr === null || p.addr === undefined ? "-" : p.addr}</td>
      <td class="num">${p.reg === null || p.reg === undefined ? "-" : p.reg}</td>
      <td>${escapeHtml(p.dtype || "-")}</td>
      <td class="num">${p.warn === null || p.warn === undefined ? "" : p.warn}</td>
      <td class="num">${p.crit === null || p.crit === undefined ? "" : p.crit}</td>
      <td>${fmtTime(lat.received_ts_ms)}</td>
    </tr>`;
  }).join("");

  $("point-table-wrap").innerHTML = d.points && d.points.length
    ? `<table>
        <thead><tr>
          <th>点位ID</th><th>名称</th><th>最新值</th><th>单位</th><th>状态</th>
          <th>age_ms</th><th>addr</th><th>reg</th><th>dtype</th><th>warn</th><th>crit</th><th>上报时间</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`
    : `<div class="empty">点表尚未同步。等待板端上报 vg/{device_id}/point_table。</div>`;

  const unsynced = (d.unsynced_latest || []).map((s) => `
    <tr>
      <td><code>${escapeHtml(s.point_id)}</code></td>
      <td class="num">${fmtValue(s.value)}</td>
      <td>${s.ok ? `<span class="ok-dot"></span>正常` : `<span class="bad-dot"></span>异常`}</td>
      <td class="num">${s.age_ms === null ? "-" : s.age_ms}</td>
      <td>${fmtTime(s.received_ts_ms)}</td>
    </tr>`).join("");
  $("unsynced-wrap").innerHTML = unsynced
    ? `<table><thead><tr><th>点位ID</th><th>最新值</th><th>状态</th><th>age_ms</th><th>上报时间</th></tr></thead><tbody>${unsynced}</tbody></table>`
    : `<div class="empty">无（所有实时值都能对应到点表）</div>`;
}

function refreshTrendPointOptions(d) {
  const select = $("trend-point");
  const prev = select.value;
  const options = (d && d.points ? d.points : [])
    .filter((p) => p.latest && typeof p.latest.value === "number")
    .map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name || p.id)}</option>`);
  if (!options.length) {
    select.innerHTML = `<option value="">暂无数值点位</option>`;
    $("trend-chart").innerHTML = `<div class="empty">暂无数值点位可绘图。</div>`;
    return;
  }
  select.innerHTML = options.join("");
  if (prev && [...select.options].some((o) => o.value === prev)) select.value = prev;
}

async function renderTrend() {
  const wrap = $("trend-chart");
  const meta = $("trend-meta");
  if (state.view !== "detail" || !state.deviceId) return;
  const pointId = $("trend-point").value;
  if (!pointId) return;
  const minutes = parseInt($("trend-range").value, 10) || 30;
  try {
    const data = await fetchJson(
      `/api/devices/${encodeURIComponent(state.deviceId)}/history?point=${encodeURIComponent(pointId)}&minutes=${minutes}`
    );
    drawTrendChart(data.samples || [], minutes);
    const last = (data.samples || [])[data.samples.length - 1];
    meta.textContent = `点位 ${pointId} · ${data.samples.length} 个样本 · 最新 ${last ? fmtValue(last.value) : "-"} @ ${last ? fmtTime(last.received_ts_ms) : "-"}`;
  } catch (err) {
    meta.textContent = `趋势数据获取失败：${err.message}`;
  }
}

function drawTrendChart(samples, minutes) {
  const wrap = $("trend-chart");
  const numeric = samples.filter((s) => typeof s.value === "number");
  if (numeric.length < 2) {
    wrap.innerHTML = `<div class="empty">样本不足（${samples.length}），等待更多上报。</div>`;
    return;
  }
  const W = 600, H = 220, PAD = 34;
  const xs = numeric.map((s) => s.received_ts_ms);
  const ys = numeric.map((s) => s.value);
  const x0 = xs[0], x1 = xs[xs.length - 1];
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (y0 === y1) { y0 -= 1; y1 += 1; }
  const span = y1 - y0;
  y0 -= span * 0.1; y1 += span * 0.1;
  const px = (t) => PAD + ((t - x0) / Math.max(1, x1 - x0)) * (W - PAD * 2);
  const py = (v) => H - PAD - ((v - y0) / (y1 - y0)) * (H - PAD * 2);
  const points = numeric.map((s) => `${px(s.received_ts_ms).toFixed(1)},${py(s.value).toFixed(1)}`).join(" ");
  const badPoints = numeric
    .filter((s) => !s.ok)
    .map((s) => `<circle cx="${px(s.received_ts_ms).toFixed(1)}" cy="${py(s.value).toFixed(1)}" r="3.5" fill="var(--crit)" />`)
    .join("");
  wrap.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <rect x="${PAD}" y="${PAD}" width="${W - PAD * 2}" height="${H - PAD * 2}" fill="var(--panel-2)" stroke="var(--border)" />
      <text x="${PAD - 6}" y="${py(y1) + 4}" text-anchor="end" font-size="10" fill="var(--muted)">${fmtValue(y1)}</text>
      <text x="${PAD - 6}" y="${py(y0) + 4}" text-anchor="end" font-size="10" fill="var(--muted)">${fmtValue(y0)}</text>
      <text x="${PAD}" y="${H - 10}" font-size="10" fill="var(--muted)">${fmtTime(x0)}</text>
      <text x="${W - PAD}" y="${H - 10}" text-anchor="end" font-size="10" fill="var(--muted)">${fmtTime(x1)}</text>
      <polyline points="${points}" fill="none" stroke="var(--accent)" stroke-width="2" />
      ${badPoints}
    </svg>`;
}

/* ---------- 告警 ---------- */

function renderAlarms() {
  const a = state.alarms || { active: [], events: [] };
  const activeRows = (a.active || []).map((al) => {
    const p = al.payload || {};
    return `<tr>
      <td>${escapeHtml(al.device_id)}</td>
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
    ? `<table><thead><tr><th>设备</th><th>点位</th><th>类型</th><th>值</th><th>阈值</th><th>状态</th><th>首次触发</th><th>最近触发</th></tr></thead><tbody>${activeRows}</tbody></table>`
    : `<div class="empty">当前无活动告警。</div>`;

  const eventRows = (a.events || []).map((ev) => {
    const p = ev.payload || {};
    const badge = ev.state === "raised"
      ? `<span class="badge badge-alarm">触发</span>`
      : `<span class="badge badge-online">恢复</span>`;
    return `<tr>
      <td>${fmtTime(ev.received_ts_ms)}</td>
      <td>${escapeHtml(ev.device_id)}</td>
      <td><code>${escapeHtml(ev.point_id || "-")}</code></td>
      <td>${escapeHtml(p.kind || "-")}</td>
      <td class="num">${fmtValue(p.value)}</td>
      <td class="num">${fmtValue(p.thr)}</td>
      <td>${badge}</td>
      <td>${ev.device_ts_ms ? fmtTime(ev.device_ts_ms) : "-"}</td>
    </tr>`;
  }).join("");
  $("alarm-events").innerHTML = eventRows
    ? `<table><thead><tr><th>收到时间</th><th>设备</th><th>点位</th><th>类型</th><th>值</th><th>阈值</th><th>事件</th><th>设备时间</th></tr></thead><tbody>${eventRows}</tbody></table>`
    : `<div class="empty">暂无告警事件。</div>`;
}

/* ---------- 原始报文 ---------- */

function renderMessages() {
  const rows = state.messages.map((m) => {
    const cls = m.quarantine_reason ? "quarantined" : "";
    return `<tr class="${cls}">
      <td>${fmtTime(m.received_ts_ms)}</td>
      <td><code>${escapeHtml(m.topic)}</code></td>
      <td>${escapeHtml(m.kind || "-")}</td>
      <td>${m.quarantine_reason
        ? `<span class="badge badge-warn">隔离: ${escapeHtml(m.quarantine_reason)}</span>`
        : `<span class="badge badge-online">正常</span>`}</td>
      <td><details><summary>查看 JSON</summary><pre>${escapeHtml(prettyJson(m.payload))}</pre></details></td>
    </tr>`;
  }).join("");
  $("raw-messages").innerHTML = rows
    ? `<table><thead><tr><th>收到时间</th><th>主题</th><th>类型</th><th>状态</th><th>载荷</th></tr></thead><tbody>${rows}</tbody></table>`
    : `<div class="empty">暂无报文。</div>`;
}

function prettyJson(text) {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/* ---------- 轮询 ---------- */

async function refresh() {
  try {
    if (state.view === "devices") {
      const data = await fetchJson("/api/devices");
      state.devices = data.devices || [];
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
  badge.textContent = ok ? "采集服务已连接" : "采集服务连接失败";
  badge.className = `conn-badge ${ok ? "conn-ok" : "conn-fail"}`;
}

/* ---------- 启动 ---------- */

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => showView(btn.dataset.view));
});
$("back-to-devices").addEventListener("click", () => showView("devices"));
$("trend-range").addEventListener("change", renderTrend);
$("trend-point").addEventListener("change", renderTrend);

showView("devices");
setInterval(refresh, POLL_MS);
