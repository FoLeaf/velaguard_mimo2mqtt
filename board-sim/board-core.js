"use strict";

/* =====================================================================
 * VelaGuard board HMI simulator - pure model and contract layer.
 *
 * This file is dependency-free and dual-use:
 *   - Browser: loaded with <script src="board-core.js">, exposes window.BoardCore
 *   - Node: require("./board-core.js") for contract/unit checks
 *
 * It mirrors the board-side model semantics from
 * D:/Study/Embeded/Velaguard/GUI/main/ui/model/vg_model.c (scenario,
 * sensors, alarms, net, diagnosis, logs, home filter, mock diagnosis) and
 * the AI Bridge request/response contract from .trellis/spec/backend/
 * mqtt-ai-bridge-contracts.md.
 *
 * Canonical JSON / SHA-256 parity: the helpers below are copied from
 * debug-console/app.js (same repository) so board-sim/ stays fully
 * independent while reproducing ai_bridge.cli.synthetic_publisher
 * byte-for-byte. Keep the two copies in sync; tests/contract/
 * test_debug_console_hash_parity.py checks both against Python.
 * ===================================================================== */

/* =====================================================================
 * Python-compatible canonical JSON and SHA-256 helpers.
 * (Copied verbatim from debug-console/app.js; see header note above.)
 *
 * payload_hash must match ai_bridge.cli.synthetic_publisher.build_request:
 *   canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
 *   payload_hash = sha256(canonical.encode("utf-8")).hexdigest()
 *
 * Python's default json.dumps uses ensure_ascii=True, so every character
 * with code point >= 0x7f (including DEL and non-ASCII) is escaped as
 * \uXXXX per UTF-16 code unit, and keys are sorted by code point.
 * ===================================================================== */

function compareCodePoints(a, b) {
  const ca = Array.from(a);
  const cb = Array.from(b);
  const n = Math.min(ca.length, cb.length);
  for (let i = 0; i < n; i++) {
    const pa = ca[i].codePointAt(0);
    const pb = cb[i].codePointAt(0);
    if (pa !== pb) {
      return pa < pb ? -1 : 1;
    }
  }
  return ca.length - cb.length;
}

function pyEscapeString(s) {
  let out = '"';
  for (let i = 0; i < s.length; i++) {
    const ch = s.charAt(i);
    const code = s.charCodeAt(i);
    switch (ch) {
      case '"':
        out += '\\"';
        break;
      case "\\":
        out += "\\\\";
        break;
      case "\b":
        out += "\\b";
        break;
      case "\t":
        out += "\\t";
        break;
      case "\n":
        out += "\\n";
        break;
      case "\f":
        out += "\\f";
        break;
      case "\r":
        out += "\\r";
        break;
      default:
        if (code < 0x20 || code >= 0x7f) {
          out += "\\u" + code.toString(16).padStart(4, "0");
        } else {
          out += ch;
        }
    }
  }
  return out + '"';
}

function pyNormalizeExponent(s) {
  const m = s.match(/^(-?)([\d.]+)e([+-])(\d+)$/);
  if (!m) {
    return s;
  }
  const exp = Number(m[4]);
  const padded = exp < 10 ? "0" + exp : String(exp);
  return m[1] + m[2] + "e" + m[3] + padded;
}

function pyFloatToString(v) {
  if (typeof v === "bigint") {
    return v.toString();
  }
  if (!Number.isFinite(v)) {
    if (Number.isNaN(v)) {
      return "NaN";
    }
    return v > 0 ? "Infinity" : "-Infinity";
  }
  if (Object.is(v, -0)) {
    return "-0.0";
  }
  const abs = Math.abs(v);
  if (abs >= 1e16 || (abs > 0 && abs < 1e-4)) {
    return pyNormalizeExponent(v.toExponential());
  }
  if (Number.isInteger(v)) {
    return v.toFixed(1);
  }
  return String(v);
}

function pyDumps(value) {
  if (value === null) {
    return "null";
  }
  if (value instanceof PyInt) {
    return String(value.value);
  }
  const t = typeof value;
  if (t === "boolean") {
    return value ? "true" : "false";
  }
  if (t === "number") {
    return pyFloatToString(value);
  }
  if (t === "bigint") {
    return value.toString();
  }
  if (t === "string") {
    return pyEscapeString(value);
  }
  if (Array.isArray(value)) {
    const parts = [];
    for (const item of value) {
      parts.push(pyDumps(item));
    }
    return "[" + parts.join(",") + "]";
  }
  if (t === "object") {
    const keys = Object.keys(value).sort(compareCodePoints);
    const parts = [];
    for (const key of keys) {
      parts.push(pyEscapeString(key) + ":" + pyDumps(value[key]));
    }
    return "{" + parts.join(",") + "}";
  }
  throw new Error("pyDumps: unsupported value type: " + t);
}

/**
 * A JSON integer value. JSON.parse collapses 1 and 1.0 into the same JS
 * number, but Python's json.dumps serializes them differently (1 vs 1.0).
 * This wrapper preserves the int/float distinction while hashing.
 */
class PyInt {
  constructor(value) {
    this.value = value; // number (safe int) or bigint
  }

  toJSON() {
    // Only used for display; BigInt is approximated by Number in previews.
    return typeof this.value === "bigint" ? Number(this.value) : this.value;
  }
}

/**
 * JSON object that preserves the textual key order, including integer-like
 * keys ("2", "10", "1") that plain JS objects would reorder numerically.
 * Python's json.dumps(sort_keys=True) sorts every key by code point, so the
 * original order must survive parsing and be handed to the sorter intact.
 */
function makePyObject() {
  const entries = [];
  const target = Object.create(null);
  return new Proxy(target, {
    ownKeys() {
      return entries.slice();
    },
    getOwnPropertyDescriptor(t, key) {
      if (!(key in t)) {
        return undefined;
      }
      return {
        value: t[key],
        writable: true,
        enumerable: true,
        configurable: true,
      };
    },
    set(t, key, value) {
      if (key in t) {
        t[key] = value;
      } else {
        t[key] = value;
        entries.push(key);
      }
      return true;
    },
    deleteProperty(t, key) {
      if (key in t) {
        delete t[key];
        const idx = entries.indexOf(key);
        if (idx >= 0) {
          entries.splice(idx, 1);
        }
      }
      return true;
    },
  });
}

/**
 * A JSON parser that preserves the int/float distinction of number tokens.
 * Integer tokens become PyInt (using BigInt, so huge integers keep exact
 * digits), float tokens stay as JS numbers with Python float semantics.
 * Call JSON.parse first for standard validation; this parser mirrors the
 * same grammar and is only fed already-validated text.
 */
function parseJsonPreservingInts(text) {
  let pos = 0;
  const src = String(text);

  function fail(message) {
    throw new SyntaxError(message + " at position " + pos);
  }

  function skipWs() {
    while (
      pos < src.length &&
      (src[pos] === " " || src[pos] === "\t" || src[pos] === "\n" || src[pos] === "\r")
    ) {
      pos++;
    }
  }

  function expectWord(word) {
    if (src.slice(pos, pos + word.length) !== word) {
      fail("invalid literal");
    }
    pos += word.length;
  }

  function parseString() {
    pos++;
    let out = "";
    while (pos < src.length) {
      const ch = src[pos];
      if (ch === '"') {
        pos++;
        return out;
      }
      if (ch === "\\") {
        pos++;
        if (pos >= src.length) {
          fail("unterminated escape");
        }
        const esc = src[pos];
        if (esc === '"') out += '"';
        else if (esc === "\\") out += "\\";
        else if (esc === "/") out += "/";
        else if (esc === "b") out += "\b";
        else if (esc === "f") out += "\f";
        else if (esc === "n") out += "\n";
        else if (esc === "r") out += "\r";
        else if (esc === "t") out += "\t";
        else if (esc === "u") {
          const hex = src.slice(pos + 1, pos + 5);
          if (!/^[0-9a-fA-F]{4}$/.test(hex)) {
            fail("invalid \\u escape");
          }
          out += String.fromCharCode(parseInt(hex, 16));
          pos += 4;
        } else {
          fail("invalid escape \\" + esc);
        }
        pos++;
      } else {
        out += ch;
        pos++;
      }
    }
    fail("unterminated string");
  }

  function parseNumber() {
    const m = src.slice(pos).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/);
    if (!m) {
      fail("invalid number");
    }
    const token = m[0];
    pos += token.length;
    const isFloat = token.includes(".") || /[eE]/.test(token);
    if (isFloat) {
      return Number(token);
    }
    return new PyInt(BigInt(token));
  }

  function parseArray() {
    pos++;
    const out = [];
    skipWs();
    if (src[pos] === "]") {
      pos++;
      return out;
    }
    for (;;) {
      out.push(parseValue());
      skipWs();
      if (src[pos] === ",") {
        pos++;
        continue;
      }
      if (src[pos] === "]") {
        pos++;
        return out;
      }
      fail("expected , or ]");
    }
  }

  function parseObject() {
    pos++;
    const out = makePyObject();
    skipWs();
    if (src[pos] === "}") {
      pos++;
      return out;
    }
    for (;;) {
      skipWs();
      if (src[pos] !== '"') {
        fail("expected string key");
      }
      const key = parseString();
      skipWs();
      if (src[pos] !== ":") {
        fail("expected :");
      }
      pos++;
      out[key] = parseValue();
      skipWs();
      if (src[pos] === ",") {
        pos++;
        continue;
      }
      if (src[pos] === "}") {
        pos++;
        return out;
      }
      fail("expected , or }");
    }
  }

  function parseValue() {
    skipWs();
    if (pos >= src.length) {
      fail("unexpected end of input");
    }
    const ch = src[pos];
    if (ch === "{") return parseObject();
    if (ch === "[") return parseArray();
    if (ch === '"') return parseString();
    if (ch === "t") {
      expectWord("true");
      return true;
    }
    if (ch === "f") {
      expectWord("false");
      return false;
    }
    if (ch === "n") {
      expectWord("null");
      return null;
    }
    if (ch === "-" || (ch >= "0" && ch <= "9")) {
      return parseNumber();
    }
    fail("unexpected character " + JSON.stringify(ch));
  }

  const result = parseValue();
  skipWs();
  if (pos < src.length) {
    fail("unexpected trailing content");
  }
  return result;
}

const SHA256_K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
  0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
  0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
  0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
  0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
  0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

function rotr(x, n) {
  return (x >>> n) | (x << (32 - n));
}

function sha256Sync(bytes) {
  const bitLenHi = Math.floor((bytes.length * 8) / 0x100000000) >>> 0;
  const bitLenLo = (bytes.length * 8) >>> 0;
  const paddedLen = (((bytes.length + 8) >> 6) + 1) << 6;
  const data = new Uint8Array(paddedLen);
  data.set(bytes);
  data[bytes.length] = 0x80;
  const view = new DataView(data.buffer);
  view.setUint32(paddedLen - 8, bitLenHi);
  view.setUint32(paddedLen - 4, bitLenLo);

  let h0 = 0x6a09e667;
  let h1 = 0xbb67ae85;
  let h2 = 0x3c6ef372;
  let h3 = 0xa54ff53a;
  let h4 = 0x510e527f;
  let h5 = 0x9b05688c;
  let h6 = 0x1f83d9ab;
  let h7 = 0x5be0cd19;
  const w = new Uint32Array(64);

  for (let offset = 0; offset < paddedLen; offset += 64) {
    for (let i = 0; i < 16; i++) {
      w[i] = view.getUint32(offset + i * 4);
    }
    for (let i = 16; i < 64; i++) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }
    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    let f = h5;
    let g = h6;
    let h = h7;
    for (let i = 0; i < 64; i++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const t1 = (h + S1 + ch + SHA256_K[i] + w[i]) >>> 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + t1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (t1 + t2) >>> 0;
    }
    h0 = (h0 + a) >>> 0;
    h1 = (h1 + b) >>> 0;
    h2 = (h2 + c) >>> 0;
    h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0;
    h5 = (h5 + f) >>> 0;
    h6 = (h6 + g) >>> 0;
    h7 = (h7 + h) >>> 0;
  }

  let hex = "";
  for (const h of [h0, h1, h2, h3, h4, h5, h6, h7]) {
    hex += h.toString(16).padStart(8, "0");
  }
  return hex;
}

function hexFromBytes(bytes) {
  let hex = "";
  for (const b of bytes) {
    hex += b.toString(16).padStart(2, "0");
  }
  return hex;
}

async function computePayloadHash(body) {
  const canonical = pyDumps(body);
  const bytes = new TextEncoder().encode(canonical);
  const subtle =
    typeof crypto !== "undefined" && crypto && crypto.subtle ? crypto.subtle : null;
  if (subtle) {
    try {
      const digest = await subtle.digest("SHA-256", bytes);
      return hexFromBytes(new Uint8Array(digest));
    } catch (err) {
      // Fall through to the pure-JS implementation (e.g. non-secure context).
    }
  }
  return sha256Sync(bytes);
}

/* =====================================================================
 * Contract constants.
 * ===================================================================== */

const REQUEST_TYPE = "diagnosis";
const REQUEST_NOTE = "board simulator";
const VG_DISP_W = 480;
const VG_DISP_H = 272;
const VG_STATUS_H = 28;
const VG_CONTENT_H = VG_DISP_H - VG_STATUS_H;
const VG_PAGE_PAD = 6;
const VG_GAP = 4;
const VG_CARD_RADIUS = 4;
const VG_MIN_TOUCH_H = 36;
const VG_MIN_TOUCH_W = 40;
const VG_LIST_ROW_H = VG_MIN_TOUCH_H + 4;

const VG_HISTORY_LEN = 60;
const VG_LOG_MAX = 24;
const VG_SENSOR_MAX = 24;
const VG_DIAG_LOAD_MS = 500;
const HISTORY_CONTEXT_LIMIT = 50;
const RULES_CONTEXT_LIMIT = 20;
const MQTT_DEFAULT_URL = "ws://107.174.123.74:9001";
const MQTT_CONNECT_TIMEOUT_MS = 8000;
const REAL_RESPONSE_TIMEOUT_MS = 60000;

const SCENARIO_IDS = ["normal", "warn", "crit", "offline", "ai_down", "ota"];
const SCENARIOS = [
  { id: "normal", label: "正常" },
  { id: "warn", label: "预警" },
  { id: "crit", label: "严重" },
  { id: "offline", label: "离线" },
  { id: "ai_down", label: "AI不可用" },
  { id: "ota", label: "OTA中" },
];

const HOME_FILTERS = ["all", "alarm", "offline", "ok"];

/* =====================================================================
 * Mock fleet data (mirrors vg_model.c seed_fleet / apply_scenario).
 * ===================================================================== */

const KINDS = [
  { name: "温度", unit: "C", thr_low: 5, thr_warn: 55, thr_crit: 70, base: 34, amp: 0.6, noise: 0.08 },
  { name: "湿度", unit: "%", thr_low: 10, thr_warn: 75, thr_crit: 90, base: 45, amp: 1.0, noise: 0.1 },
  { name: "压力", unit: "kPa", thr_low: 50, thr_warn: 180, thr_crit: 220, base: 110, amp: 2.0, noise: 0.2 },
  { name: "振动", unit: "mm/s", thr_low: 0, thr_warn: 4.5, thr_crit: 7.0, base: 1.5, amp: 0.15, noise: 0.04 },
  { name: "电流", unit: "A", thr_low: 0, thr_warn: 12, thr_crit: 18, base: 4.0, amp: 0.2, noise: 0.05 },
  { name: "电压", unit: "V", thr_low: 180, thr_warn: 250, thr_crit: 280, base: 220, amp: 1.5, noise: 0.1 },
];

function approxSin(t) {
  const phase = ((Math.floor(t * 10) % 62) + 62) % 62;
  if (phase < 16) return phase / 16.0;
  if (phase < 31) return (31 - phase) / 15.0;
  if (phase < 47) return -(phase - 31) / 16.0;
  return -(62 - phase) / 15.0;
}

function round3(v) {
  return Math.round(v * 1000) / 1000;
}

function fillSensorHistory(model, sensor, base, amp, noise) {
  const history = [];
  for (let i = 0; i < VG_HISTORY_LEN; i++) {
    const t = i / 8.0;
    const mod = ((((i * 17 + model.tick * 3 + sensor.reg_addr) % 11) + 11) % 11) - 5;
    const n = mod * noise;
    history.push(round3(base + amp * approxSin(t) + n));
  }
  sensor.history = history;
  sensor.value = history[VG_HISTORY_LEN - 1];
}

function seedFleet(model) {
  model.sensors = [];
  for (let i = 0; i < VG_SENSOR_MAX; i++) {
    const kind = KINDS[i % 6];
    const group = Math.floor(i / 6) + 1;
    // vg_model.c uses a per-kind offset; replicate the exact values:
    let offset;
    if (kind === KINDS[0]) offset = i % 5;
    else if (kind === KINDS[1]) offset = i % 8;
    else if (kind === KINDS[2]) offset = i % 10;
    else if (kind === KINDS[3]) offset = 0.1 * (i % 4);
    else if (kind === KINDS[4]) offset = 0.2 * (i % 5);
    else offset = i % 6;
    const sensor = {
      id: "s_" + String(i + 1).padStart(2, "0"),
      name: kind.name + "-" + String(group).padStart(2, "0"),
      unit: kind.unit,
      kind: kind.name,
      value: 0,
      thr_warn: kind.thr_warn,
      thr_crit: kind.thr_crit,
      thr_low: kind.thr_low,
      severity: "ok",
      age_sec: 1 + (i % 5),
      period_ms: 1000,
      reg_addr: 0x100 + i,
      quality_pct: 90 + (i % 10),
      online: true,
      history: [],
      history_len: VG_HISTORY_LEN,
    };
    fillSensorHistory(model, sensor, kind.base + offset, kind.amp, kind.noise);
    model.sensors.push(sensor);
  }
  if (!model.selectedId || !getSensor(model, model.selectedId)) {
    model.selectedId = model.sensors[0].id;
  }
}

function defaultNet() {
  return {
    net_ok: true,
    mimo_ok: true,
    acq_ok: true,
    aud_ok: true,
    ota_active: false,
    ip: "192.168.1.50",
    latency_ms: 28,
  };
}

function createAlarm() {
  return {
    active: false,
    severity: "ok",
    title: "",
    sensor_id: "",
    value: 0,
    threshold: 0,
    duration_sec: 0,
    acked: false,
    muted: false,
  };
}

function createDiagnosis() {
  return {
    state: "idle",
    summary: "",
    risk: "low",
    causes: [],
    actions: [],
    confidence_pct: 0,
    error_msg: "",
    error_code: null,
    alarm_title: "",
    degraded: false,
    fallback_reason: null,
    need_shutdown: false,
    source: null,
  };
}

function formatTimeShort(d) {
  const p = (n) => String(n).padStart(2, "0");
  return p(d.getHours()) + ":" + p(d.getMinutes());
}

function appendLog(model, type, severity, text) {
  if (model.logs.length >= VG_LOG_MAX) {
    model.logs.shift();
  }
  model.logs.push({
    type: type,
    severity: severity,
    time: formatTimeShort(new Date()),
    text: text,
  });
}

function seedBaseLogs(model) {
  model.logs = [];
  appendLog(model, "sys", "info", "系统启动完成");
  appendLog(model, "sys", "ok", "网络连接已建立");
  appendLog(model, "ui", "info", "进入总览页");
  appendLog(model, "sys", "ok", "采集任务运行中");
  appendLog(model, "sys", "info", "时钟同步成功");
  appendLog(model, "ui", "info", "状态栏刷新");
  appendLog(model, "sys", "ok", "存储自检通过");
  appendLog(model, "sys", "info", "配置加载完成");
}

function setAlarmFromSensor(model, sensor, severity, title, threshold, duration) {
  model.alarm = {
    active: true,
    severity: severity,
    title: title,
    sensor_id: sensor.id,
    value: sensor.value,
    threshold: threshold,
    duration_sec: duration,
    acked: false,
    muted: false,
  };
}

function applyScenario(model, scenario) {
  const s = SCENARIO_IDS.includes(scenario) ? scenario : "normal";
  clearDiagTimer(model);
  model.scenario = s;
  model.alarm = createAlarm();
  model.net = defaultNet();
  model.diagnosis = createDiagnosis();
  seedFleet(model);

  const primary = model.sensors[0];
  switch (s) {
    case "warn":
      fillSensorHistory(model, primary, 58.0, 1.5, 0.15);
      primary.severity = "warn";
      primary.age_sec = 12;
      primary.quality_pct = 92;
      if (model.sensors.length > 2) {
        fillSensorHistory(model, model.sensors[2], 185.0, 2.0, 0.2);
        model.sensors[2].severity = "warn";
        model.sensors[2].age_sec = 8;
      }
      if (model.sensors.length > 8) {
        model.sensors[8].severity = "warn";
        fillSensorHistory(model, model.sensors[8], 60.0, 1.0, 0.1);
      }
      setAlarmFromSensor(model, primary, "warn", "温度预警", primary.thr_warn, 45);
      appendLog(model, "alarm", "warn", "告警触发: " + model.alarm.title);
      break;
    case "crit":
      fillSensorHistory(model, primary, 76.0, 2.0, 0.2);
      primary.severity = "crit";
      primary.age_sec = 30;
      primary.quality_pct = 88;
      if (model.sensors.length > 3) {
        fillSensorHistory(model, model.sensors[3], 6.2, 0.4, 0.1);
        model.sensors[3].severity = "warn";
        model.sensors[3].age_sec = 18;
      }
      if (model.sensors.length > 9) {
        model.sensors[9].severity = "crit";
        fillSensorHistory(model, model.sensors[9], 78.0, 1.5, 0.2);
      }
      setAlarmFromSensor(model, primary, "crit", "温度严重告警", primary.thr_crit, 120);
      appendLog(model, "alarm", "crit", "告警触发: " + model.alarm.title);
      break;
    case "offline":
      fillSensorHistory(model, primary, 0.0, 0.0, 0.0);
      primary.value = 0.0;
      primary.online = false;
      primary.severity = "offline";
      primary.age_sec = 300;
      primary.quality_pct = 0;
      model.net.acq_ok = false;
      if (model.sensors.length > 6) {
        model.sensors[6].online = false;
        model.sensors[6].severity = "offline";
        model.sensors[6].age_sec = 120;
        model.sensors[6].quality_pct = 0;
      }
      setAlarmFromSensor(model, primary, "offline", "传感器离线", 0.0, 300);
      appendLog(model, "alarm", "offline", "告警触发: " + model.alarm.title);
      break;
    case "ai_down":
      model.net.mimo_ok = false;
      model.net.latency_ms = 999;
      appendLog(model, "sys", "warn", "MiMo 服务不可用");
      break;
    case "ota":
      model.net.ota_active = true;
      appendLog(model, "ota", "info", "OTA 任务进行中");
      break;
    case "normal":
    default:
      appendLog(model, "sys", "ok", "场景切换: 正常");
      break;
  }
}

function createModel() {
  const model = {
    scenario: "normal",
    homeFilter: "all",
    selectedId: "",
    sensors: [],
    alarm: createAlarm(),
    net: defaultNet(),
    diagnosis: createDiagnosis(),
    logs: [],
    tick: 0,
    _listeners: [],
    _diagTimer: null,
  };
  seedBaseLogs(model);
  applyScenario(model, "normal");
  return model;
}

/* =====================================================================
 * Model accessors / mutators (mirror vg_model.h API).
 * ===================================================================== */

function notifyChange(model) {
  for (const cb of model._listeners.slice()) {
    try {
      cb(model);
    } catch (err) {
      // Listener errors must not break the model loop.
    }
  }
}

function onChange(model, cb) {
  if (typeof cb !== "function" || model._listeners.includes(cb)) {
    return;
  }
  model._listeners.push(cb);
}

function offChange(model, cb) {
  const idx = model._listeners.indexOf(cb);
  if (idx >= 0) {
    model._listeners.splice(idx, 1);
  }
}

function getSensor(model, id) {
  if (!id) {
    return model.sensors[0] || null;
  }
  for (const s of model.sensors) {
    if (s.id === id) {
      return s;
    }
  }
  return null;
}

function getPrimarySensor(model) {
  return model.sensors[0] || null;
}

function getSelectedSensor(model) {
  return getSensor(model, model.selectedId) || model.sensors[0] || null;
}

function setScenario(model, scenario) {
  const s = SCENARIO_IDS.includes(scenario) ? scenario : "normal";
  applyScenario(model, s);
  notifyChange(model);
}

function setHomeFilter(model, filter) {
  const f = HOME_FILTERS.includes(filter) ? filter : "all";
  if (f === model.homeFilter) {
    return;
  }
  model.homeFilter = f;
  notifyChange(model);
}

function severityRank(sev) {
  switch (sev) {
    case "crit":
      return 4;
    case "warn":
      return 3;
    case "offline":
      return 2;
    case "info":
      return 1;
    default:
      return 0;
  }
}

function homeSensors(model) {
  const pass = [];
  for (const s of model.sensors) {
    let ok = false;
    switch (model.homeFilter) {
      case "alarm":
        ok = s.severity === "warn" || s.severity === "crit";
        break;
      case "offline":
        ok = !s.online || s.severity === "offline";
        break;
      case "ok":
        ok = s.online && s.severity === "ok";
        break;
      case "all":
      default:
        ok = true;
        break;
    }
    if (ok) {
      pass.push(s);
    }
  }
  pass.sort((a, b) => {
    const ra = severityRank(a.severity);
    const rb = severityRank(b.severity);
    if (ra !== rb) {
      return rb - ra;
    }
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });
  return pass;
}

function countByFilter(model) {
  let alarm = 0;
  let offline = 0;
  let ok = 0;
  for (const s of model.sensors) {
    if (!s.online || s.severity === "offline") {
      offline++;
    } else if (s.severity === "warn" || s.severity === "crit") {
      alarm++;
    } else if (s.severity === "ok") {
      ok++;
    }
  }
  return { all: model.sensors.length, alarm: alarm, offline: offline, ok: ok };
}

function setSelectedSensor(model, id) {
  if (!id) {
    return;
  }
  const s = getSensor(model, id);
  if (!s) {
    return;
  }
  model.selectedId = id;
  notifyChange(model);
}

function ackAlarm(model) {
  if (!model.alarm.active || model.alarm.acked) {
    return;
  }
  model.alarm.acked = true;
  appendLog(model, "ui", "info", "告警已标记处理");
  notifyChange(model);
}

function muteAlarm(model) {
  if (!model.alarm.active) {
    return;
  }
  model.alarm.muted = true;
  appendLog(model, "ui", "info", "告警已静音");
  notifyChange(model);
}

function modelTick(model) {
  model.tick++;
  for (const s of model.sensors) {
    if (s.online && model.scenario !== "offline") {
      fillSensorHistory(model, s, s.value, 0.3, 0.03);
      s.age_sec = 1;
    }
  }
  if (model.alarm.active) {
    const p = getSensor(model, model.alarm.sensor_id);
    if (p) {
      model.alarm.value = p.value;
    }
    model.alarm.duration_sec++;
  }
  notifyChange(model);
}

function clearDiagTimer(model) {
  if (model._diagTimer) {
    clearTimeout(model._diagTimer);
    model._diagTimer = null;
  }
  if (model._diagResolve) {
    const resolve = model._diagResolve;
    model._diagResolve = null;
    resolve(null);
  }
}

function cancelMockDiagnosis(model) {
  clearDiagTimer(model);
  if (model.diagnosis.state === "loading") {
    model.diagnosis.state = "idle";
  }
}

function settleDiagnosis(model, scenario) {
  const d = model.diagnosis;
  if (scenario === "ai_down" || !model.net.mimo_ok) {
    d.state = "error";
    d.error_msg = "MiMo 不可用";
    d.error_code = "ai_down";
    d.alarm_title = model.alarm.active ? model.alarm.title : "无活动告警";
    appendLog(model, "diag", "warn", "AI 诊断失败: MiMo 不可用");
    return;
  }
  if (scenario === "warn") {
    d.state = "ok";
    d.alarm_title = model.alarm.title;
    d.summary = "温度接近预警阈值，建议关注散热与负载变化。";
    d.risk = "medium";
    d.causes = ["环境温度升高", "散热风扇效率下降", "负载短时偏高"];
    d.actions = ["检查散热通道", "降低非关键负载", "持续观察 10 分钟"];
    d.confidence_pct = 82;
  } else if (scenario === "crit") {
    d.state = "ok";
    d.alarm_title = model.alarm.title;
    d.summary = "温度已超严重阈值，存在过热风险，请立即处理。";
    d.risk = "high";
    d.causes = ["冷却系统异常", "传感器附近热源", "阈值配置可能偏紧"];
    d.actions = ["现场检查冷却", "必要时停机保护", "核对阈值与标定"];
    d.confidence_pct = 91;
  } else if (scenario === "offline") {
    d.state = "ok";
    d.alarm_title = model.alarm.title;
    d.summary = "传感器通信中断，采集链路可能异常。";
    d.risk = "high";
    d.causes = ["传感器供电异常", "RS485/线缆松动", "采集模块故障"];
    d.actions = ["检查供电与接线", "重启采集通道", "更换备用传感器"];
    d.confidence_pct = 88;
  } else {
    d.state = "ok";
    d.alarm_title = "无活动告警";
    d.summary = "当前无活动告警，系统运行正常。";
    d.risk = "low";
    d.causes = ["无异常指标"];
    d.actions = ["保持常规巡检"];
    d.confidence_pct = 70;
  }
  appendLog(model, "diag", "info", "AI 诊断完成");
}

/**
 * Mock diagnosis engine, mirroring vg_model_request_diagnosis:
 * ai_down / mimo down fails immediately; otherwise LOADING then settle
 * after ~500 ms. Returns a Promise resolving to model.diagnosis.
 */
function runMockDiagnosis(model, scenario, options) {
  const opts = options || {};
  const delayMs = opts.delayMs !== undefined ? opts.delayMs : VG_DIAG_LOAD_MS;
  const s = SCENARIO_IDS.includes(scenario) ? scenario : model.scenario;
  const d = model.diagnosis;
  if (d.state === "loading") {
    return Promise.resolve(null);
  }
  clearDiagTimer(model);
  d.state = "idle";
  d.summary = "";
  d.risk = "low";
  d.causes = [];
  d.actions = [];
  d.confidence_pct = 0;
  d.error_msg = "";
  d.error_code = null;
  d.degraded = false;
  d.fallback_reason = null;
  d.need_shutdown = false;
  d.source = null;
  d.alarm_title = model.alarm.active ? model.alarm.title : "无活动告警";

  if (s === "ai_down" || !model.net.mimo_ok) {
    d.state = "error";
    d.error_msg = "MiMo 不可用";
    d.error_code = "ai_down";
    appendLog(model, "diag", "warn", "AI 诊断失败: MiMo 不可用");
    notifyChange(model);
    return Promise.resolve(d);
  }

  d.state = "loading";
  appendLog(model, "diag", "info", "开始 AI 诊断");
  notifyChange(model);
  return new Promise((resolve) => {
    model._diagResolve = resolve;
    model._diagTimer = setTimeout(() => {
      model._diagTimer = null;
      model._diagResolve = null;
      settleDiagnosis(model, s);
      notifyChange(model);
      resolve(d);
    }, delayMs);
  });
}

/* =====================================================================
 * Diagnosis context builder and v2 result mapping.
 * ===================================================================== */

function severityToContextSeverity(sev) {
  switch (sev) {
    case "warn":
      return "warning";
    case "crit":
      return "critical";
    case "offline":
      return "offline";
    case "info":
      return "info";
    case "ok":
    default:
      return "ok";
  }
}

function buildRules(model) {
  const rules = [];
  for (const s of model.sensors) {
    if (rules.length >= RULES_CONTEXT_LIMIT) {
      break;
    }
    if (s.thr_warn > 0 && rules.length < RULES_CONTEXT_LIMIT) {
      rules.push({
        rule_id: s.id + "_warn",
        expr: s.id + " > " + s.thr_warn,
        severity: "warning",
        message: "超过预警阈值",
      });
    }
    if (s.thr_crit > 0 && rules.length < RULES_CONTEXT_LIMIT) {
      rules.push({
        rule_id: s.id + "_crit",
        expr: s.id + " > " + s.thr_crit,
        severity: "critical",
        message: "超过严重阈值",
      });
    }
    if (s.thr_low > 0 && rules.length < RULES_CONTEXT_LIMIT) {
      rules.push({
        rule_id: s.id + "_low",
        expr: s.id + " < " + s.thr_low,
        severity: "warning",
        message: "低于下限阈值",
      });
    }
  }
  return rules.slice(0, RULES_CONTEXT_LIMIT);
}

/**
 * Build the optional structured context for a diagnosis request from the
 * current mock model. Sections are omitted when there is no data, so the
 * request never carries an invalid section.
 */
function buildDiagnosisContext(model, now) {
  const ts = typeof now === "number" ? now : Date.now();
  const ctx = {};
  const a = model.alarm;
  if (a && a.active) {
    ctx.event = {
      event_id: "alarm_" + a.sensor_id,
      severity: severityToContextSeverity(a.severity),
      title: a.title,
      current_value: round3(a.value),
      threshold: round3(a.threshold),
      duration_sec: a.duration_sec,
      sensor_id: a.sensor_id,
      ts_ms: ts,
    };
  }
  const sensor = getSelectedSensor(model);
  if (sensor && sensor.history && sensor.history.length > 0) {
    const history = [];
    const start = Math.max(0, sensor.history.length - HISTORY_CONTEXT_LIMIT);
    for (let i = start; i < sensor.history.length; i++) {
      const values = {};
      values[sensor.id] = round3(sensor.history[i]);
      history.push({
        ts_ms: ts - (sensor.history.length - 1 - i) * (sensor.period_ms || 1000),
        values: values,
      });
    }
    if (history.length > 0) {
      ctx.history = history;
    }
  }
  const rules = buildRules(model);
  if (rules.length > 0) {
    ctx.rules = rules;
  }
  ctx.device = {
    name: sensor ? sensor.name : "VelaGuard",
    model: "VelaGuard Sensor",
    description: sensor ? sensor.name + " 模拟监测点，数据由本地模型生成" : "VelaGuard 模拟监测点",
  };
  return ctx;
}

function truncate(text, max) {
  const s = String(text == null ? "" : text);
  return s.length > max ? s.slice(0, max) : s;
}

/**
 * Map a v2 diagnosis result (envelope.result) to board diagnosis fields.
 * Returns null when result is not a structured object.
 */
function mapResultToDiagnosis(result) {
  if (!result || typeof result !== "object" || Array.isArray(result)) {
    return null;
  }
  const risk = ["low", "medium", "high"].includes(result.risk_level)
    ? result.risk_level
    : "low";
  const causes = Array.isArray(result.possible_causes)
    ? result.possible_causes.slice(0, 3).map((c) => truncate(c, 64))
    : [];
  const actions = Array.isArray(result.recommended_actions)
    ? result.recommended_actions.slice(0, 3).map((c) => truncate(c, 64))
    : [];
  let confidencePct = null;
  if (
    typeof result.confidence === "number" &&
    !Number.isNaN(result.confidence) &&
    result.confidence >= 0 &&
    result.confidence <= 1
  ) {
    confidencePct = Math.round(result.confidence * 100);
  }
  return {
    state: "ok",
    summary: truncate(
      typeof result.diagnosis_summary === "string" ? result.diagnosis_summary : "诊断完成",
      128
    ),
    risk: risk,
    causes: causes,
    actions: actions,
    confidence_pct: confidencePct,
    degraded: result.source === "fallback" || result.advisory_only === true,
    fallback_reason:
      typeof result.fallback_reason === "string" ? truncate(result.fallback_reason, 160) : null,
    need_shutdown: result.need_shutdown === true,
    source: typeof result.source === "string" ? result.source : null,
  };
}

function applyResultToDiagnosis(model, mapped) {
  const d = model.diagnosis;
  d.state = "ok";
  d.summary = mapped.summary;
  d.risk = mapped.risk;
  d.causes = mapped.causes;
  d.actions = mapped.actions;
  d.confidence_pct = mapped.confidence_pct;
  d.degraded = mapped.degraded;
  d.fallback_reason = mapped.fallback_reason;
  d.need_shutdown = mapped.need_shutdown;
  d.source = mapped.source;
  d.error_msg = "";
  d.error_code = null;
  d.alarm_title = model.alarm.active ? model.alarm.title : "无活动告警";
  appendLog(model, "diag", "info", "AI 诊断完成");
}

function applyErrorToDiagnosis(model, envelope) {
  const d = model.diagnosis;
  d.state = "error";
  d.error_code = envelope && envelope.error_code ? envelope.error_code : "internal_error";
  d.error_msg =
    envelope && envelope.error_message
      ? envelope.error_message
      : "诊断失败: " + d.error_code;
  d.alarm_title = model.alarm.active ? model.alarm.title : "无活动告警";
  appendLog(model, "diag", "warn", "AI 诊断失败: " + d.error_code);
}

/* =====================================================================
 * Request building and envelope helpers.
 * ===================================================================== */

function newReqId() {
  const bytes = new Uint8Array(16);
  if (typeof crypto !== "undefined" && crypto.getRandomValues) {
    crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < 16; i++) {
      bytes[i] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return (
    hex.slice(0, 8) +
    "-" +
    hex.slice(8, 12) +
    "-" +
    hex.slice(12, 16) +
    "-" +
    hex.slice(16, 20) +
    "-" +
    hex.slice(20)
  );
}

/**
 * Build a diagnosis request body with an automatically computed
 * payload_hash. Resolves to { body, full, payload_hash, payload }.
 */
async function buildRequest(opts) {
  const body = {
    req_id: String(opts.req_id),
    device_id: String(opts.device_id),
    created_ts_ms: new PyInt(opts.created_ts_ms),
    type: REQUEST_TYPE,
    note: opts.note || REQUEST_NOTE,
  };
  if (opts.context && typeof opts.context === "object") {
    body.context = opts.context;
  }
  const payload_hash = await computePayloadHash(body);
  const full = Object.assign({}, body, { payload_hash: payload_hash });
  return {
    body: body,
    full: full,
    payload_hash: payload_hash,
    payload: pyDumps(full),
  };
}

function normalizeEnvelope(data) {
  return {
    req_id: data.req_id !== undefined ? data.req_id : null,
    device_id: data.device_id !== undefined ? data.device_id : null,
    type: data.type !== undefined ? data.type : null,
    status: typeof data.status === "string" ? data.status : "unknown",
    error_code: data.error_code !== undefined ? data.error_code : null,
    error_message: data.error_message !== undefined ? data.error_message : null,
    result: data.result !== undefined ? data.result : null,
    received_ts_ms: data.received_ts_ms !== undefined ? data.received_ts_ms : null,
    bridge_ts_ms: data.bridge_ts_ms !== undefined ? data.bridge_ts_ms : null,
  };
}

/* =====================================================================
 * Labels (mirror vg_model.c label helpers).
 * ===================================================================== */

function severityLabelZh(sev) {
  switch (sev) {
    case "warn":
      return "预警";
    case "crit":
      return "严重";
    case "offline":
      return "离线";
    case "info":
      return "信息";
    case "ok":
    default:
      return "正常";
  }
}

function scenarioLabel(scenario) {
  const s = SCENARIOS.find((x) => x.id === scenario);
  return s ? s.label : "正常";
}

function logTypeLabelZh(type) {
  switch (type) {
    case "alarm":
      return "告警";
    case "diag":
      return "诊断";
    case "sys":
      return "系统";
    case "ota":
      return "OTA";
    case "ui":
      return "界面";
    default:
      return "事件";
  }
}

function riskLabelZh(risk) {
  if (risk === "high") return "高";
  if (risk === "medium") return "中";
  if (risk === "low") return "低";
  return "未知";
}

function fmt1(v) {
  // Truncate toward zero to one decimal, like the C simulator.
  let vi = Math.trunc(v);
  let vf = Math.trunc((v - vi) * 10);
  if (vf < 0) vf = -vf;
  return vi + "." + vf;
}

const api = {
  // canonical JSON + hash (shared contract helpers)
  pyDumps: pyDumps,
  sha256Sync: sha256Sync,
  computePayloadHash: computePayloadHash,
  parseJsonPreservingInts: parseJsonPreservingInts,
  PyInt: PyInt,

  // constants
  REQUEST_TYPE: REQUEST_TYPE,
  REQUEST_NOTE: REQUEST_NOTE,
  VG_DISP_W: VG_DISP_W,
  VG_DISP_H: VG_DISP_H,
  VG_STATUS_H: VG_STATUS_H,
  VG_CONTENT_H: VG_CONTENT_H,
  VG_PAGE_PAD: VG_PAGE_PAD,
  VG_GAP: VG_GAP,
  VG_CARD_RADIUS: VG_CARD_RADIUS,
  VG_MIN_TOUCH_H: VG_MIN_TOUCH_H,
  VG_MIN_TOUCH_W: VG_MIN_TOUCH_W,
  VG_LIST_ROW_H: VG_LIST_ROW_H,
  VG_HISTORY_LEN: VG_HISTORY_LEN,
  VG_LOG_MAX: VG_LOG_MAX,
  VG_SENSOR_MAX: VG_SENSOR_MAX,
  VG_DIAG_LOAD_MS: VG_DIAG_LOAD_MS,
  HISTORY_CONTEXT_LIMIT: HISTORY_CONTEXT_LIMIT,
  RULES_CONTEXT_LIMIT: RULES_CONTEXT_LIMIT,
  MQTT_DEFAULT_URL: MQTT_DEFAULT_URL,
  MQTT_CONNECT_TIMEOUT_MS: MQTT_CONNECT_TIMEOUT_MS,
  REAL_RESPONSE_TIMEOUT_MS: REAL_RESPONSE_TIMEOUT_MS,
  SCENARIOS: SCENARIOS,
  HOME_FILTERS: HOME_FILTERS,

  // model lifecycle
  createModel: createModel,
  modelTick: modelTick,
  onChange: onChange,
  offChange: offChange,
  notifyChange: notifyChange,

  // model accessors / mutators
  getSensor: getSensor,
  getPrimarySensor: getPrimarySensor,
  getSelectedSensor: getSelectedSensor,
  setScenario: setScenario,
  setHomeFilter: setHomeFilter,
  homeSensors: homeSensors,
  countByFilter: countByFilter,
  setSelectedSensor: setSelectedSensor,
  ackAlarm: ackAlarm,
  muteAlarm: muteAlarm,
  appendLog: appendLog,

  // diagnosis
  runMockDiagnosis: runMockDiagnosis,
  cancelMockDiagnosis: cancelMockDiagnosis,
  buildDiagnosisContext: buildDiagnosisContext,
  mapResultToDiagnosis: mapResultToDiagnosis,
  applyResultToDiagnosis: applyResultToDiagnosis,
  applyErrorToDiagnosis: applyErrorToDiagnosis,

  // request / envelope helpers
  newReqId: newReqId,
  buildRequest: buildRequest,
  normalizeEnvelope: normalizeEnvelope,

  // labels / formatting
  severityLabelZh: severityLabelZh,
  scenarioLabel: scenarioLabel,
  logTypeLabelZh: logTypeLabelZh,
  riskLabelZh: riskLabelZh,
  fmt1: fmt1,
};

if (typeof module !== "undefined" && module.exports) {
  module.exports = api;
} else if (typeof window !== "undefined") {
  window.BoardCore = api;
}
