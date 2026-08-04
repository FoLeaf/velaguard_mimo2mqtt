(function initDebugCore(root) {
    "use strict";

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



  const api = { REQUEST_TYPE, REQUEST_NOTE, HISTORY_LIMIT, MQTT_DEFAULT_URL, MQTT_CONNECT_TIMEOUT_MS, REAL_RESPONSE_TIMEOUT_MS, SCENARIOS, STATUS_CLASS, ERROR_CLASS, scenarioById, buildEnvelope, riskFromEvent, mimoResult, fallbackResult, buildTerminalEnvelope };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else if (typeof window !== "undefined") {
    window.DebugCore = api;
  }

})(typeof window !== "undefined" ? window : globalThis);
