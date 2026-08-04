"use strict";

/* =====================================================================
 * Python-compatible canonical JSON and SHA-256 helpers.
 *
 * payload_hash in the console must match
 * ai_bridge.cli.synthetic_publisher.build_request:
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
    // Python json.dumps emits these tokens for non-finite floats; the console
    // never generates them through the editors, but keep parity anyway.
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
 * Contract constants and mock scenarios.
 * ===================================================================== */

const REQUEST_TYPE = "diagnosis";
const REQUEST_NOTE = "synthetic publisher";
const HISTORY_LIMIT = 50;
const MQTT_DEFAULT_URL = "ws://107.174.123.74:9001";
const MQTT_CONNECT_TIMEOUT_MS = 8000;
const REAL_RESPONSE_TIMEOUT_MS = 60000;

const SCENARIOS = [
  {
    id: "mimo_success",
    label: "v2 MiMo 成功",
    desc: "MiMo 调用成功，返回完整 v2 诊断结果（source=mimo）。",
    defaultDelayMs: 800,
    sendsProcessing: true,
  },
  {
    id: "fallback",
    label: "fallback 降级",
    desc: "MiMo HTTP/网络失败且请求预算剩余，桥接降级返回 status=success、source=fallback、advisory_only=true。",
    defaultDelayMs: 1200,
    sendsProcessing: true,
  },
  {
    id: "schema_invalid",
    label: "schema 非法（provider_error）",
    desc: "MiMo 返回非法结构化输出，发布 error/provider_error，不触发 fallback。",
    defaultDelayMs: 600,
    sendsProcessing: true,
  },
  {
    id: "timeout",
    label: "整体超时（timeout）",
    desc: "超过整体 deadline，发布 error/timeout，不触发 fallback。",
    defaultDelayMs: 2500,
    sendsProcessing: true,
  },
  {
    id: "validation_error",
    label: "校验失败（validation_error）",
    desc: "请求在解析阶段被拒绝（例如缺少字段），直接发布 error/validation_error；真实桥接不会发布 processing。",
    defaultDelayMs: 200,
    sendsProcessing: false,
  },
  {
    id: "conflict",
    label: "幂等冲突（conflict）",
    desc: "同一 req_id 但 payload_hash 不同，幂等表直接拒绝并发布 error/conflict；真实桥接不会发布 processing。",
    defaultDelayMs: 300,
    sendsProcessing: false,
  },
];

const STATUS_CLASS = {
  processing: "badge-info",
  success: "badge-success",
  error: "badge-error",
  pending: "badge-pending",
};

const ERROR_CLASS = {
  validation_error: "badge-warn",
  conflict: "badge-error",
  timeout: "badge-warn",
  provider_error: "badge-error",
  internal_error: "badge-error",
};

function scenarioById(id) {
  return SCENARIOS.find((s) => s.id === id) || SCENARIOS[0];
}

function buildEnvelope({
  req_id,
  device_id,
  type,
  status,
  error_code = null,
  error_message = null,
  result = null,
  received_ts_ms,
  bridge_ts_ms,
}) {
  return {
    req_id,
    device_id,
    type,
    status,
    error_code,
    error_message,
    result,
    received_ts_ms,
    bridge_ts_ms,
  };
}

function riskFromEvent(event) {
  if (!event || typeof event !== "object" || typeof event.severity !== "string") {
    return "low";
  }
  const sev = event.severity.trim().toLowerCase();
  if (sev === "critical" || sev === "error") {
    return "high";
  }
  if (sev === "warning") {
    return "medium";
  }
  return "low";
}

function mimoResult() {
  return {
    diagnosis_summary: "温度持续超限，建议优先检查冷却风扇转速与散热器状态。",
    risk_level: "high",
    possible_causes: ["冷却风扇转速低于设定下限", "散热器积尘导致热阻升高"],
    recommended_actions: [
      "检查冷却风扇供电与转速",
      "清理散热器并复测温度趋势",
      "若 30 分钟内持续超限，联系维护人员",
    ],
    need_shutdown: false,
    confidence: 0.87,
    reasons: ["温度连续 5 个采样点超过 75°C", "风扇转速低于 3000 rpm"],
    recommendations: ["下次保养时更换风扇轴承"],
    source: "mimo",
  };
}

function fallbackResult(context) {
  return {
    diagnosis_summary: "Cloud AI diagnosis is temporarily unavailable; local template result.",
    risk_level: riskFromEvent(context && context.event),
    possible_causes: ["Cloud AI service is temporarily unavailable (provider failure)."],
    recommended_actions: [
      "Retry the diagnosis after a short delay.",
      "Continue local monitoring and check the latest alarm/telemetry values.",
    ],
    need_shutdown: false,
    confidence: 0.0,
    source: "fallback",
    advisory_only: true,
    fallback_reason: "MiMo provider HTTP/network failure with remaining request budget",
  };
}

function buildTerminalEnvelope(scenarioId, request, receivedTsMs) {
  const base = {
    req_id: request.req_id,
    device_id: request.device_id,
    type: REQUEST_TYPE,
    received_ts_ms: receivedTsMs,
    bridge_ts_ms: Date.now(),
  };
  switch (scenarioId) {
    case "mimo_success":
      return buildEnvelope({ ...base, status: "success", result: mimoResult() });
    case "fallback":
      return buildEnvelope({
        ...base,
        status: "success",
        result: fallbackResult(request.context || null),
      });
    case "schema_invalid":
      return buildEnvelope({
        ...base,
        status: "error",
        error_code: "provider_error",
        error_message: "provider returned invalid structured output",
      });
    case "timeout":
      return buildEnvelope({
        ...base,
        status: "error",
        error_code: "timeout",
        error_message: "request deadline exceeded",
      });
    case "validation_error":
      return buildEnvelope({
        ...base,
        status: "error",
        error_code: "validation_error",
        error_message: "missing or invalid field: payload_hash",
      });
    case "conflict":
      return buildEnvelope({
        ...base,
        status: "error",
        error_code: "conflict",
        error_message: "req_id reused with different payload_hash",
      });
    default:
      return buildEnvelope({ ...base, status: "error", error_code: "internal_error", error_message: "unknown scenario" });
  }
}

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

let statusTimer = null;

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
 * Simulation flow.
 * ===================================================================== */

async function handleSend() {
  if (state.sending) {
    return;
  }
  const collected = collectRequest();
  if (!collected.ok) {
    showStatus("发送失败：" + collected.errors[0], "error");
    return;
  }
  if (state.mode === "real") {
    if (state.mqtt.status !== "connected") {
      showStatus("真实模式需要先连接 broker（可在左侧连接，或切换到 Mock 模式）", "error");
      return;
    }
    await sendReal(collected);
    return;
  }
  await sendMock(collected);
}

function beginSending(text) {
  state.sending = true;
  document.getElementById("btn-send").disabled = true;
  document.getElementById("sending-text").textContent = text || "处理中…";
  document.getElementById("sending-indicator").hidden = false;
}

function endSending() {
  state.sending = false;
  document.getElementById("btn-send").disabled = false;
  document.getElementById("sending-indicator").hidden = true;
}

async function sendMock(collected) {
  const scenario = scenarioById(state.scenarioId);
  beginSending("模拟中，请稍候…");
  showStatus("模拟中…", "");

  const receivedTs = Date.now();
  const entry = {
    id: "e" + state.entrySeq++,
    reqId: collected.request.req_id,
    deviceId: collected.request.device_id,
    scenarioId: scenario.id,
    scenarioLabel: scenario.label,
    mode: "mock",
    receivedTs,
    status: "pending",
    events: [],
  };
  state.history.unshift(entry);
  if (state.history.length > HISTORY_LIMIT) {
    state.history.length = HISTORY_LIMIT;
  }
  state.activeEntryId = entry.id;
  state.activeEventIndex = -1;
  renderHistory();

  const topicBase = "vg/" + entry.deviceId + "/ai/response/" + entry.reqId;
  if (scenario.sendsProcessing) {
    const processing = buildEnvelope({
      req_id: entry.reqId,
      device_id: entry.deviceId,
      type: REQUEST_TYPE,
      status: "processing",
      received_ts_ms: receivedTs,
      bridge_ts_ms: Date.now(),
    });
    pushEvent(entry, processing, topicBase, "processing");
    selectEvent(entry.id, entry.events.length - 1);
  } else {
    pushNote(
      entry,
      "解析/幂等阶段直接拒绝，真实桥接不会发布 processing（与 ai_bridge.application.handle_request 一致）"
    );
    renderTimeline();
  }

  await delay(state.delayMs);

  const terminal = buildTerminalEnvelope(scenario.id, collected.request, receivedTs);
  pushEvent(entry, terminal, topicBase, "terminal");
  entry.status = terminal.status;
  renderHistory();
  selectEvent(entry.id, entry.events.length - 1);

  showStatus(
    "已收到终态：" + terminal.status + (terminal.error_code ? " / " + terminal.error_code : ""),
    terminal.status === "success" ? "success" : "error"
  );
  endSending();
}

/* =====================================================================
 * MQTT over WebSocket (real mode).
 * ===================================================================== */

function defaultClientId() {
  let rand;
  if (typeof crypto !== "undefined" && crypto.getRandomValues) {
    rand = Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) =>
      b.toString(16).padStart(2, "0")
    ).join("");
  } else {
    rand = Math.random().toString(16).slice(2, 10);
  }
  return "dc-" + rand;
}

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
  const badge = document.getElementById("conn-badge");
  badge.textContent = label;
  badge.className = cls;
  const statusEl = document.getElementById("conn-status");
  statusEl.textContent = label;
  statusEl.className = cls;
  const msgEl = document.getElementById("conn-message");
  msgEl.textContent = message || "";
  msgEl.className =
    "status-message" +
    (status === "error" ? " is-error" : status === "connected" ? " is-success" : "");
}

function findEntryByReqId(reqId) {
  return state.history.find((e) => e.reqId === reqId);
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

function connectMqtt() {
  const url = document.getElementById("f-broker-url").value.trim();
  const clientId = document.getElementById("f-client-id").value.trim();
  const username = document.getElementById("f-mqtt-user").value.trim();
  const password = document.getElementById("f-mqtt-pass").value;

  if (typeof mqtt === "undefined") {
    setConnStatus("error", "mqtt.js 未加载（检查 debug-console/vendor/mqtt.min.js）");
    showStatus("无法连接：mqtt.js 未加载", "error");
    return;
  }
  if (!/^wss?:\/\/[^/]+/.test(url)) {
    setConnStatus("error", "Broker URL 必须是 ws:// 或 wss:// 地址");
    showStatus("连接失败：Broker URL 无效", "error");
    return;
  }
  disconnectMqtt();

  const client = mqtt.connect(url, {
    clientId: clientId || defaultClientId(),
    username: username || undefined,
    password: password || undefined,
    clean: true,
    protocolVersion: 4,
    reconnectPeriod: 0,
    connectTimeout: MQTT_CONNECT_TIMEOUT_MS,
  });
  state.mqtt.client = client;
  state.mqtt.status = "connecting";
  setConnStatus("connecting", "正在连接 " + url + " …");
  showStatus("正在连接 broker…", "");

  client.on("connect", () => {
    state.mqtt.status = "connected";
    setConnStatus("connected", "已连接 " + url);
    showStatus("MQTT 已连接", "success");
  });
  client.on("message", (topic, payload) => {
    handleMqttMessage(topic, payload);
  });
  client.on("error", (err) => {
    state.mqtt.status = "error";
    const message = err && err.message ? err.message : String(err);
    setConnStatus("error", "连接错误：" + message);
    showStatus("MQTT 连接错误：" + message, "error");
    failPendingRealEntries("连接错误，等待中的请求已取消：" + message);
  });
  client.on("offline", () => {
    if (state.mqtt.status !== "error") {
      state.mqtt.status = "disconnected";
      setConnStatus("disconnected", "已离线，请重试连接");
      failPendingRealEntries("已离线，等待中的请求已取消；请重新连接后重试");
    }
  });
  client.on("close", () => {
    if (state.mqtt.status === "connected" || state.mqtt.status === "connecting") {
      state.mqtt.status = "disconnected";
      setConnStatus("disconnected", "连接已断开");
      failPendingRealEntries("连接已断开，等待中的请求已取消；请重新连接后重试");
    }
  });
}

function disconnectMqtt() {
  const client = state.mqtt.client;
  state.mqtt.client = null;
  state.mqtt.status = "disconnected";
  failPendingRealEntries("连接已断开，等待中的请求已取消；请重新连接后重试");
  setConnStatus("disconnected", "未连接");
  if (client) {
    try {
      client.end(true);
    } catch (err) {
      // best effort
    }
  }
}

function handleMqttMessage(topic, payload) {
  let text = "";
  try {
    text = new TextDecoder().decode(payload);
  } catch (err) {
    text = String(payload);
  }
  let data;
  try {
    data = JSON.parse(text);
  } catch (err) {
    const m = topic.match(/\/ai\/response\/([^/]+)$/);
    const reqId = m ? m[1] : null;
    const entry = reqId ? findEntryByReqId(reqId) : null;
    if (entry) {
      pushNote(entry, "收到非法 JSON 响应：" + err.message);
      renderTimeline();
    } else {
      showStatus("收到无法解析的响应（" + topic + "）", "error");
    }
    return;
  }

  const reqId =
    data && data.req_id !== undefined ? String(data.req_id) : null;
  const entry = reqId ? findEntryByReqId(reqId) : null;
  if (!entry) {
    showStatus("收到未知 req_id 的响应：" + (reqId || topic), "error");
    return;
  }

  const envelope = normalizeEnvelope(data);
  const kind = envelope.status === "processing" ? "processing" : "terminal";
  pushEvent(entry, envelope, topic, kind);
  if (envelope.status === "success" || envelope.status === "error") {
    entry.status = envelope.status;
    clearRealTimer(entry);
    unsubscribeResponseTopic(entry);
    renderHistory();
    selectEvent(entry.id, entry.events.length - 1);
    endSending();
    showStatus(
      "已收到终态：" + envelope.status + (envelope.error_code ? " / " + envelope.error_code : ""),
      envelope.status === "success" ? "success" : "error"
    );
  } else {
    selectEvent(entry.id, entry.events.length - 1);
    showStatus("已收到 processing，等待终态…", "");
  }
}

function clearRealTimer(entry) {
  const timer = state.mqtt.pending.get(entry.reqId);
  if (timer) {
    clearTimeout(timer);
    state.mqtt.pending.delete(entry.reqId);
  }
}

function failPendingRealEntries(message) {
  let changed = false;
  for (const [reqId, timer] of state.mqtt.pending) {
    clearTimeout(timer);
    const entry = findEntryByReqId(reqId);
    if (entry && entry.status === "pending") {
      entry.status = "superseded";
      pushNote(entry, message);
      changed = true;
    }
  }
  state.mqtt.pending.clear();
  if (changed) {
    renderHistory();
    renderTimeline();
    endSending();
  }
}

function supersedePendingForReqId(reqId, keepEntryId) {
  let changed = false;
  for (const entry of state.history) {
    if (entry.reqId === reqId && entry.id !== keepEntryId && entry.status === "pending") {
      clearRealTimer(entry);
      entry.status = "superseded";
      pushNote(
        entry,
        "同一 req_id 的后续请求已发送，本条等待状态被取代；桥接将按新 payload_hash 判定重复/冲突"
      );
      changed = true;
    }
  }
  if (changed) {
    renderHistory();
    renderTimeline();
  }
}

function unsubscribeResponseTopic(entry) {
  const client = state.mqtt.client;
  if (!client) {
    return;
  }
  try {
    client.unsubscribe(entry.responseTopic);
  } catch (err) {
    // best effort
  }
}

function failRealEntry(entry, message) {
  clearRealTimer(entry);
  const env = buildEnvelope({
    req_id: entry.reqId,
    device_id: entry.deviceId,
    type: REQUEST_TYPE,
    status: "error",
    error_code: "internal_error",
    error_message: message,
    received_ts_ms: Date.now(),
    bridge_ts_ms: Date.now(),
  });
  pushEvent(entry, env, entry.responseTopic, "terminal");
  entry.status = "error";
  renderHistory();
  selectEvent(entry.id, entry.events.length - 1);
  endSending();
  showStatus("发送失败：" + message, "error");
}

async function sendReal(collected) {
  const hash = await computePayloadHash(collected.request.body);
  const body = {};
  Object.assign(body, collected.request.body, { payload_hash: hash });
  const payloadText = pyDumps(body);
  const requestTopic = "vg/" + collected.request.device_id + "/ai/request";
  const responseTopic =
    "vg/" + collected.request.device_id + "/ai/response/" + collected.request.req_id;

  const receivedTs = Date.now();
  const entry = {
    id: "e" + state.entrySeq++,
    reqId: collected.request.req_id,
    deviceId: collected.request.device_id,
    scenarioId: null,
    scenarioLabel: "真实 MQTT",
    mode: "real",
    receivedTs,
    status: "pending",
    events: [],
    requestTopic,
    responseTopic,
  };
  state.history.unshift(entry);
  if (state.history.length > HISTORY_LIMIT) {
    state.history.length = HISTORY_LIMIT;
  }
  state.activeEntryId = entry.id;
  state.activeEventIndex = -1;
  renderHistory();
  beginSending("已发布，等待桥接响应…");

  pushNote(entry, "请求 topic：" + requestTopic);
  pushNote(entry, "响应订阅：" + responseTopic);
  renderTimeline();
  supersedePendingForReqId(entry.reqId, entry.id);

  const client = state.mqtt.client;
  client.subscribe(responseTopic, { qos: 1 }, (subErr) => {
    if (subErr) {
      failRealEntry(entry, "订阅失败：" + (subErr.message || String(subErr)));
      return;
    }
    pushNote(entry, "已订阅响应 topic，发布请求（QoS 1）…");
    renderTimeline();
    client.publish(requestTopic, payloadText, { qos: 1, retain: false }, (pubErr) => {
      if (pubErr) {
        failRealEntry(entry, "发布失败：" + (pubErr.message || String(pubErr)));
        return;
      }
      pushNote(entry, "已发布：" + requestTopic);
      renderTimeline();
      showStatus("已发布 req_id=" + collected.request.req_id + "，等待桥接响应…", "success");
    });
  });

  const timer = setTimeout(() => {
    const current = findEntryByReqId(entry.reqId);
    if (current && current.status === "pending") {
      pushNote(
        current,
        "本地等待超时（" + REAL_RESPONSE_TIMEOUT_MS + " ms），未收到终态；请检查桥接进程与 provider 状态"
      );
      renderTimeline();
      endSending();
    }
  }, REAL_RESPONSE_TIMEOUT_MS);
  state.mqtt.pending.set(entry.reqId, timer);
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

function switchMode(mode) {
  if (mode !== "real" && mode !== "mock") {
    return;
  }
  state.mode = mode;
  const isReal = mode === "real";
  document.getElementById("conn-panel").hidden = !isReal;
  document.getElementById("mock-controls").hidden = isReal;
  const modeBadge = document.getElementById("mode-badge");
  modeBadge.textContent = isReal ? "真实模式" : "Mock 模式";
  modeBadge.className = "badge " + (isReal ? "badge-info" : "badge-ghost");
  document.getElementById("mode-hint").textContent = isReal
    ? "真实模式默认连接 dev broker（WebSocket 9001），由真实 AI Bridge 处理；连接失败时可一键切换 Mock 继续演示。"
    : "Mock 模式完全离线，不依赖网络与 broker；内置六个场景，仅用于演示与契约核对。";
  for (const btn of document.querySelectorAll("[data-mode-select]")) {
    btn.classList.toggle("is-active", btn.dataset.modeSelect === mode);
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
  document.getElementById("btn-connect").addEventListener("click", connectMqtt);
  document.getElementById("btn-disconnect").addEventListener("click", disconnectMqtt);

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

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    pyDumps,
    sha256Sync,
    computePayloadHash,
    parseJsonPreservingInts,
    PyInt,
    SCENARIOS,
    buildEnvelope,
    buildTerminalEnvelope,
    REQUEST_TYPE,
    REQUEST_NOTE,
  };
} else if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
}
