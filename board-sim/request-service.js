"use strict";

/*
 * Unified diagnosis request service.
 * Owns the only MQTT client, pending request map, Mock timing and the
 * request-service-event bridge consumed by the board UI and debug panel.
 */
(function initRequestService(root) {
  const core = root.BoardCore;
  const debugCore = root.DebugCore;
  const MQTT_DEFAULT_URL = core.MQTT_DEFAULT_URL || "ws://107.174.123.74:9001";
  const MQTT_CONNECT_TIMEOUT_MS = core.MQTT_CONNECT_TIMEOUT_MS || 8000;
  const REAL_RESPONSE_TIMEOUT_MS = core.REAL_RESPONSE_TIMEOUT_MS || 60000;

  const state = {
    mode: "real",
    client: null,
    status: "disconnected",
    url: MQTT_DEFAULT_URL,
    pending: new Map(),
    seq: 1,
  };
  const listeners = new Set();

  function defaultClientId() {
    if (core && typeof core.newReqId === "function") {
      return "vg-unified-" + core.newReqId().slice(0, 8);
    }
    return "vg-unified-" + Math.random().toString(16).slice(2, 10);
  }

  function emit(detail) {
    const event = Object.assign({ timestamp: Date.now() }, detail);
    for (const listener of listeners) {
      try {
        listener(event);
      } catch (err) {
        // Observers must not break the transport.
      }
    }
    const target = root.document || root;
    if (target && typeof target.dispatchEvent === "function" && typeof root.CustomEvent === "function") {
      target.dispatchEvent(new root.CustomEvent("request-service-event", { detail: event }));
    }
  }

  function on(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  function setStatus(status, message) {
    state.status = status;
    emit({ kind: "connection", status, message: message || "", url: state.url });
  }

  function normalizeRequest(input) {
    const request = input && input.request ? input.request : input;
    if (!request) {
      throw new Error("请求为空");
    }
    const body = request.body || request;
    const full = Object.assign({}, request.full || body);
    if (!full.payload_hash && request.payload_hash) {
      full.payload_hash = request.payload_hash;
    }
    const reqId = String(full.req_id || request.req_id || "");
    const deviceId = String(full.device_id || request.device_id || "");
    if (!reqId || !deviceId) {
      throw new Error("请求缺少 req_id 或 device_id");
    }
    return {
      body,
      full,
      payload_hash: String(request.payload_hash || full.payload_hash || ""),
      payload: request.payload || core.pyDumps(full),
      req_id: reqId,
      device_id: deviceId,
    };
  }

  function topicFor(entry) {
    return {
      requestTopic: "vg/" + entry.deviceId + "/ai/request",
      responseTopic: "vg/" + entry.deviceId + "/ai/response/" + entry.reqId,
    };
  }

  function emitRequest(entry) {
    emit({
      kind: "request",
      entryId: entry.id,
      source: entry.source,
      mode: entry.mode,
      reqId: entry.reqId,
      deviceId: entry.deviceId,
      requestTopic: entry.requestTopic,
      responseTopic: entry.responseTopic,
      request: entry.request.full,
      payloadHash: entry.request.payload_hash,
    });
  }

  function emitNote(entry, message) {
    emit({ kind: "note", entryId: entry.id, source: entry.source, reqId: entry.reqId, message });
  }

  function emitResponse(entry, envelope, topic, responseKind) {
    const normalized = core.normalizeEnvelope(envelope);
    emit({
      kind: "response",
      entryId: entry.id,
      source: entry.source,
      mode: entry.mode,
      reqId: entry.reqId,
      deviceId: entry.deviceId,
      topic,
      responseKind: responseKind || (normalized.status === "processing" ? "processing" : "terminal"),
      envelope: normalized,
    });
  }

  function emitTraffic(entry, direction, topic, payload, status, errorCode) {
    emit({
      kind: "traffic",
      source: entry.source,
      mode: entry.mode,
      direction,
      topic,
      payload,
      reqId: entry.reqId,
      status: status || null,
      errorCode: errorCode || null,
    });
  }

  function failEntry(entry, errorCode, message, status) {
    if (!entry || entry.finished) {
      return;
    }
    entry.finished = true;
    if (entry.timer) {
      clearTimeout(entry.timer);
      entry.timer = null;
    }
    state.pending.delete(entry.reqId);
    const envelope = core.normalizeEnvelope({
      req_id: entry.reqId,
      device_id: entry.deviceId,
      type: core.REQUEST_TYPE || "diagnosis",
      status: status || "error",
      error_code: errorCode,
      error_message: message,
      received_ts_ms: Date.now(),
      bridge_ts_ms: Date.now(),
    });
    emitTraffic(entry, "in", entry.responseTopic, envelope, envelope.status, errorCode);
    emitResponse(entry, envelope, entry.responseTopic, "terminal");
    emit({
      kind: "failure",
      entryId: entry.id,
      source: entry.source,
      reqId: entry.reqId,
      deviceId: entry.deviceId,
      errorCode,
      message,
    });
    unsubscribe(entry);
  }

  function unsubscribe(entry) {
    if (!state.client || !entry || !entry.responseTopic) {
      return;
    }
    try {
      state.client.unsubscribe(entry.responseTopic);
    } catch (err) {
      // Best effort cleanup.
    }
  }

  function finishEntry(entry) {
    if (entry.timer) {
      clearTimeout(entry.timer);
      entry.timer = null;
    }
    state.pending.delete(entry.reqId);
    entry.finished = true;
    unsubscribe(entry);
  }

  function handleIncoming(topic, payload) {
    let text;
    try {
      text = new TextDecoder().decode(payload);
    } catch (err) {
      text = String(payload);
    }
    let data;
    try {
      data = JSON.parse(text);
    } catch (err) {
      const match = topic.match(/\/ai\/response\/([^/]+)$/);
      const reqId = match ? match[1] : null;
      const entry = reqId ? state.pending.get(reqId) : null;
      if (entry) {
        emitNote(entry, "收到非法 JSON 响应：" + err.message);
        failEntry(entry, "provider_error", "收到无法解析的响应");
      } else {
        emit({ kind: "unmatched", topic, message: "收到无法解析的响应" });
      }
      return;
    }
    const reqId = data && data.req_id !== undefined ? String(data.req_id) : null;
    const entry = reqId ? state.pending.get(reqId) : null;
    if (!entry) {
      emit({ kind: "unmatched", topic, message: "收到未知 req_id 的响应", reqId });
      return;
    }
    const envelope = core.normalizeEnvelope(data);
    emitTraffic(entry, "in", topic, envelope, envelope.status, envelope.error_code);
    emitResponse(entry, envelope, topic);
    if (envelope.status === "processing") {
      emitNote(entry, "已收到 processing，等待终态…");
      return;
    }
    if (envelope.status === "success" || envelope.status === "error") {
      finishEntry(entry);
    }
  }

  function connect(config) {
    const options = config || {};
    const url = String(options.url || MQTT_DEFAULT_URL).trim();
    const clientId = String(options.clientId || defaultClientId()).trim();
    const username = String(options.username || "").trim();
    const password = options.password || "";
    if (typeof root.mqtt === "undefined" || !root.mqtt || typeof root.mqtt.connect !== "function") {
      setStatus("error", "mqtt.js 未加载");
      return false;
    }
    if (!/^wss?:\/\/[^/]+/.test(url)) {
      setStatus("error", "Broker URL 必须是 ws:// 或 wss:// 地址");
      return false;
    }
    disconnect("重新连接");
    state.url = url;
    setStatus("connecting", "正在连接 " + url);
    let client;
    try {
      client = root.mqtt.connect(url, {
        clientId,
        username: username || undefined,
        password: password || undefined,
        clean: true,
        protocolVersion: 4,
        reconnectPeriod: 0,
        connectTimeout: MQTT_CONNECT_TIMEOUT_MS,
      });
    } catch (err) {
      setStatus("error", "连接失败：" + (err.message || String(err)));
      return false;
    }
    state.client = client;
    client.on("connect", () => setStatus("connected", "已连接 " + url));
    client.on("message", handleIncoming);
    client.on("error", (err) => {
      const message = err && err.message ? err.message : String(err);
      setStatus("error", "连接错误：" + message);
      failPending("连接错误，等待中的请求已取消：" + message, "interrupted");
    });
    client.on("offline", () => {
      setStatus("disconnected", "已离线，请重试连接");
      failPending("已离线，等待中的请求已取消；请重新连接后重试", "interrupted");
    });
    client.on("close", () => {
      if (state.client === client) {
        state.client = null;
        setStatus("disconnected", "连接已断开");
        failPending("连接已断开，等待中的请求已取消；请重新连接后重试", "interrupted");
      }
    });
    return true;
  }

  function disconnect(reason) {
    const client = state.client;
    state.client = null;
    failPending(reason || "连接已断开，等待中的请求已取消", "interrupted");
    if (client) {
      try {
        client.end(true);
      } catch (err) {
        // Best effort.
      }
    }
    if (state.status !== "disconnected") {
      setStatus("disconnected", reason || "未连接");
    }
  }

  function failPending(message, errorCode) {
    for (const entry of Array.from(state.pending.values())) {
      failEntry(entry, errorCode || "interrupted", message);
    }
    state.pending.clear();
  }

  async function runMock(entry, scenarioId, delayMs) {
    const scenario = debugCore.scenarioById(scenarioId);
    const receivedTs = Date.now();
    emitTraffic(entry, "out", "mock://" + entry.deviceId + "/ai/request", entry.request.full, "request");
    if (scenario.sendsProcessing) {
      const processing = debugCore.buildEnvelope({
        req_id: entry.reqId,
        device_id: entry.deviceId,
        type: core.REQUEST_TYPE || "diagnosis",
        status: "processing",
        received_ts_ms: receivedTs,
        bridge_ts_ms: Date.now(),
      });
      emitTraffic(entry, "in", entry.responseTopic, processing, "processing");
      emitResponse(entry, processing, entry.responseTopic, "processing");
    } else {
      emitNote(entry, "解析/幂等阶段直接拒绝，真实桥接不会发布 processing");
    }
    await new Promise((resolve) => setTimeout(resolve, Math.max(0, Number(delayMs) || 0)));
    if (entry.finished) {
      return;
    }
    const terminal = debugCore.buildTerminalEnvelope(scenario.id, entry.request.full, receivedTs);
    emitTraffic(entry, "in", entry.responseTopic, terminal, terminal.status, terminal.error_code);
    emitResponse(entry, terminal, entry.responseTopic, "terminal");
    finishEntry(entry);
  }

  function send(input) {
    let request;
    try {
      request = normalizeRequest(input);
    } catch (err) {
      emit({ kind: "failure", source: input && input.source, message: err.message, errorCode: "internal_error" });
      return null;
    }
    const source = input && input.source ? input.source : "debug";
    const entry = {
      id: "r" + state.seq++,
      source,
      mode: state.mode,
      request,
      reqId: request.req_id,
      deviceId: request.device_id,
      finished: false,
      timer: null,
    };
    Object.assign(entry, topicFor(entry));
    const previous = state.pending.get(entry.reqId);
    if (previous) {
      failEntry(previous, "superseded", "同一 req_id 的后续请求已发送，本条等待状态被取代");
    }
    state.pending.set(entry.reqId, entry);
    emitRequest(entry);
    emitNote(entry, "请求 topic：" + entry.requestTopic);
    emitNote(entry, "响应订阅：" + entry.responseTopic);
    if (entry.mode === "mock") {
      runMock(entry, input && input.mockScenario, input && input.delayMs);
      return entry.id;
    }
    if (!state.client || state.status !== "connected") {
      failEntry(entry, "interrupted", "连接已断开，诊断已取消");
      return entry.id;
    }
    emitTraffic(entry, "out", entry.requestTopic, entry.request.full, "request");
    entry.timer = setTimeout(() => failEntry(entry, "timeout", "等待响应超时（60 s），请重试或切 Mock"), REAL_RESPONSE_TIMEOUT_MS);
    state.client.subscribe(entry.responseTopic, { qos: 1 }, (subErr) => {
      if (subErr) {
        failEntry(entry, "send_failed", "订阅失败：" + (subErr.message || String(subErr)));
        return;
      }
      emitNote(entry, "已订阅响应 topic，发布请求（QoS 1）…");
      state.client.publish(entry.requestTopic, entry.request.payload, { qos: 1, retain: false }, (pubErr) => {
        if (pubErr) {
          failEntry(entry, "send_failed", "发布失败：" + (pubErr.message || String(pubErr)));
          return;
        }
        emitNote(entry, "已发布：" + entry.requestTopic);
      });
    });
    return entry.id;
  }

  function recordMock(input) {
    let request;
    try {
      request = normalizeRequest(input);
    } catch (err) {
      emit({ kind: "failure", source: input && input.source, message: err.message, errorCode: "internal_error" });
      return null;
    }
    const entry = {
      id: "r" + state.seq++,
      source: input && input.source ? input.source : "board",
      mode: "mock",
      request,
      reqId: request.req_id,
      deviceId: request.device_id,
      finished: true,
      timer: null,
    };
    Object.assign(entry, topicFor(entry));
    emitRequest(entry);
    emitTraffic(entry, "out", "mock://" + entry.deviceId + "/ai/request", entry.request.full, "request");
    if (input && input.processing) {
      emitTraffic(entry, "in", entry.responseTopic, input.processing, "processing");
      emitResponse(entry, input.processing, entry.responseTopic, "processing");
    }
    if (input && input.terminal) {
      emitTraffic(entry, "in", entry.responseTopic, input.terminal, input.terminal.status, input.terminal.error_code);
      emitResponse(entry, input.terminal, entry.responseTopic, "terminal");
    }
    return entry.id;
  }

  function setMode(mode) {
    const next = mode === "mock" ? "mock" : "real";
    if (next !== state.mode) {
      failPending("模式已切换，等待中的诊断请求已取消", "interrupted");
    }
    state.mode = next;
    emit({ kind: "mode", mode: next });
  }

  function waitForConnection(timeoutMs) {
    if (state.status === "connected") return Promise.resolve(true);
    if (state.status === "error" || (state.status === "disconnected" && !state.client)) return Promise.resolve(false);
    const timeout = Math.max(100, Number(timeoutMs) || MQTT_CONNECT_TIMEOUT_MS + 1000);
    return new Promise((resolve) => {
      let timer = setTimeout(() => { off(); resolve(false); }, timeout);
      const off = on((event) => {
        if (event.kind === "connection" && event.status === "connected") {
          clearTimeout(timer);
          off();
          resolve(true);
        } else if (event.kind === "connection" && event.status === "error") {
          clearTimeout(timer);
          off();
          resolve(false);
        }
      });
    });
  }

  const api = {
    connect,
    waitForConnection,
    disconnect,
    send,
    recordMock,
    setMode,
    on,
    getState: () => ({ mode: state.mode, status: state.status, pendingCount: state.pending.size, hasClient: !!state.client, url: state.url }),
  };
  root.__requestService = api;
})(typeof window !== "undefined" ? window : globalThis);
