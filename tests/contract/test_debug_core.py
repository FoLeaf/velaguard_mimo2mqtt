"""Contract checks for the unified debug Mock core."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

NODE = shutil.which("node")
DEBUG_JS = Path(__file__).resolve().parents[2] / "board-sim" / "debug-core.js"
requires_node = pytest.mark.skipif(NODE is None, reason="node.js is required for debug-core contract checks")

_NODE_SCRIPT = textwrap.dedent(
    """
    const debug = require(process.argv[1]);
    const request = { req_id: "r-debug", device_id: "dev01", context: { event: { severity: "warning" } } };
    const out = {};
    out.scenarios = debug.SCENARIOS.map((item) => ({ id: item.id, sendsProcessing: item.sendsProcessing }));
    out.success = debug.buildTerminalEnvelope("mimo_success", request, 1);
    out.fallback = debug.buildTerminalEnvelope("fallback", request, 1);
    out.providerError = debug.buildTerminalEnvelope("schema_invalid", request, 1);
    out.timeout = debug.buildTerminalEnvelope("timeout", request, 1);
    out.validation = debug.buildTerminalEnvelope("validation_error", request, 1);
    out.conflict = debug.buildTerminalEnvelope("conflict", request, 1);
    process.stdout.write(JSON.stringify(out));
    """
)


@pytest.fixture(scope="module")
def debug_report() -> dict:
    assert NODE is not None
    proc = subprocess.run(
        [NODE, "-e", _NODE_SCRIPT, str(DEBUG_JS)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@requires_node
def test_debug_scenarios_preserve_processing_contract(debug_report: dict) -> None:
    scenarios = {item["id"]: item["sendsProcessing"] for item in debug_report["scenarios"]}
    assert len(scenarios) == 6
    assert scenarios["mimo_success"] is True
    assert scenarios["fallback"] is True
    assert scenarios["schema_invalid"] is True
    assert scenarios["timeout"] is True
    assert scenarios["validation_error"] is False
    assert scenarios["conflict"] is False


@requires_node
def test_debug_terminal_envelopes_preserve_status_and_sources(debug_report: dict) -> None:
    assert debug_report["success"]["status"] == "success"
    assert debug_report["success"]["result"]["source"] == "mimo"
    assert debug_report["fallback"]["status"] == "success"
    assert debug_report["fallback"]["result"]["source"] == "fallback"
    assert debug_report["fallback"]["result"]["advisory_only"] is True
    assert debug_report["providerError"]["error_code"] == "provider_error"
    assert debug_report["timeout"]["error_code"] == "timeout"
    assert debug_report["validation"]["error_code"] == "validation_error"
    assert debug_report["conflict"]["error_code"] == "conflict"
