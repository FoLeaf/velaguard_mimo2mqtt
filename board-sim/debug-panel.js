(function initDebugPanel(window) {
  "use strict";

  const core = window.BoardCore;
  const debugCore = window.DebugCore;
  const pyDumps = core.pyDumps;
  const sha256Sync = core.sha256Sync;
  const computePayloadHash = core.computePayloadHash;
  const parseJsonPreservingInts = core.parseJsonPreservingInts;
  const PyInt = core.PyInt;
  const newReqId = core.newReqId;
  const normalizeEnvelope = core.normalizeEnvelope;
  const { REQUEST_TYPE, REQUEST_NOTE, HISTORY_LIMIT, MQTT_DEFAULT_URL, MQTT_CONNECT_TIMEOUT_MS, REAL_RESPONSE_TIMEOUT_MS, SCENARIOS, STATUS_CLASS, ERROR_CLASS, scenarioById, buildEnvelope, buildTerminalEnvelope } = debugCore;

  /* =====================================================================
   * Presets and context form helpers.
   * ===================================================================== */

  const PRESETS = {
    temp: {
      label: "温度超限",
      context: {
        event: {
          event_id: "evt_temp_over",
          severity: "warning",
          title: "温度持续超限",
          current_value: 82.4,
          ts_ms: 1782450000000,
        },
        history: [
          { ts_ms: 1782448800000, values: { temperature: 75.1, fan_rpm: 2800 } },
          { ts_ms: 1782449400000, values: { temperature: 78.6, fan_rpm: 2750 } },
          { ts_ms: 1782450000000, values: { temperature: 82.4, fan_rpm: 2600 } },
        ],
        rules: [
          { rule_id: "r1", expr: "temperature > 75" },
          { rule_id: "r2", expr: "fan_rpm < 3000" },
        ],
        device: { name: "主轴电机", model: "RS485-TH-1", description: "生产线 2 号主轴温度监测点" },
      },
    },
    humidity: {
      label: "湿度偏低",
      context: {
        event: {
          event_id: "evt_hum_low",
          severity: "warning",
          title: "湿度低于下限",
          current_value: 32.5,
          ts_ms: 1782450000000,
        },
        history: [
          { ts_ms: 1782448800000, values: { humidity: 38.2 } },
          { ts_ms: 1782449400000, values: { humidity: 35.1 } },
          { ts_ms: 1782450000000, values: { humidity: 32.5 } },
        ],
        rules: [{ rule_id: "rh1", expr: "humidity < 40" }],
        device: { name: "温室传感器", model: "SHT31", description: "3 号温室环境监测点" },
      },
    },
    empty: {
      label: "空上下文",
      context: null,
    },
  };

  const CONTEXT_SECTIONS = ["event", "history", "rules", "device"];

  function contextSectionEl(name) {
    return document.querySelector('.context-section[data-section="' + name + '"]');
  }

  function makeInput(attrs) {
    const input = document.createElement("input");
    input.type = "text";
    for (const [key, value] of Object.entries(attrs)) {
      input.setAttribute(key, value);
    }
    return input;
  }

  function makeField(labelText, input) {
    const label = document.createElement("label");
    label.className = "field";
    const span = document.createElement("span");
    span.textContent = labelText;
    label.append(span, input);
    return label;
  }

  function makeRemoveButton() {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-ghost btn-remove";
    btn.textContent = "×";
    btn.title = "删除该条";
    return btn;
  }

  function addRow(sectionName, data) {
    const sectionEl = contextSectionEl(sectionName);
    const rowsBox = sectionEl.querySelector(".mode-form [data-rows]");
    const row = document.createElement("div");
    row.className = "row-item";
    const fields = document.createElement("div");
    fields.className = "row-fields";

    if (sectionName === "history") {
      fields.appendChild(
        makeField(
          "ts_ms",
          makeInput({
            "data-key": "ts_ms",
            inputmode: "numeric",
            value: data && data.ts_ms !== undefined ? String(data.ts_ms) : "",
          })
        )
      );
      fields.appendChild(
        makeField(
          "values JSON",
          makeInput({
            "data-key": "values",
            spellcheck: "false",
            placeholder: '{"temperature": 82.4}',
            value: data && data.values !== undefined ? JSON.stringify(data.values, null, 2) : "",
          })
        )
      );
    } else {
      fields.appendChild(
        makeField(
          "rule_id",
          makeInput({
            "data-key": "rule_id",
            value: data && data.rule_id !== undefined ? String(data.rule_id) : "",
          })
        )
      );
      fields.appendChild(
        makeField(
          "expr",
          makeInput({
            "data-key": "expr",
            value: data && data.expr !== undefined ? String(data.expr) : "",
          })
        )
      );
    }

    row.append(fields, makeRemoveButton());
    rowsBox.appendChild(row);
  }

  function clearSection(name) {
    const sectionEl = contextSectionEl(name);
    for (const input of sectionEl.querySelectorAll(".mode-form input, .mode-form select")) {
      input.value = "";
    }
    const rowsBox = sectionEl.querySelector(".mode-form [data-rows]");
    if (rowsBox) {
      rowsBox.textContent = "";
    }
    const textarea = sectionEl.querySelector(".mode-json textarea");
    if (textarea) {
      textarea.value = "";
    }
    clearSectionError(name);
  }

  function populateForm(name, value) {
    const sectionEl = contextSectionEl(name);
    if (name === "event" || name === "device") {
      if (!value || typeof value !== "object" || Array.isArray(value)) {
        showSectionError(name, name + " 必须是 JSON 对象");
        return false;
      }
      for (const input of sectionEl.querySelectorAll(".mode-form [data-key]")) {
        const key = input.dataset.key;
        if (value[key] !== undefined) {
          input.value = String(value[key]);
        }
      }
      return true;
    }
    if (name === "history" || name === "rules") {
      if (value === undefined || value === null) {
        return true;
      }
      if (!Array.isArray(value)) {
        showSectionError(name, name + " 必须是 JSON 数组");
        return false;
      }
      sectionEl.querySelector(".mode-form [data-rows]").textContent = "";
      for (const item of value) {
        addRow(name, item);
      }
      return true;
    }
    return true;
  }

  function collectObjectForm(sectionName, numericKeys) {
    const sectionEl = contextSectionEl(sectionName);
    const value = {};
    let any = false;
    for (const input of sectionEl.querySelectorAll(".mode-form [data-key]")) {
      const raw = input.value.trim();
      if (!raw) {
        continue;
      }
      const key = input.dataset.key;
      if (numericKeys.includes(key)) {
        if (!/^-?\d+(\.\d+)?$/.test(raw)) {
          return { ok: false, message: key + " 必须是数字" };
        }
        value[key] = /^-?\d+$/.test(raw) ? new PyInt(BigInt(raw)) : Number(raw);
      } else {
        value[key] = raw;
      }
      any = true;
    }
    return { ok: true, value: any ? value : undefined };
  }

  function collectArrayForm(sectionName) {
    const sectionEl = contextSectionEl(sectionName);
    const rows = sectionEl.querySelectorAll(".mode-form .row-item");
    const out = [];
    for (const row of rows) {
      if (sectionName === "history") {
        const tsRaw = row.querySelector('[data-key="ts_ms"]').value.trim();
        const valuesRaw = row.querySelector('[data-key="values"]').value.trim();
        if (!tsRaw && !valuesRaw) {
          continue;
        }
        const entry = {};
        if (tsRaw) {
          if (!/^-?\d+$/.test(tsRaw)) {
            return { ok: false, message: "history 条目 ts_ms 必须是整数" };
          }
          entry.ts_ms = new PyInt(BigInt(tsRaw));
        }
        if (valuesRaw) {
          let parsed;
          try {
            JSON.parse(valuesRaw);
            parsed = parseJsonPreservingInts(valuesRaw);
          } catch (err) {
            return { ok: false, message: "history 条目 values JSON 解析失败：" + err.message };
          }
          if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
            return { ok: false, message: "history 条目 values 必须是 JSON 对象" };
          }
          entry.values = parsed;
        }
        out.push(entry);
      } else {
        const ruleId = row.querySelector('[data-key="rule_id"]').value.trim();
        const expr = row.querySelector('[data-key="expr"]').value.trim();
        if (!ruleId && !expr) {
          continue;
        }
        const entry = {};
        if (ruleId) {
          entry.rule_id = ruleId;
        }
        if (expr) {
          entry.expr = expr;
        }
        out.push(entry);
      }
    }
    return { ok: true, value: out.length ? out : undefined };
  }

  function collectFormValue(sectionName) {
    if (sectionName === "event") {
      return collectObjectForm(sectionName, ["current_value", "ts_ms"]);
    }
    if (sectionName === "device") {
      return collectObjectForm(sectionName, []);
    }
    return collectArrayForm(sectionName);
  }

  function showSectionError(name, message) {
    const errEl = contextSectionEl(name).querySelector(".field-error");
    errEl.textContent = message;
    errEl.hidden = false;
  }

  function clearSectionError(name) {
    const errEl = contextSectionEl(name).querySelector(".field-error");
    errEl.textContent = "";
    errEl.hidden = true;
  }

  function setSectionMode(name, mode, force) {
    const sectionEl = contextSectionEl(name);
    const formBox = sectionEl.querySelector(".mode-form");
    const jsonBox = sectionEl.querySelector(".mode-json");

    if (!force && mode === "json") {
      const collected = collectFormValue(name);
      if (!collected.ok) {
        showSectionError(name, collected.message);
        return;
      }
      jsonBox.querySelector("textarea").value =
        collected.value === undefined ? "" : JSON.stringify(collected.value, null, 2);
    }
    if (!force && mode === "form") {
      const raw = jsonBox.querySelector("textarea").value.trim();
      if (raw) {
        let parsed;
        try {
          parsed = JSON.parse(raw);
        } catch (err) {
          showSectionError(name, "JSON 解析失败：" + err.message);
          return;
        }
        const applied = populateForm(name, parsed);
        if (!applied) {
          return;
        }
      }
    }

    formBox.hidden = mode !== "form";
    jsonBox.hidden = mode !== "json";
    sectionEl.dataset.mode = mode;
    for (const btn of sectionEl.querySelectorAll(".mode-btn")) {
      btn.classList.toggle("is-active", btn.dataset.mode === mode);
    }
    clearSectionError(name);
  }

  function applyPreset(presetId) {
    const preset = PRESETS[presetId];
    for (const name of CONTEXT_SECTIONS) {
      setSectionMode(name, "form", true);
      clearSection(name);
      const value = preset.context && preset.context[name];
      if (value !== undefined && value !== null) {
        populateForm(name, value);
      }
    }
  }

  /* =====================================================================
   * Request collection and payload_hash preview.
   * ===================================================================== */

  function collectContext() {
    const out = {};
    let hasAny = false;
    for (const name of CONTEXT_SECTIONS) {
      const sectionEl = contextSectionEl(name);
      if (sectionEl.dataset.mode === "json") {
        const raw = sectionEl.querySelector("textarea").value.trim();
        if (!raw) {
          continue;
        }
        let parsed;
        try {
          JSON.parse(raw);
          parsed = parseJsonPreservingInts(raw);
        } catch (err) {
          showSectionError(name, "JSON 解析失败：" + err.message);
          return { ok: false, message: err.message };
        }
        clearSectionError(name);
        if (parsed === null || parsed === undefined) {
          continue;
        }
        out[name] = parsed;
        hasAny = true;
      } else {
        const collected = collectFormValue(name);
        if (!collected.ok) {
          showSectionError(name, collected.message);
          return { ok: false, message: collected.message };
        }
        clearSectionError(name);
        if (collected.value !== undefined) {
          out[name] = collected.value;
          hasAny = true;
        }
      }
    }
    return { ok: true, context: hasAny ? out : null };
  }

  function collectRequest() {
    const errors = [];
    const reqId = document.getElementById("f-req-id").value.trim();
    const deviceId = document.getElementById("f-device-id").value.trim();
    const tsRaw = document.getElementById("f-created-ts").value.trim();

    if (!reqId) {
      errors.push("req_id 不能为空");
    }
    if (!deviceId) {
      errors.push("device_id 不能为空");
    }
    let createdTsMs = null;
    if (!/^-?\d+$/.test(tsRaw)) {
      errors.push("created_ts_ms 必须是整数");
    } else {
      const createdTsNumber = Number(tsRaw);
      if (!Number.isSafeInteger(createdTsNumber) || createdTsNumber < 0) {
        errors.push("created_ts_ms 必须是非负整数且在安全整数范围内");
      } else {
        createdTsMs = new PyInt(createdTsNumber);
      }
    }

    const ctx = collectContext();
    if (!ctx.ok) {
      errors.push(ctx.message || "上下文存在编辑错误");
    }
    if (errors.length) {
      return { ok: false, errors };
    }

    const body = {
      req_id: reqId,
      device_id: deviceId,
      created_ts_ms: createdTsMs,
      type: REQUEST_TYPE,
      note: REQUEST_NOTE,
    };
    if (ctx.context) {
      body.context = ctx.context;
    }
    return {
      ok: true,
      request: {
        req_id: reqId,
        device_id: deviceId,
        created_ts_ms: createdTsMs,
        context: ctx.context,
        body,
      },
    };
  }

  function previewJson(body, hash) {
    const shown = {};
    Object.assign(shown, body);
    if (hash) {
      shown.payload_hash = hash;
    }
    return JSON.stringify(shown, null, 2);
  }

  async function updateHashAndPreview() {
    const version = ++state.hashVersion;
    const collected = collectRequest();
    const hashInput = document.getElementById("f-payload-hash");
    const preview = document.getElementById("request-preview");

    if (!collected.ok) {
      hashInput.value = "（存在编辑错误，无法计算）";
      preview.textContent = "无法生成请求：\n" + collected.errors.join("\n");
      return;
    }

    hashInput.value = "（计算中…）";
    preview.textContent = previewJson(collected.request.body, null);
    const hash = await computePayloadHash(collected.request.body);
    if (version !== state.hashVersion) {
      return;
    }
    hashInput.value = hash;
    preview.textContent = previewJson(collected.request.body, hash);
  }

  /* =====================================================================
   * Small DOM / time / clipboard helpers.
   * ===================================================================== */

  function formatTime(ts) {
    const d = new Date(ts);
    const p = (n, w) => String(n).padStart(w || 2, "0");
    return (
      p(d.getHours()) +
      ":" +
      p(d.getMinutes()) +
      ":" +
      p(d.getSeconds()) +
      "." +
      p(d.getMilliseconds(), 3)
    );
  }

  /* UUID generation is shared by BoardCore. */

  function showStatus(message, kind) {
    const el = document.getElementById("status-message");
    el.textContent = message;
    el.className = "status-message" + (kind ? " is-" + kind : "");
    clearTimeout(statusTimer);
    statusTimer = setTimeout(() => {
      el.textContent = "";
      el.className = "status-message";
    }, kind === "error" ? 8000 : 5000);
  }

  async function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (err) {
        // Fall through to the legacy path.
      }
    }
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (err) {
      ok = false;
    }
    document.body.removeChild(ta);
    return ok;
  }

  function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function emptyItem(text) {
    const li = document.createElement("li");
    li.className = "empty-item";
    li.textContent = text;
    return li;
  }

  /* =====================================================================
   * Viewer, timeline and history rendering.
   * ===================================================================== */

  function buildTreeItem(value, key) {
    if (Array.isArray(value)) {
      const details = document.createElement("details");
      details.open = true;
      const summary = document.createElement("summary");
      summary.textContent = key + "  Array(" + value.length + ")";
      details.appendChild(summary);
      value.forEach((item, i) => details.appendChild(buildTreeItem(item, "[" + i + "]")));
      return details;
    }
    if (value && typeof value === "object") {
      const details = document.createElement("details");
      details.open = true;
      const summary = document.createElement("summary");
      summary.textContent = key + "  Object";
      details.appendChild(summary);
      Object.keys(value).forEach((k) => details.appendChild(buildTreeItem(value[k], k)));
      return details;
    }
    const leaf = document.createElement("div");
    leaf.className = "tree-leaf";
    const keyEl = document.createElement("span");
    keyEl.className = "tree-key";
    keyEl.textContent = key + ":";
    const valEl = document.createElement("span");
    valEl.className = "tree-val";
    valEl.textContent = typeof value === "string" ? JSON.stringify(value) : String(value);
    leaf.append(keyEl, valEl);
    return leaf;
  }

  function renderResultTree(container, value) {
    container.textContent = "";
    if (value === null || value === undefined) {
      container.textContent = "null";
      return;
    }
    container.appendChild(buildTreeItem(value, "result"));
  }

  function renderResult(view) {
    state.resultView = view;
    const entry = state.history.find((e) => e.id === state.activeEntryId);
    const event = entry ? entry.events[state.activeEventIndex] : null;
    const value = event && event.envelope ? event.envelope.result : null;
    const treeBox = document.getElementById("result-tree");
    const jsonBox = document.getElementById("result-json");
    const isTree = view === "tree";
    treeBox.hidden = !isTree;
    jsonBox.hidden = isTree;
    for (const btn of document.querySelectorAll(".result-head .mode-btn")) {
      btn.classList.toggle("is-active", btn.dataset.view === view);
    }
    if (isTree) {
      renderResultTree(treeBox, value);
    } else {
      jsonBox.textContent = value === null || value === undefined ? "null" : JSON.stringify(value, null, 2);
    }
  }

  function renderViewer(entry, eventIdx) {
    const event = entry.events[eventIdx];
    if (!event || !event.envelope) {
      return;
    }
    const env = event.envelope;
    document.getElementById("response-empty").hidden = true;
    document.getElementById("response-body").hidden = false;
    document.getElementById("r-req-id").textContent = env.req_id;
    document.getElementById("r-device-id").textContent = env.device_id;
    document.getElementById("r-type").textContent = env.type;
    const statusBadge = document.getElementById("r-status");
    statusBadge.textContent = env.status;
    statusBadge.className = "badge " + (STATUS_CLASS[env.status] || "badge-ghost");
    const codeBadge = document.getElementById("r-error-code");
    if (env.error_code) {
      codeBadge.textContent = env.error_code;
      codeBadge.className = "badge " + (ERROR_CLASS[env.error_code] || "badge-ghost");
    } else {
      codeBadge.textContent = "null";
      codeBadge.className = "mono";
    }
    document.getElementById("r-error-message").textContent = env.error_message || "null";
    document.getElementById("r-received-ts").textContent = String(env.received_ts_ms);
    document.getElementById("r-bridge-ts").textContent = String(env.bridge_ts_ms);
    renderResult(state.resultView);
  }

  function resetViewer() {
    document.getElementById("response-body").hidden = true;
    document.getElementById("response-empty").hidden = false;
    renderResult("tree");
    renderTimeline();
  }

  function renderTimeline() {
    const list = document.getElementById("timeline");
    list.textContent = "";
    const entry = state.history.find((e) => e.id === state.activeEntryId);
    if (!entry) {
      list.appendChild(emptyItem("暂无事件"));
      return;
    }
    if (!entry.events.length) {
      list.appendChild(emptyItem("等待首个事件…"));
      return;
    }

    entry.events.forEach((ev, idx) => {
      const li = document.createElement("li");
      li.className = "timeline-item" + (idx === state.activeEventIndex ? " is-active" : "");
      if (ev.kind === "note") {
        const note = document.createElement("span");
        note.className = "timeline-note";
        note.textContent = ev.note;
        li.appendChild(note);
        list.appendChild(li);
        return;
      }
      const head = document.createElement("div");
      head.className = "timeline-head";
      const time = document.createElement("span");
      time.className = "history-time";
      time.textContent = formatTime(ev.wallTs);
      const badge = document.createElement("span");
      badge.className = "badge " + (STATUS_CLASS[ev.envelope.status] || "badge-ghost");
      badge.textContent = ev.envelope.status;
      const kind = document.createElement("span");
      kind.className = "badge badge-ghost";
      kind.textContent = ev.kind === "processing" ? "中间态" : "终态";
      const viewBtn = document.createElement("button");
      viewBtn.type = "button";
      viewBtn.className = "btn btn-ghost";
      viewBtn.textContent = "查看";
      viewBtn.addEventListener("click", () => selectEvent(entry.id, idx));
      head.append(time, badge, kind, viewBtn);

      const meta = document.createElement("div");
      meta.className = "timeline-meta";
      const topic = document.createElement("span");
      topic.className = "mono";
      topic.textContent =
        "topic: " +
        (ev.topic || "vg/" + ev.envelope.device_id + "/ai/response/" + ev.envelope.req_id);
      const stamps = document.createElement("span");
      stamps.className = "mono";
      let stampText =
        "received_ts_ms=" + ev.envelope.received_ts_ms + "  bridge_ts_ms=" + ev.envelope.bridge_ts_ms;
      if (
        typeof ev.envelope.received_ts_ms === "number" &&
        typeof ev.envelope.bridge_ts_ms === "number"
      ) {
        stampText +=
          "  耗时 " + Math.max(0, ev.envelope.bridge_ts_ms - ev.envelope.received_ts_ms) + " ms";
      }
      stamps.textContent = stampText;
      meta.append(topic, stamps);
      li.append(head, meta);
      list.appendChild(li);
    });

    if (entry.status === "pending") {
      const li = document.createElement("li");
      li.className = "timeline-item";
      const wait = document.createElement("span");
      wait.className = "timeline-note";
      wait.textContent = "等待终态（模拟耗时 " + state.delayMs + " ms）…";
      li.appendChild(wait);
      list.appendChild(li);
    }
  }

  function selectEvent(entryId, eventIdx) {
    const entry = state.history.find((e) => e.id === entryId);
    if (!entry || !entry.events[eventIdx] || !entry.events[eventIdx].envelope) {
      return;
    }
    state.activeEntryId = entryId;
    state.activeEventIndex = eventIdx;
    renderViewer(entry, eventIdx);
    renderTimeline();
  }

  function pushEvent(entry, envelope, topic, kind) {
    entry.events.push({ kind, envelope, topic, wallTs: Date.now() });
    renderTimeline();
  }

  function pushNote(entry, note) {
    entry.events.push({ kind: "note", note, wallTs: Date.now() });
  }

  function renderHistory() {
    const list = document.getElementById("history-list");
    list.textContent = "";
    if (!state.history.length) {
      list.appendChild(emptyItem("暂无请求记录"));
      return;
    }
    for (const entry of state.history) {
      const li = document.createElement("li");
      li.className = "history-item";
      const time = document.createElement("span");
      time.className = "history-time";
      time.textContent = formatTime(entry.receivedTs);
      const reqId = document.createElement("span");
      reqId.className = "mono";
      reqId.textContent = entry.reqId;
      reqId.title = entry.reqId;
      const scenario = document.createElement("span");
      scenario.className = "scenario-label";
      scenario.textContent = entry.scenarioLabel;
      const modeBadge = document.createElement("span");
      modeBadge.className = "badge " + (entry.mode === "real" ? "badge-info" : "badge-ghost");
      modeBadge.textContent = entry.mode === "real" ? "真实" : "Mock";
      const badge = document.createElement("span");
      badge.className = "badge " + (STATUS_CLASS[entry.status] || "badge-ghost");
      badge.textContent =
        entry.status === "pending"
          ? "等待终态"
          : entry.status === "superseded"
            ? "已取代"
            : entry.status;
      const viewBtn = document.createElement("button");
      viewBtn.type = "button";
      viewBtn.className = "btn btn-ghost";
      viewBtn.textContent = "查看";
      viewBtn.addEventListener("click", () => {
        const terminalIdx = entry.events.reduce(
          (acc, ev, idx) => (ev.envelope && ev.envelope.status !== "processing" ? idx : acc),
          -1
        );
        selectEvent(entry.id, terminalIdx >= 0 ? terminalIdx : entry.events.length - 1);
      });
      li.append(time, reqId, scenario, modeBadge, badge, viewBtn);
      list.appendChild(li);
    }
  }

  /* =====================================================================
   * Unified request service flow.
   * ===================================================================== */

  function beginSending(text) {
  state.sending = true;
  const sendButton = document.getElementById("btn-send");
  const indicator = document.getElementById("sending-indicator");
  const textEl = document.getElementById("sending-text");
  if (sendButton) sendButton.disabled = true;
  if (textEl) textEl.textContent = text || "处理中…";
  if (indicator) indicator.hidden = false;
}

function endSending() {
  state.sending = false;
  const sendButton = document.getElementById("btn-send");
  const indicator = document.getElementById("sending-indicator");
  if (sendButton) sendButton.disabled = false;
  if (indicator) indicator.hidden = true;
}

function defaultClientId() {
    return "dc-" + newReqId().slice(0, 8);
  }

  let statusTimer = null;

  function setConnStatus(status, message) {
    const clsMap = {
      disconnected: "badge-ghost",
      connecting: "badge-info",
      connected: "badge-success",
      error: "badge-error",
    };
    const labelMap = {
      disconnected: "未连接",
      connecting: "连接中",
      connected: "已连接",
      error: "连接错误",
    };
    const label = labelMap[status] || "未连接";
    const cls = "badge " + (clsMap[status] || "badge-ghost");
    for (const id of ["conn-badge", "conn-status"]) {
      const el = document.getElementById(id);
      if (el) {
        el.textContent = label;
        el.className = cls;
      }
    }
    const msgEl = document.getElementById("conn-message");
    if (msgEl) {
      msgEl.textContent = message || "";
      msgEl.className = "status-message" + (status === "error" ? " is-error" : status === "connected" ? " is-success" : "");
    }
  }

  function findEntryByReqId(reqId) {
    return state.history.find((entry) => entry.reqId === reqId) || null;
  }

  function ensureServiceEntry(detail) {
    let entry = state.history.find((item) => item.id === detail.entryId);
    if (entry) {
      return entry;
    }
    const request = detail.request || {};
    entry = {
      id: detail.entryId,
      reqId: detail.reqId,
      deviceId: detail.deviceId,
      scenarioId: detail.mode === "mock" ? state.scenarioId : null,
      scenarioLabel: detail.mode === "mock" ? scenarioById(state.scenarioId).label : "真实 MQTT",
      mode: detail.mode || state.mode,
      source: detail.source || "debug",
      receivedTs: Date.now(),
      status: "pending",
      events: [],
      request,
      requestTopic: detail.requestTopic,
      responseTopic: detail.responseTopic,
    };
    state.history.unshift(entry);
    if (state.history.length > HISTORY_LIMIT) {
      state.history.length = HISTORY_LIMIT;
    }
    state.activeEntryId = entry.id;
    state.activeEventIndex = -1;
    renderHistory();
    return entry;
  }

  function handleServiceEvent(detail) {
    if (!detail || !detail.kind) {
      return;
    }
    if (detail.kind === "connection") {
      state.mqtt.status = detail.status;
      setConnStatus(detail.status, detail.message);
      if (detail.status === "connected") {
        showStatus("MQTT 已连接", "success");
      } else if (detail.status === "error") {
        showStatus("MQTT 连接错误：" + (detail.message || "未知错误"), "error");
      }
      return;
    }
    if (detail.kind === "mode") {
      state.mode = detail.mode;
      updateModeUi();
      return;
    }
    if (detail.kind === "request") {
      ensureServiceEntry(detail);
      beginSending(detail.mode === "mock" ? "模拟中，请稍候…" : "已发布，等待桥接响应…");
      renderTimeline();
      return;
    }
    if (detail.kind === "note") {
      const entry = ensureServiceEntry(detail);
      pushNote(entry, detail.message);
      renderTimeline();
      return;
    }
    if (detail.kind === "response") {
      const entry = ensureServiceEntry(detail);
      pushEvent(entry, detail.envelope, detail.topic, detail.responseKind || "terminal");
      if (detail.envelope.status === "processing") {
        entry.status = "pending";
        showStatus("已收到 processing，等待终态…", "");
      } else {
        entry.status = detail.envelope.status;
        renderHistory();
        showStatus("已收到终态：" + detail.envelope.status + (detail.envelope.error_code ? " / " + detail.envelope.error_code : ""), detail.envelope.status === "success" ? "success" : "error");
        endSending();
      }
      selectEvent(entry.id, entry.events.length - 1);
      return;
    }
    if (detail.kind === "failure") {
      const entry = detail.entryId ? state.history.find((item) => item.id === detail.entryId) : findEntryByReqId(detail.reqId);
      if (entry) {
        entry.status = "error";
        pushNote(entry, detail.message || detail.errorCode || "请求失败");
        renderHistory();
        renderTimeline();
      }
      endSending();
      showStatus("发送失败：" + (detail.message || detail.errorCode || "未知错误"), "error");
      return;
    }
    if (detail.kind === "unmatched") {
      showStatus(detail.message + (detail.reqId ? "：" + detail.reqId : ""), "error");
    }
  }

  async function handleSend() {
    if (state.sending) {
      return;
    }
    const collected = collectRequest();
    if (!collected.ok) {
      showStatus("发送失败：" + collected.errors[0], "error");
      return;
    }
    const service = window.__requestService;
    if (!service) {
      showStatus("发送失败：统一请求服务未初始化", "error");
      return;
    }
    service.setMode(state.mode);
    service.send({
      source: "debug",
      request: collected.request,
      mockScenario: state.scenarioId,
      delayMs: state.delayMs,
    });
  }

  function sendExternalRequest(request, options) {
    const service = window.__requestService;
    if (!service) {
      return null;
    }
    const opts = options || {};
    service.setMode(opts.mode || state.mode);
    return service.send({
      source: opts.source || "board",
      request,
      mockScenario: opts.mockScenario || state.scenarioId,
      delayMs: opts.delayMs !== undefined ? opts.delayMs : state.delayMs,
    });
  }

  /* =====================================================================
   * Import / export.
   * ===================================================================== */

  function handleExport() {
    const collected = collectRequest();
    if (!collected.ok) {
      showStatus("导出失败：请先修正请求编辑错误", "error");
      return;
    }
    const body = collected.request.body;
    const hash = sha256Sync(new TextEncoder().encode(pyDumps(body)));
    const shown = {};
    Object.assign(shown, body, { payload_hash: hash });
    const safeId = String(collected.request.req_id).replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 16) || "request";
    const blob = new Blob([JSON.stringify(shown, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "velaguard-request-" + safeId + ".json";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showStatus("已导出请求 JSON", "success");
  }

  function applyImportedContext(context) {
    for (const name of CONTEXT_SECTIONS) {
      setSectionMode(name, "json", true);
      const textarea = contextSectionEl(name).querySelector("textarea");
      if (context && context[name] !== undefined && context[name] !== null) {
        textarea.value = JSON.stringify(context[name], null, 2);
      } else {
        textarea.value = "";
      }
    }
  }

  function handleImport(file) {
    if (!file) {
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      let data;
      try {
        data = JSON.parse(String(reader.result));
      } catch (err) {
        showStatus("导入失败：文件不是合法 JSON", "error");
        return;
      }
      if (!data || typeof data !== "object" || Array.isArray(data)) {
        showStatus("导入失败：请求必须是 JSON 对象", "error");
        return;
      }
      document.getElementById("f-req-id").value =
        typeof data.req_id === "string" ? data.req_id : newReqId();
      document.getElementById("f-device-id").value =
        typeof data.device_id === "string" ? data.device_id : "dev01";
      document.getElementById("f-created-ts").value =
        data.created_ts_ms !== undefined ? String(data.created_ts_ms) : String(Date.now());
      applyImportedContext(typeof data.context === "object" && data.context ? data.context : null);
      if (data.type && data.type !== REQUEST_TYPE) {
        showStatus("已导入；注意：type 非 diagnosis，本工具仅模拟 diagnosis", "success");
      } else {
        showStatus("已导入请求（payload_hash 将按当前 body 重新计算）", "success");
      }
      updateHashAndPreview();
    };
    reader.onerror = () => showStatus("导入失败：无法读取文件", "error");
    reader.readAsText(file);
  }

  /* =====================================================================
   * Init and wiring.
   * ===================================================================== */

  const state = {
    scenarioId: "mimo_success",
    delayMs: 800,
    history: [],
    activeEntryId: null,
    activeEventIndex: -1,
    sending: false,
    hashVersion: 0,
    resultView: "tree",
    entrySeq: 1,
    mode: "real",
    mqtt: {
      client: null,
      status: "disconnected",
      pending: new Map(),
    },
  };

  function updateModeUi() {
    const isReal = state.mode === "real";
    const connPanel = document.getElementById("conn-panel");
    const mockControls = document.getElementById("mock-controls");
    const modeBadge = document.getElementById("mode-badge");
    const modeHint = document.getElementById("mode-hint");
    if (connPanel) connPanel.hidden = !isReal;
    if (mockControls) mockControls.hidden = isReal;
    if (modeBadge) {
      modeBadge.textContent = isReal ? "真实模式" : "Mock 模式";
      modeBadge.className = "badge " + (isReal ? "badge-info" : "badge-ghost");
    }
    if (modeHint) {
      modeHint.textContent = isReal
        ? "真实模式默认连接 dev broker（WebSocket 9001），由真实 AI Bridge 处理；连接失败时可一键切换 Mock 继续演示。"
        : "Mock 模式完全离线，不依赖网络与 broker；内置六个场景，仅用于演示与契约核对。";
    }
    for (const btn of document.querySelectorAll("[data-mode-select]")) {
      btn.classList.toggle("is-active", btn.dataset.modeSelect === state.mode);
    }
  }

  function switchMode(mode) {
    if (mode !== "real" && mode !== "mock") {
      return;
    }
    state.mode = mode;
    updateModeUi();
    if (window.__requestService) {
      window.__requestService.setMode(mode);
    }
  }

  function buildScenarioOptions() {
    const select = document.getElementById("f-scenario");
    for (const scenario of SCENARIOS) {
      const option = document.createElement("option");
      option.value = scenario.id;
      option.textContent = scenario.label;
      select.appendChild(option);
    }
    select.value = state.scenarioId;
    document.getElementById("scenario-desc").textContent = scenarioById(state.scenarioId).desc;
  }

  function scheduleHashUpdate() {
    clearTimeout(state.hashTimer);
    state.hashTimer = setTimeout(() => {
      updateHashAndPreview();
    }, 120);
  }

  function init() {
    buildScenarioOptions();
    applyPreset("temp");
    document.getElementById("f-req-id").value = newReqId();
    document.getElementById("f-created-ts").value = String(Date.now());
    document.getElementById("f-client-id").value = defaultClientId();
    document.getElementById("f-delay").value = String(scenarioById(state.scenarioId).defaultDelayMs);
    state.delayMs = Number(document.getElementById("f-delay").value);

    for (const btn of document.querySelectorAll("[data-mode-select]")) {
      btn.addEventListener("click", () => switchMode(btn.dataset.modeSelect));
    }
    document.addEventListener("request-service-event", (event) => handleServiceEvent(event.detail));
    document.getElementById("btn-connect").addEventListener("click", () => {
      const service = window.__requestService;
      if (service) {
        service.connect({
          url: document.getElementById("f-broker-url").value.trim(),
          clientId: document.getElementById("f-client-id").value.trim(),
          username: document.getElementById("f-mqtt-user").value.trim(),
          password: document.getElementById("f-mqtt-pass").value,
        });
      }
    });
    document.getElementById("btn-disconnect").addEventListener("click", () => {
      if (window.__requestService) window.__requestService.disconnect("未连接");
    });

    document.getElementById("btn-regen-req-id").addEventListener("click", () => {
      document.getElementById("f-req-id").value = newReqId();
      scheduleHashUpdate();
    });
    document.getElementById("btn-now-ts").addEventListener("click", () => {
      document.getElementById("f-created-ts").value = String(Date.now());
      scheduleHashUpdate();
    });
    document.getElementById("btn-refresh-hash").addEventListener("click", () => {
      updateHashAndPreview();
      showStatus("hash 已刷新", "success");
    });
    document.getElementById("btn-copy-hash").addEventListener("click", async () => {
      const hash = document.getElementById("f-payload-hash").value;
      if (!hash || hash.startsWith("（")) {
        showStatus("hash 尚未计算完成", "error");
        return;
      }
      const ok = await copyText(hash);
      showStatus(ok ? "hash 已复制" : "复制失败，请手动选择复制", ok ? "success" : "error");
    });

    document.getElementById("f-scenario").addEventListener("change", () => {
      state.scenarioId = document.getElementById("f-scenario").value;
      const scenario = scenarioById(state.scenarioId);
      document.getElementById("scenario-desc").textContent = scenario.desc;
      document.getElementById("f-delay").value = String(scenario.defaultDelayMs);
      state.delayMs = scenario.defaultDelayMs;
    });
    document.getElementById("f-delay").addEventListener("input", () => {
      const value = Number(document.getElementById("f-delay").value);
      state.delayMs = Number.isFinite(value) ? Math.min(60000, Math.max(0, value)) : 0;
    });
    document.getElementById("btn-send").addEventListener("click", handleSend);
    document.getElementById("btn-export").addEventListener("click", handleExport);
    document.getElementById("btn-copy-response").addEventListener("click", async () => {
      const entry = state.history.find((e) => e.id === state.activeEntryId);
      const event = entry ? entry.events[state.activeEventIndex] : null;
      if (!event || !event.envelope) {
        showStatus("当前没有可复制的响应", "error");
        return;
      }
      const ok = await copyText(JSON.stringify(event.envelope, null, 2));
      showStatus(ok ? "响应 JSON 已复制" : "复制失败", ok ? "success" : "error");
    });

    document.getElementById("btn-clear-history").addEventListener("click", () => {
      state.history = [];
      state.activeEntryId = null;
      state.activeEventIndex = -1;
      renderHistory();
      resetViewer();
      showStatus("历史已清空", "success");
    });

    const importInput = document.getElementById("f-import");
    importInput.addEventListener("change", () => {
      handleImport(importInput.files && importInput.files[0]);
      importInput.value = "";
    });

    for (const btn of document.querySelectorAll("[data-preset]")) {
      btn.addEventListener("click", () => {
        const preset = PRESETS[btn.dataset.preset];
        applyPreset(btn.dataset.preset);
        scheduleHashUpdate();
        showStatus("已载入预设：" + preset.label, "success");
      });
    }

    for (const sectionEl of document.querySelectorAll(".context-section")) {
      const name = sectionEl.dataset.section;
      for (const btn of sectionEl.querySelectorAll(".mode-btn")) {
        btn.addEventListener("click", () => {
          setSectionMode(name, btn.dataset.mode);
          scheduleHashUpdate();
        });
      }
      sectionEl.addEventListener("click", (ev) => {
        const addBtn = ev.target.closest("[data-add-row]");
        if (addBtn) {
          addRow(name);
          scheduleHashUpdate();
          return;
        }
        const removeBtn = ev.target.closest(".btn-remove");
        if (removeBtn) {
          removeBtn.closest(".row-item").remove();
          scheduleHashUpdate();
        }
      });
    }

    for (const btn of document.querySelectorAll(".result-head .mode-btn")) {
      btn.addEventListener("click", () => renderResult(btn.dataset.view));
    }

    for (const textarea of document.querySelectorAll(".json-editor")) {
      textarea.addEventListener("input", () => {
        const sectionEl = textarea.closest(".context-section");
        const name = sectionEl.dataset.section;
        const raw = textarea.value.trim();
        if (!raw) {
          clearSectionError(name);
        } else {
          try {
            JSON.parse(raw);
            clearSectionError(name);
          } catch (err) {
            showSectionError(name, "JSON 解析失败：" + err.message);
          }
        }
        scheduleHashUpdate();
      });
    }

    function onEditorMutation(ev) {
      const target = ev.target;
      if (!target || !target.closest || !target.closest("#editor-panel")) {
        return;
      }
      if (target.id === "f-scenario" || target.id === "f-delay") {
        return;
      }
      const valuesInput = target.closest('[data-key="values"]');
      if (valuesInput) {
        const sectionEl = target.closest(".context-section");
        const errEl = sectionEl.querySelector(".field-error");
        const raw = valuesInput.value.trim();
        if (!raw) {
          errEl.hidden = true;
        } else {
          try {
            const parsed = JSON.parse(raw);
            if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
              errEl.textContent = "values 必须是 JSON 对象";
              errEl.hidden = false;
            } else {
              errEl.hidden = true;
            }
          } catch (err) {
            errEl.textContent = "values JSON 解析失败：" + err.message;
            errEl.hidden = false;
          }
        }
      }
      scheduleHashUpdate();
    }
    document.addEventListener("input", onEditorMutation);
    document.addEventListener("change", onEditorMutation);

    renderHistory();
    resetViewer();
    switchMode("real");
    scheduleHashUpdate();
  }

  window.__requestConsole = {
    sendRequest: sendExternalRequest,
    switchMode,
    getState: () => ({ mode: state.mode, historyCount: state.history.length, activeEntryId: state.activeEntryId }),
  };

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  }

})(window);
