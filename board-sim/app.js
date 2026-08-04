"use strict";

/* =====================================================================
 * VelaGuard board HMI simulator - UI layer.
 *
 * Depends on BoardCore (board-core.js) and mqtt.js (vendor/mqtt.min.js).
 * Renders the 480x272 board replica into #content and owns the developer
 * toolbar: scenario switching, real/mock mode, MQTT connection, traffic
 * log. Real mode follows the AI Bridge contract from
 * .trellis/spec/backend/mqtt-ai-bridge-contracts.md.
 * ===================================================================== */

const core = window.BoardCore;

const PAGE_TITLES = {
  home: "VelaGuard",
  device: "设备详情",
  trend: "实时趋势",
  alarm: "告警详情",
  diagnosis: "AI 诊断",
  logs: "事件日志",
  add_sensor: "后续版本",
  system: "后续版本",
  ota: "后续版本",
};

const STUB_PAGES = ["add_sensor", "system", "ota"];

const SEV_CLASS = {
  ok: "sev-ok",
  warn: "sev-warn",
  crit: "sev-crit",
  offline: "sev-offline",
  info: "sev-info",
};

const state = {
  model: null,
  mode: "real",
  page: "home",
  navStack: [],
  mqtt: {
    client: null,
    status: "disconnected",
    pending: new Map(), // req_id -> { timer, requestTopic, responseTopic, deviceId }
  },
  traffic: [],
  homeCtx: null,
  connectPromise: null,
  toastTimer: null,
  lastTerminal: null,
};

/* =====================================================================
 * DOM helpers.
 * ===================================================================== */

function $(id) {
  return document.getElementById(id);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
}

function formatClock(d) {
  const p = (n) => String(n).padStart(2, "0");
  return p(d.getHours()) + ":" + p(d.getMinutes());
}

function formatTime(ts) {
  const d = new Date(ts);
  const p = (n, w) => String(n).padStart(w || 2, "0");
  return (
    p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds()) + "." + p(d.getMilliseconds(), 3)
  );
}

function severityColor(sev) {
  switch (sev) {
    case "warn":
      return "var(--warn)";
    case "crit":
      return "var(--crit)";
    case "offline":
      return "var(--offline)";
    case "info":
      return "var(--info)";
    case "ok":
    default:
      return "var(--ok)";
  }
}

function setChip(id, text, sev) {
  const node = $(id);
  if (!node) {
    return;
  }
  node.textContent = text;
  node.className = "chip chip-" + (sev || "info");
}

/* =====================================================================
 * Shell: status bar, toast, navigation.
 * ===================================================================== */

function toast(message) {
  const node = $("toast");
  if (!node) {
    return;
  }
  node.textContent = message;
  node.hidden = false;
  if (state.toastTimer) {
    clearTimeout(state.toastTimer);
  }
  state.toastTimer = setTimeout(() => {
    node.hidden = true;
    state.toastTimer = null;
  }, 1800);
}

function refreshStatusBar() {
  const net = state.model.net;
  setChip("chip-net", net.net_ok ? "NET" : "NET!", net.net_ok ? "info" : "crit");
  if (net.ota_active) {
    setChip("chip-mimo", "OTA", "info");
  } else {
    setChip("chip-mimo", net.mimo_ok ? "MiMo" : "MiMo!", net.mimo_ok ? "info" : "warn");
  }
  setChip("chip-acq", net.acq_ok ? "ACQ" : "ACQ!", net.acq_ok ? "ok" : "crit");
  setChip("chip-aud", net.aud_ok ? "AUD" : "AUD!", net.aud_ok ? "ok" : "warn");
}

function setTitle(title) {
  $("page-title").textContent = title;
}

function updateBackButton() {
  $("back-btn").hidden = state.navStack.length === 0;
}

function navigate(page) {
  if (STUB_PAGES.includes(page)) {
    toast("后续版本");
    return;
  }
  if (page !== state.page) {
    if (state.navStack.length >= 6) {
      state.navStack.shift();
    }
    state.navStack.push(state.page);
  }
  state.page = page;
  state.homeCtx = null;
  renderPage();
  if (page === "diagnosis") {
    startDiagnosisIfIdle();
  }
}

function goBack() {
  if (state.navStack.length > 0) {
    state.page = state.navStack.pop();
  } else if (state.page !== "home") {
    state.page = "home";
  } else {
    return;
  }
  state.homeCtx = null;
  renderPage();
}

/* =====================================================================
 * Page rendering.
 * ===================================================================== */

function renderPage() {
  const content = $("content");
  content.textContent = "";
  setTitle(PAGE_TITLES[state.page] || "VelaGuard");
  updateBackButton();
  switch (state.page) {
    case "home":
      renderHome(content);
      break;
    case "device":
      renderDevice(content);
      break;
    case "trend":
      renderTrend(content);
      break;
    case "alarm":
      renderAlarm(content);
      break;
    case "diagnosis":
      renderDiagnosis(content);
      break;
    case "logs":
      renderLogs(content);
      break;
    default:
      renderStub(content);
      break;
  }
}

function renderStub(root) {
  root.className = "page";
  const box = el("div", "diag-box card");
  const lab = el("div", "", "功能将在后续版本提供");
  lab.style.color = "var(--muted)";
  box.appendChild(lab);
  root.appendChild(box);
}

function sensorLine(s) {
  const v = s.online ? core.fmt1(s.value) + s.unit : "--" + s.unit;
  return s.name + "  " + v + "  " + core.severityLabelZh(s.severity) + "  " + s.age_sec + "s";
}

function renderHome(root) {
  root.className = "page";

  const bar = el("div", "filter-bar");
  const counts = core.countByFilter(state.model);
  const filters = [
    ["all", "全部 " + counts.all],
    ["alarm", "告警 " + counts.alarm],
    ["offline", "离线 " + counts.offline],
    ["ok", "正常 " + counts.ok],
  ];
  for (const [id, label] of filters) {
    const btn = el(
      "button",
      "filter-btn" + (state.model.homeFilter === id ? " is-active" : ""),
      label
    );
    btn.type = "button";
    btn.dataset.testid = "home-filter-" + id;
    btn.addEventListener("click", () => core.setHomeFilter(state.model, id));
    bar.appendChild(btn);
  }

  const list = el("div", "sensor-list");
  list.dataset.testid = "home-list";
  const sensors = core.homeSensors(state.model);
  if (sensors.length === 0) {
    const empty = el("div", "sensor-row");
    empty.textContent = "无匹配传感器";
    empty.style.color = "var(--muted)";
    list.appendChild(empty);
  } else {
    for (let i = 0; i < sensors.length; i++) {
      list.appendChild(makeSensorRow(sensors[i]));
    }
  }

  const strip = makeAlarmStrip();
  const actions = el("div", "actions-row");
  const actionDefs = [
    ["详情", "device", true],
    ["趋势", "trend", false],
    ["诊断", "diagnosis", false],
    ["添加", "add_sensor", false],
    ["日志", "logs", false],
  ];
  for (const [label, page, primary] of actionDefs) {
    const btn = el("button", "action-btn" + (primary ? " is-primary" : ""), label);
    btn.type = "button";
    btn.dataset.testid = "home-action-" + page;
    btn.addEventListener("click", () => navigate(page));
    actions.appendChild(btn);
  }

  root.append(bar, list, strip, actions);
  state.homeCtx = { list: list, sig: homeListSig() };
}

function homeListSig() {
  const sensors = core.homeSensors(state.model);
  return (
    state.model.homeFilter +
    ":" +
    sensors.length +
    "|" +
    sensors.map((s) => s.id).join(",")
  );
}

function makeSensorRow(s) {
  const row = el("div", "sensor-row");
  row.dataset.sev = s.severity;
  row.dataset.testid = "sensor-row-" + s.id;
  const line = el("div", "row-main", sensorLine(s));
  row.appendChild(line);
  row.addEventListener("click", () => {
    core.setSelectedSensor(state.model, s.id);
    navigate("device");
  });
  return row;
}

function updateHomeDynamic() {
  if (!state.homeCtx || state.page !== "home") {
    return;
  }
  const counts = core.countByFilter(state.model);
  const labels = [
    "全部 " + counts.all,
    "告警 " + counts.alarm,
    "离线 " + counts.offline,
    "正常 " + counts.ok,
  ];
  const barBtns = document.querySelectorAll(".filter-btn");
  barBtns.forEach((btn, i) => {
    btn.textContent = labels[i];
    btn.classList.toggle("is-active", i === ["all", "alarm", "offline", "ok"].indexOf(state.model.homeFilter));
  });

  const sig = homeListSig();
  if (sig !== state.homeCtx.sig) {
    state.homeCtx.list.textContent = "";
    const sensors = core.homeSensors(state.model);
    if (sensors.length === 0) {
      const empty = el("div", "sensor-row");
      empty.textContent = "无匹配传感器";
      empty.style.color = "var(--muted)";
      state.homeCtx.list.appendChild(empty);
    } else {
      for (const s of sensors) {
        state.homeCtx.list.appendChild(makeSensorRow(s));
      }
    }
    state.homeCtx.sig = sig;
  } else {
    const rows = state.homeCtx.list.children;
    const sensors = core.homeSensors(state.model);
    for (let i = 0; i < rows.length && i < sensors.length; i++) {
      const s = sensors[i];
      rows[i].className = "sensor-row";
      rows[i].dataset.sev = s.severity;
      rows[i].querySelector(".row-main").textContent = sensorLine(s);
    }
  }

  const strip = document.querySelector(".alarm-strip");
  if (strip) {
    applyAlarmStrip(strip, state.model.alarm);
  }
}

function alarmStripText(a) {
  if (!a.active) {
    return "告警摘要: 当前无活动告警";
  }
  const suffix = a.acked ? " 已处理" : a.muted ? " 静音" : "";
  if (a.severity === "offline") {
    return "告警: " + a.title + "  " + a.duration_sec + "s" + suffix;
  }
  return (
    "告警: " +
    a.title +
    "  " +
    core.fmt1(a.value) +
    " / 阈" +
    core.fmt1(a.threshold) +
    "  " +
    a.duration_sec +
    "s" +
    suffix
  );
}

function applyAlarmStrip(strip, a) {
  strip.textContent = alarmStripText(a);
  if (a.active && !a.acked && !a.muted) {
    strip.classList.add("is-active");
    strip.classList.remove("is-crit", "is-offline");
    if (a.severity === "crit") {
      strip.classList.add("is-crit");
    } else if (a.severity === "offline") {
      strip.classList.add("is-offline");
    }
  } else {
    strip.classList.remove("is-active", "is-crit", "is-offline");
  }
}

function makeAlarmStrip() {
  const strip = el("div", "alarm-strip");
  strip.dataset.testid = "home-alarm-strip";
  applyAlarmStrip(strip, state.model.alarm);
  strip.addEventListener("click", () => {
    if (state.model.alarm.active) {
      navigate("alarm");
    } else {
      toast("当前无活动告警");
    }
  });
  return strip;
}

function renderDevice(root) {
  root.className = "page";
  const s = core.getSelectedSensor(state.model);

  const head = el("div", "card dev-head");
  const left = el("div", "dev-left");
  const title = el("div", "dev-title", s.name);
  const value = el("div", "dev-value " + SEV_CLASS[s.severity]);
  value.dataset.testid = "device-value";
  value.textContent = s.online ? core.fmt1(s.value) + " " + s.unit : "-- " + s.unit;
  left.append(title, value);
  const chip = el("span", "chip chip-" + s.severity, core.severityLabelZh(s.severity));
  head.append(left, chip);

  const body = el("div", "card dev-body");
  const rows = [
    ["通信质量", s.quality_pct + "%"],
    ["采集周期", s.period_ms + " ms"],
    ["寄存器", "0x" + s.reg_addr.toString(16).toUpperCase().padStart(4, "0")],
    ["预警/严重阈值", core.fmt1(s.thr_warn) + " / " + core.fmt1(s.thr_crit) + " " + s.unit],
    ["下限阈值", core.fmt1(s.thr_low) + " " + s.unit],
    ["最近采样", s.age_sec + " s 前"],
    ["连接状态", s.online ? "在线" : "离线"],
    ["设备 ID", s.id],
  ];
  for (const [label, val] of rows) {
    const row = el("div", "metric-row");
    row.append(el("span", "metric-label", label), el("span", "metric-value", val));
    body.appendChild(row);
  }

  const cta = el("button", "dev-cta", "查看实时趋势");
  cta.type = "button";
  cta.dataset.testid = "device-goto-trend";
  cta.addEventListener("click", () => navigate("trend"));

  root.append(head, body, cta);
}

function renderTrend(root) {
  root.className = "page";
  const s = core.getSelectedSensor(state.model);

  const head = el("div", "trend-head");
  const cur = el("div", "trend-current");
  cur.append(el("span", "trend-label", "当前"));
  const value = el("span", "trend-value " + SEV_CLASS[s.severity]);
  value.dataset.testid = "trend-value";
  value.textContent = s.online ? core.fmt1(s.value) + " " + s.unit : "-- " + s.unit;
  cur.appendChild(value);
  const meta = el(
    "span",
    "trend-meta",
    "阈值 预警" + core.fmt1(s.thr_warn) + " / 严重" + core.fmt1(s.thr_crit)
  );
  head.append(cur, meta);

  const canvas = el("canvas", "trend-canvas");
  canvas.dataset.testid = "trend-canvas";
  root.append(head, canvas);
  drawTrend(canvas, s);
}

function drawTrend(canvas, s) {
  const rect = canvas.getBoundingClientRect();
  const w = Math.max(40, rect.width);
  const h = Math.max(40, rect.height);
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#24292e";
  ctx.fillRect(0, 0, w, h);

  const minV = (s.thr_low - 5) * 10;
  let maxV = (s.thr_crit + 10) * 10;
  if (maxV <= minV) {
    maxV = minV + 200;
  }
  const padL = 4;
  const padR = 4;
  const padT = 6;
  const padB = 4;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  const xAt = (i) => padL + (i / (core.VG_HISTORY_LEN - 1)) * plotW;
  const yAt = (v) => padT + (1 - (v - minV) / (maxV - minV)) * plotH;

  ctx.strokeStyle = "#3a424a";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = padT + (i / 4) * plotH;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(w - padR, y);
    ctx.stroke();
  }
  for (let i = 0; i <= 6; i++) {
    const x = padL + (i / 6) * plotW;
    ctx.beginPath();
    ctx.moveTo(x, padT);
    ctx.lineTo(x, h - padB);
    ctx.stroke();
  }

  function line(values, color) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i < values.length; i++) {
      const x = xAt(i);
      const y = yAt(values[i]);
      if (i === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.stroke();
  }

  const hist = s.history || [];
  if (hist.length >= 2) {
    const vals = hist.map((v) => v * 10);
    line(vals, "#1c7ed6");
  }
  line([s.thr_warn * 10, s.thr_warn * 10], "#f0a202");
  line([s.thr_crit * 10, s.thr_crit * 10], "#e03131");
}

function renderAlarm(root) {
  root.className = "page";
  const a = state.model.alarm;
  const s = core.getPrimarySensor(state.model);

  const head = el("div", "card alarm-head");
  const title = el("span", "alarm-title", a.active ? a.title : "无活动告警");
  const chip = el(
    "span",
    "chip chip-" + (a.active ? a.severity : "ok"),
    a.active ? core.severityLabelZh(a.severity) : "正常"
  );
  head.append(title, chip);

  const body = el("div", "card alarm-body");
  const rows = [
    ["当前值", a.active && a.severity !== "offline" ? core.fmt1(a.value) + " " + s.unit : "--"],
    ["阈值", a.active && a.severity !== "offline" ? core.fmt1(a.threshold) + " " + s.unit : "--"],
    ["持续", a.active ? a.duration_sec + " s" : "--"],
    ["传感器", s.name],
    ["状态", a.active ? (a.acked ? "已处理" : a.muted ? "已静音" : "活动中") : "无"],
  ];
  for (const [label, val] of rows) {
    const row = el("div", "metric-row");
    row.append(el("span", "metric-label", label), el("span", "metric-value", val));
    body.appendChild(row);
  }

  const hist = s.history || [];
  const npts = Math.min(8, hist.length);
  const histText =
    npts === 0
      ? "历史: --"
      : "历史: " + hist.slice(hist.length - npts).map(core.fmt1).join(" ");
  body.appendChild(el("div", "hist-label", histText));

  const actions = el("div", "alarm-actions");
  const diagBtn = el("button", "alarm-btn is-primary", "AI诊断");
  diagBtn.type = "button";
  diagBtn.dataset.testid = "alarm-goto-diagnosis";
  diagBtn.addEventListener("click", () => navigate("diagnosis"));
  const muteBtn = el("button", "alarm-btn", "静音");
  muteBtn.type = "button";
  muteBtn.dataset.testid = "alarm-mute";
  muteBtn.disabled = !a.active || a.muted;
  muteBtn.addEventListener("click", () => {
    core.muteAlarm(state.model);
    toast("已静音");
  });
  const ackBtn = el("button", "alarm-btn", "标记处理");
  ackBtn.type = "button";
  ackBtn.dataset.testid = "alarm-ack";
  ackBtn.disabled = !a.active || a.acked;
  ackBtn.addEventListener("click", () => {
    core.ackAlarm(state.model);
    toast("已标记处理");
  });
  actions.append(diagBtn, muteBtn, ackBtn);

  root.append(head, body, actions);
}

function riskChip(risk) {
  const sev = risk === "high" ? "crit" : risk === "medium" ? "warn" : "ok";
  return el("span", "chip chip-" + sev, "风险 " + core.riskLabelZh(risk));
}

function renderDiagnosis(root) {
  root.className = "page";
  const d = state.model.diagnosis;
  const box = el("div", "diag-box card" + (d.state === "ok" ? " is-ok" : ""));
  box.dataset.testid = "diag-state";
  box.dataset.diagState = d.state;

  if (d.state === "loading") {
    const line = el("div", "diag-loading-text");
    line.appendChild(el("span", "spinner"));
    const text = el("span", "", "诊断中...");
    text.dataset.testid = "diag-loading";
    line.appendChild(text);
    box.appendChild(line);
    if (state.mode === "real") {
      box.appendChild(el("div", "diag-note", "已发布请求，等待 AI Bridge 响应..."));
    }
  } else if (d.state === "error") {
    const lab = el("div", "diag-error-label");
    lab.dataset.testid = "diag-error";
    lab.textContent = d.error_code ? d.error_code + ": " + d.error_msg : d.error_msg;
    box.appendChild(lab);
    const retry = el("button", "diag-retry", "重试");
    retry.type = "button";
    retry.dataset.testid = "diag-retry";
    retry.addEventListener("click", () => startDiagnosisIfIdle(true));
    box.appendChild(retry);
  } else if (d.state === "ok") {
    const summary = el("div", "diag-summary");
    summary.dataset.testid = "diag-summary";
    summary.textContent = d.summary;
    box.appendChild(summary);

    if (d.degraded) {
      const hint = el("div", "degraded-hint");
      hint.dataset.testid = "diag-degraded";
      hint.textContent =
        "降级提示：AI Bridge 返回模板结果（source=fallback, advisory_only）。" +
        (d.fallback_reason ? " 原因: " + d.fallback_reason : "");
      box.appendChild(hint);
    }
    if (d.need_shutdown) {
      const shutdown = el("div", "degraded-hint");
      shutdown.textContent = "AI 建议：尽快安排停机检查（仅建议，不自动执行）。";
      box.appendChild(shutdown);
    }

    const headRow = el("div", "diag-head-row");
    headRow.appendChild(riskChip(d.risk));
    const conf = el("span", "diag-conf");
    conf.dataset.testid = "diag-confidence";
    conf.textContent =
      d.confidence_pct === null || d.confidence_pct === undefined
        ? "置信 --"
        : "置信 " + d.confidence_pct + "%";
    headRow.appendChild(conf);
    box.appendChild(headRow);

    box.appendChild(el("div", "diag-section-title", "可能原因"));
    for (const c of d.causes) {
      box.appendChild(el("div", "diag-line", "· " + c));
    }
    box.appendChild(el("div", "diag-section-title", "建议动作"));
    for (const c of d.actions) {
      box.appendChild(el("div", "diag-line", "· " + c));
    }
    box.appendChild(el("div", "diag-note", "注: AI 只建议不执行"));
  } else {
    // idle: same presentation as loading, matching the C page's default box.
    const line = el("div", "diag-loading-text");
    line.appendChild(el("span", "spinner"));
    line.appendChild(el("span", "", "诊断中..."));
    box.appendChild(line);
  }

  root.appendChild(box);
}

function renderLogs(root) {
  root.className = "page";
  const list = el("div", "log-list");
  list.dataset.testid = "log-list";
  const logs = state.model.logs;
  if (logs.length === 0) {
    list.appendChild(el("div", "log-row", "暂无日志"));
  } else {
    for (let i = logs.length - 1; i >= 0; i--) {
      const e = logs[i];
      const row = el(
        "div",
        "log-row " + SEV_CLASS[e.severity],
        "[" + e.time + "] [" + core.logTypeLabelZh(e.type) + "] " + e.text
      );
      list.appendChild(row);
    }
  }
  root.appendChild(list);
}

/* =====================================================================
 * Unified request service diagnosis flow.
 * ===================================================================== */

function getDeviceId() {
  const input = $("f-device-id");
  return (input && input.value.trim()) || "dev01";
}

function pushTraffic(item) {
  state.traffic.unshift(Object.assign({ ts: Date.now() }, item));
  if (state.traffic.length > 24) {
    state.traffic.length = 24;
  }
  const list = $("traffic-list");
  if (!list) return;
  list.textContent = "";
  for (const entry of state.traffic) {
    const li = el("li", "traffic-item");
    const head = el("div", "traffic-head");
    head.appendChild(el("span", "traffic-kind", entry.kind || "event"));
    head.appendChild(el("span", "traffic-time", new Date(entry.ts).toLocaleTimeString()));
    const topic = el("div", "traffic-topic mono", entry.topic || "");
    const body = el("pre", "traffic-body");
    body.textContent = JSON.stringify(entry.payload || {}, null, 2);
    li.append(head, topic, body);
    list.appendChild(li);
  }
}

function clearTraffic() {
  state.traffic = [];
  const list = $("traffic-list");
  if (list) list.textContent = "";
}

function applyEnvelopeToBoard(envelope, reqId, source) {
  if (!envelope) return;
  if (envelope.status === "processing") {
    state.model.diagnosis.state = "loading";
    renderPage();
    return;
  }
  if (envelope.status === "success") {
    const mapped = core.mapResultToDiagnosis(envelope.result);
    if (mapped) {
      core.applyResultToDiagnosis(state.model, mapped);
      state.lastTerminal = { reqId, status: "success", source: mapped.source, error_code: null };
    } else {
      core.applyErrorToDiagnosis(state.model, { error_code: "provider_error", error_message: "响应缺少有效诊断结果" });
      state.lastTerminal = { reqId, status: "error", source: null, error_code: "provider_error" };
    }
  } else if (envelope.status === "error") {
    core.applyErrorToDiagnosis(state.model, envelope);
    state.lastTerminal = { reqId, status: "error", source: null, error_code: envelope.error_code };
  }
  if (source === "board") {
    toast(envelope.status === "success" ? "诊断完成" : "诊断失败: " + (envelope.error_code || "unknown"));
  } else if (envelope.status === "success" && getDeviceId() === String(envelope.device_id || "")) {
    toast("调试台诊断已同步到板端");
  }
  renderPage();
}

function handleUnifiedServiceEvent(detail) {
  if (!detail) return;
  if (detail.kind === "connection") {
    state.mqtt.status = detail.status;
    return;
  }
  if (detail.kind === "mode") {
    if (detail.mode === "real" && state.mode === "mock") {
      core.cancelMockDiagnosis(state.model);
    }
    state.mode = detail.mode;
    renderPage();
    return;
  }
  if (detail.kind === "traffic") {
    const isOut = detail.direction === "out";
    const isProcessing = detail.status === "processing";
    pushTraffic({
      kind: isOut ? (detail.mode === "mock" ? "diagnosis_req" : "mqtt_publish") : (isProcessing ? "mqtt_processing" : "diagnosis_terminal"),
      topic: detail.topic,
      payload: detail.payload,
      reqId: detail.reqId,
      status: detail.status,
      source: detail.source,
      errorCode: detail.errorCode,
    });
    return;
  }
  if (detail.kind === "response") {
    if (detail.deviceId === getDeviceId() || detail.source === "board") {
      applyEnvelopeToBoard(detail.envelope, detail.reqId, detail.source);
    }
    return;
  }
  if (detail.kind === "failure" && (detail.source === "board" || detail.deviceId === getDeviceId())) {
    core.applyErrorToDiagnosis(state.model, { error_code: detail.errorCode || "send_failed", error_message: detail.message || "请求失败" });
    state.lastTerminal = { reqId: detail.reqId || null, status: "error", source: null, error_code: detail.errorCode || "send_failed" };
    toast(detail.message || "诊断失败");
    renderPage();
  }
}

function startDiagnosisIfIdle(force) {
  const d = state.model.diagnosis;
  if (!force && d.state === "loading") {
    return;
  }
  runUnifiedDiagnosis();
}

async function runUnifiedDiagnosis() {
  const d = state.model.diagnosis;
  const reqId = core.newReqId();
  state.lastTerminal = null;
  const deviceId = getDeviceId();
  const ctx = core.buildDiagnosisContext(state.model);
  let built;
  try {
    built = await core.buildRequest({
      req_id: reqId,
      device_id: deviceId,
      created_ts_ms: Date.now(),
      context: ctx,
      note: "board simulator",
    });
  } catch (err) {
    core.applyErrorToDiagnosis(state.model, { error_code: "internal_error", error_message: "请求构建失败: " + (err.message || String(err)) });
    renderPage();
    return;
  }
  d.alarm_title = state.model.alarm.active ? state.model.alarm.title : "无活动告警";
  const service = window.__requestService;
  if (!service) {
    core.applyErrorToDiagnosis(state.model, { error_code: "internal_error", error_message: "统一请求服务未初始化" });
    renderPage();
    return;
  }
  service.setMode(state.mode);
  if (state.mode === "real") {
    d.state = "loading";
    renderPage();
    const current = service.getState();
    if (current.status !== "connected") {
      service.connect({
        url: $("f-broker-url").value.trim(),
        clientId: $("f-client-id").value.trim(),
        username: $("f-mqtt-user").value.trim(),
        password: $("f-mqtt-pass").value,
      });
      const connected = await service.waitForConnection(9000);
      if (!connected) {
        core.applyErrorToDiagnosis(state.model, { error_code: "mqtt_connect", error_message: "无法连接 broker，可切换到 Mock 继续演示" });
        renderPage();
        return;
      }
    }
    service.send({ source: "board", request: built });
    return;
  }

  const result = await core.runMockDiagnosis(state.model, state.model.scenario);
  if (!result) return;
  const terminal = {
    req_id: reqId,
    device_id: deviceId,
    type: core.REQUEST_TYPE,
    status: result.state === "ok" ? "success" : "error",
    error_code: result.state === "error" ? result.error_code : null,
    error_message: result.state === "error" ? result.error_msg : null,
    received_ts_ms: Date.now(),
    bridge_ts_ms: Date.now(),
    result: result.state === "ok" ? {
      diagnosis_summary: result.summary,
      risk_level: result.risk,
      possible_causes: result.causes,
      recommended_actions: result.actions,
      confidence: Number(result.confidence_pct || 0) / 100,
      need_shutdown: false,
      source: "mock",
    } : null,
  };
  const processing = {
    req_id: reqId,
    device_id: deviceId,
    type: core.REQUEST_TYPE,
    status: "processing",
    received_ts_ms: Date.now(),
    bridge_ts_ms: Date.now(),
  };
  service.recordMock({ source: "board", request: built, processing, terminal });
}

/* =====================================================================
 * Toolbar wiring and model change handling.
 * ===================================================================== */

function updateScenarioButtons() {
  document.querySelectorAll(".scenario-btn").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.scenario === state.model.scenario);
  });
}

function buildScenarioButtons() {
  const box = $("scenario-buttons");
  box.textContent = "";
  for (const s of core.SCENARIOS) {
    const btn = el("button", "scenario-btn", s.label);
    btn.type = "button";
    btn.dataset.scenario = s.id;
    btn.dataset.testid = "scenario-" + s.id;
    btn.addEventListener("click", () => {
      core.setScenario(state.model, s.id);
      renderPage();
    });
    box.appendChild(btn);
  }
}

function syncModeFromService(mode) {
  state.mode = mode === "mock" ? "mock" : "real";
  renderPage();
}

function onModelChange() {
  refreshStatusBar();
  updateScenarioButtons();
  updateHomeDynamic();
  if (state.page === "home") {
    return;
  }
  const content = $("content");
  content.textContent = "";
  if (state.page === "device") {
    renderDevice(content);
  } else if (state.page === "trend") {
    renderTrend(content);
  } else if (state.page === "alarm") {
    renderAlarm(content);
  } else if (state.page === "diagnosis") {
    renderDiagnosis(content);
  } else if (state.page === "logs") {
    renderLogs(content);
  }
}

function updateScale() {
  const stage = document.querySelector(".board-stage");
  const scaleEl = $("board-scale");
  const frame = $("board-frame");
  if (!stage || !scaleEl || !frame) {
    return;
  }
  const w = stage.clientWidth;
  const h = stage.clientHeight;
  const scale = Math.max(0.1, Math.min(w / core.VG_DISP_W, h / core.VG_DISP_H));
  scaleEl.style.width = core.VG_DISP_W * scale + "px";
  scaleEl.style.height = core.VG_DISP_H * scale + "px";
  frame.style.transform = "scale(" + scale + ")";
}

function init() {
  state.model = core.createModel();
  core.onChange(state.model, onModelChange);

  $("back-btn").addEventListener("click", goBack);
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      goBack();
    } else if (ev.key >= "1" && ev.key <= "6") {
      const scenario = core.SCENARIOS[Number(ev.key) - 1].id;
      core.setScenario(state.model, scenario);
      renderPage();
    }
  });

  document.addEventListener("request-service-event", (event) => handleUnifiedServiceEvent(event.detail));
  const drawer = $("debug-drawer");
  const drawerToggle = $("debug-drawer-toggle");
  const drawerClose = $("debug-drawer-close");
  const drawerCollapse = $("debug-drawer-collapse");
  const setDrawerOpen = (open) => {
    if (!drawer || !drawerToggle) return;
    drawer.hidden = !open;
    drawerToggle.setAttribute("aria-expanded", String(open));
    drawerToggle.textContent = open ? "关闭调试台" : "打开调试台";
    requestAnimationFrame(updateScale);
  };
  drawerToggle && drawerToggle.addEventListener("click", () => setDrawerOpen(drawer.hidden));
  drawerClose && drawerClose.addEventListener("click", () => setDrawerOpen(false));
  drawerCollapse && drawerCollapse.addEventListener("click", () => setDrawerOpen(false));
  $("traffic-toggle").addEventListener("click", () => {
    const panel = $("traffic-panel");
    const open = panel.hidden;
    panel.hidden = !open;
    $("traffic-toggle").setAttribute("aria-expanded", String(open));
  });
  $("btn-clear-traffic").addEventListener("click", clearTraffic);

  buildScenarioButtons();
  renderPage();
  updateScale();
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(updateScale).observe(document.querySelector(".board-stage"));
  } else {
    window.addEventListener("resize", updateScale);
  }

  setInterval(() => {
    $("status-time").textContent = formatClock(new Date());
  }, 1000);
  $("status-time").textContent = formatClock(new Date());
  setInterval(() => {
    core.modelTick(state.model);
  }, 2000);

  // Test / automation hook.
  window.__boardSim = {
    getState: () => ({
      mode: state.mode,
      page: state.page,
      scenario: state.model.scenario,
      diagnosis: state.model.diagnosis,
      mqttStatus: state.mqtt.status,
      trafficCount: state.traffic.length,
      lastTerminal: state.lastTerminal,
      sensorCount: state.model.sensors.length,
    }),
  };
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
