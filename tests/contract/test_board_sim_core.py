"""Contract checks for board-sim/board-core.js under node.js.

Covers the simulator's pure logic that mirrors vg_model.c and the AI Bridge
contract: scenario/fleet state, diagnosis context shape and limits, v2
result mapping (including fallback flags), mock diagnosis outcomes, and a
real buildRequest whose payload_hash matches the Python reference.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

NODE = shutil.which("node")
CORE_JS = Path(__file__).resolve().parents[2] / "board-sim" / "board-core.js"

requires_node = pytest.mark.skipif(
    NODE is None,
    reason="node.js is required to execute the board-core contract check",
)

_NODE_SCRIPT = textwrap.dedent(
    """\
    const core = require(process.argv[1]);
    (async () => {
      const model = core.createModel();
      const out = {};

      out.normal = {
        scenario: model.scenario,
        count: model.sensors.length,
        selected: model.selectedId,
        historyLen: model.sensors[0].history.length,
        logCount: model.logs.length,
      };

      core.setScenario(model, "warn");
      out.warn = {
        alarm: model.alarm.active
          ? { title: model.alarm.title, severity: model.alarm.severity }
          : null,
        primarySev: model.sensors[0].severity,
        counts: core.countByFilter(model),
      };

      const ctx = core.buildDiagnosisContext(model);
      out.ctx = {
        keys: Object.keys(ctx).sort(),
        eventTitle: ctx.event ? ctx.event.title : null,
        eventSeverity: ctx.event ? ctx.event.severity : null,
        historyLen: ctx.history ? ctx.history.length : 0,
        historyEntryKeys: ctx.history && ctx.history[0]
          ? Object.keys(ctx.history[0]).sort()
          : [],
        historyValuesKeys: ctx.history && ctx.history[0]
          ? Object.keys(ctx.history[0].values)
          : [],
        rulesLen: ctx.rules ? ctx.rules.length : 0,
        ruleKeys: ctx.rules && ctx.rules[0]
          ? Object.keys(ctx.rules[0]).sort()
          : [],
        deviceName: ctx.device ? ctx.device.name : null,
        deviceModel: ctx.device ? ctx.device.model : null,
      };

      const mapped = core.mapResultToDiagnosis({
        diagnosis_summary: "s".repeat(200),
        risk_level: "medium",
        possible_causes: ["c1", "c2", "c3", "c4"],
        recommended_actions: [],
        confidence: 0.865,
        source: "fallback",
        advisory_only: true,
        fallback_reason: "provider unavailable",
        need_shutdown: false,
      });
      out.mapped = {
        summaryLen: mapped.summary.length,
        risk: mapped.risk,
        causes: mapped.causes.length,
        actions: mapped.actions.length,
        confidencePct: mapped.confidence_pct,
        degraded: mapped.degraded,
        fallbackReason: mapped.fallback_reason,
      };
      out.mappedInvalid = core.mapResultToDiagnosis(null) === null;

      const m2 = core.createModel();
      core.setScenario(m2, "ai_down");
      const aiDown = await core.runMockDiagnosis(m2, "ai_down", { delayMs: 0 });
      out.aiDown = { state: aiDown.state, errorMsg: aiDown.error_msg };

      const built = await core.buildRequest({
        req_id: "r-board-core",
        device_id: "dev01",
        created_ts_ms: 1782450000000,
        context: { event: { title: "温度预警", severity: "warning" } },
      });
      out.request = {
        payloadHash: built.payload_hash,
        payload: built.payload,
        topicDeviceId: built.full.device_id,
      };

      const m3 = core.createModel();
      const mockPromise = core.runMockDiagnosis(m3, "normal", { delayMs: 200 });
      core.cancelMockDiagnosis(m3);
      out.cancel = {
        resolvedNull: (await mockPromise) === null,
        state: m3.diagnosis.state,
      };

      process.stdout.write(JSON.stringify(out));
    })().catch((err) => {
      console.error(err);
      process.exit(1);
    });
    """
)


@pytest.fixture(scope="module")
def board_report() -> dict:
    assert NODE is not None
    proc = subprocess.run(
        [NODE, "-e", _NODE_SCRIPT, str(CORE_JS)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@requires_node
def test_fleet_matches_vg_model_defaults(board_report: dict) -> None:
    normal = board_report["normal"]
    assert normal["scenario"] == "normal"
    assert normal["count"] == 24
    assert normal["selected"] == "s_01"
    assert normal["historyLen"] == 60
    assert normal["logCount"] >= 8  # seed logs, like vg_model_init


@requires_node
def test_warn_scenario_sets_alarm_and_counts(board_report: dict) -> None:
    warn = board_report["warn"]
    assert warn["alarm"] == {"title": "温度预警", "severity": "warn"}
    assert warn["primarySev"] == "warn"
    assert warn["counts"]["all"] == 24
    assert warn["counts"]["alarm"] >= 3


@requires_node
def test_diagnosis_context_shape_and_limits(board_report: dict) -> None:
    ctx = board_report["ctx"]
    assert ctx["keys"] == ["device", "event", "history", "rules"]
    assert ctx["eventTitle"] == "温度预警"
    assert ctx["eventSeverity"] == "warning"
    assert 1 <= ctx["historyLen"] <= 50
    assert ctx["historyEntryKeys"] == ["ts_ms", "values"]
    assert ctx["historyValuesKeys"] == ["s_01"]
    assert 1 <= ctx["rulesLen"] <= 20
    assert ctx["ruleKeys"] == ["expr", "message", "rule_id", "severity"]
    assert ctx["deviceName"] == "温度-01"
    assert ctx["deviceModel"]


@requires_node
def test_v2_result_mapping_and_fallback_flags(board_report: dict) -> None:
    mapped = board_report["mapped"]
    assert mapped["summaryLen"] == 128  # truncated like the board field
    assert mapped["risk"] == "medium"
    assert mapped["causes"] == 3
    assert mapped["actions"] == 0
    assert mapped["confidencePct"] == 87  # round(0.865 * 100)
    assert mapped["degraded"] is True
    assert mapped["fallbackReason"] == "provider unavailable"
    assert board_report["mappedInvalid"] is True


@requires_node
def test_mock_diagnosis_ai_down_fails_immediately(board_report: dict) -> None:
    assert board_report["aiDown"]["state"] == "error"
    assert board_report["aiDown"]["errorMsg"] == "MiMo 不可用"


@requires_node
def test_mock_diagnosis_cancel_resolves_promise(board_report: dict) -> None:
    cancelled = board_report["cancel"]
    assert cancelled["resolvedNull"] is True
    assert cancelled["state"] == "idle"


@requires_node
def test_build_request_payload_hash_matches_python(board_report: dict) -> None:
    req = board_report["request"]
    assert req["topicDeviceId"] == "dev01"
    assert len(req["payloadHash"]) == 64
    body = json.loads(req["payload"])
    assert body["payload_hash"] == req["payloadHash"]
    canonical_body = {k: v for k, v in body.items() if k != "payload_hash"}
    canonical = json.dumps(canonical_body, sort_keys=True, separators=(",", ":"))
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert req["payloadHash"] == expected
