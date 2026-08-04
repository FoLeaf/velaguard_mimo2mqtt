"""Contract parity between the debug console / board simulator and Python canonical JSON.

PRD AC2 requires ``debug-console/app.js`` to reproduce the bridge's
``payload_hash`` algorithm byte-for-byte:

    sha256(json.dumps(body, sort_keys=True, separators=(",", ":")))

``board-sim/board-core.js`` carries the same canonical helpers (copied with
attribution so the simulator stays fully independent); these tests execute
both browser modules under node.js and compare them with the Python
reference. They skip when node.js is not installed; the developer tooling is
not a Python runtime dependency.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from ai_bridge.cli.synthetic_publisher import build_request

NODE = shutil.which("node")
_REPO_ROOT = Path(__file__).resolve().parents[2]
JS_MODULES = [
    pytest.param(_REPO_ROOT / "debug-console" / "app.js", id="debug-console"),
    pytest.param(_REPO_ROOT / "board-sim" / "board-core.js", id="board-sim"),
]

requires_node = pytest.mark.skipif(
    NODE is None,
    reason="node.js is required to execute the debug-console hash parity check",
)

_NODE_SCRIPT = textwrap.dedent(
    """\
    const app = require(process.argv[1]);
    let input = "";
    process.stdin.on("data", (d) => { input += d; });
    process.stdin.on("end", async () => {
      const fixtures = JSON.parse(input);
      const out = {};
      for (const [name, text] of fixtures) {
        const parsed = app.parseJsonPreservingInts(text);
        const canonical = app.pyDumps(parsed);
        out[name] = {
          canonical,
          sync: app.sha256Sync(new TextEncoder().encode(canonical)),
          subtle: await app.computePayloadHash(parsed),
        };
      }
      process.stdout.write(JSON.stringify(out));
    });
    """
)

_FIXTURES: list[tuple[str, str]] = [
    (
        "basic",
        json.dumps(
            {
                "req_id": "r-123",
                "device_id": "dev01",
                "created_ts_ms": 1782450000000,
                "type": "diagnosis",
                "note": "synthetic publisher",
            },
            ensure_ascii=False,
        ),
    ),
    (
        "nested_chinese",
        json.dumps(
            {
                "req_id": "r-temp",
                "device_id": "dev01",
                "created_ts_ms": 1782450000000,
                "type": "diagnosis",
                "note": "synthetic publisher",
                "context": {
                    "event": {
                        "event_id": "evt_temp_over",
                        "severity": "warning",
                        "title": "温度持续超限",
                        "current_value": 82.4,
                        "ts_ms": 1782450000000,
                    },
                    "history": [
                        {"ts_ms": 1782448800000, "values": {"temperature": 75.1, "fan_rpm": 2800}},
                        {"ts_ms": 1782449400000, "values": {"temperature": 78.6, "fan_rpm": 2750}},
                    ],
                    "rules": [{"rule_id": "r1", "expr": "temperature > 75"}],
                    "device": {"name": "主轴电机", "model": "RS485-TH-1"},
                },
            },
            ensure_ascii=False,
        ),
    ),
    (
        "unicode_escapes",
        json.dumps(
            {
                "s": "温度",
                "emoji": "😀",
                "line": "a\nb",
                "ctrl": "\u0000\u001f",
                "del": "\u007f",
                "ls": "\u2028",
                "ps": "\u2029",
            },
            ensure_ascii=False,
        ),
    ),
    (
        "ints_floats",
        (
            '{"a":1,"b":1.0,"c":-1.0,"d":0,"e":0.0,"f":-0.0,"g":1e0,"h":1.5e3,'
            '"i":1e16,"j":1e15,"k":0.0001,"l":0.00001,"m":1e-4,"n":1e-5,'
            '"o":1e100,"p":1e-100,"q":2.2250738585072014e-308,"r":5e-324,'
            '"s":1.7976931348623157e308,"t":123456789.123456789,'
            '"u":10000000000000010.0,"v":9999999999999999.0,"w":1.2345678901234568e18}'
        ),
    ),
    (
        "big_ints",
        '{"big":9007199254740993,"huge":123456789012345678901234567890,'
        '"neg":-9223372036854775808,"small":-1}',
    ),
    (
        "key_order",
        json.dumps(
            {
                "2": "b",
                "10": "c",
                "1": "a",
                "é": "e-acute",
                "e": "plain-e",
                "温度": "temp",
                "a": "a",
                "😀": "smile",
            },
            ensure_ascii=False,
        ),
    ),
    ("quotes", '{"q":"a\\"b\\\\c","slash":"\\\\\\\\"}'),
    ("empty", "{}"),
    ("mixed", '{"a":[],"b":{},"c":null,"d":true,"e":false}'),
    ("nested_mixed", '{"list":[1,1.5,{"x":2,"y":2.0},[null,true,"s"]],"obj":{"z":-0.0,"w":1e-7}}'),
    ("dup_keys", '{"a":1,"a":2}'),
    ("exponent_neg", '{"x":1.5e-5,"y":-1e-05,"z":6.02e23}'),
    ("neg_zero_float", '{"nz":-0.0}'),
]


def _python_hash(text: str) -> str:
    canonical = json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _python_canonical(text: str) -> str:
    return json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))


@pytest.fixture(scope="module", params=JS_MODULES)
def js_hashes(request) -> dict[str, dict[str, str]]:
    assert NODE is not None
    app_js = request.param
    proc = subprocess.run(
        [NODE, "-e", _NODE_SCRIPT, str(app_js)],
        input=json.dumps(_FIXTURES),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@requires_node
def test_payload_hash_matches_python_canonical(
    js_hashes: dict[str, dict[str, str]],
) -> None:
    for name, text in _FIXTURES:
        expected = _python_hash(text)
        assert js_hashes[name]["sync"] == expected, name
        assert js_hashes[name]["subtle"] == expected, name


@requires_node
def test_canonical_form_matches_python(
    js_hashes: dict[str, dict[str, str]],
) -> None:
    for name, text in _FIXTURES:
        assert js_hashes[name]["canonical"] == _python_canonical(text), name


def test_build_request_round_trip_matches_exported_body() -> None:
    """README export example: re-importing the exported body reproduces the hash."""
    device_id = "dev01"
    exported = {
        "req_id": "r1",
        "device_id": device_id,
        "created_ts_ms": 1782450000000,
        "type": "diagnosis",
        "note": "synthetic publisher",
        "context": {"event": {"severity": "warning", "title": "温度"}},
    }
    body = {k: v for k, v in exported.items() if k != "payload_hash"}
    built = build_request(device_id=device_id, extra=body)
    assert built["payload_hash"] == _python_hash(json.dumps(body, ensure_ascii=False))
