"""Unit tests for bounded diagnosis prompt assembly."""

from __future__ import annotations

import json
from typing import Any

from ai_bridge.contracts.request import AiRequest
from ai_bridge.runtime.prompt_builder import (
    MAX_USER_CONTENT_CHARS,
    build_diagnosis_messages,
    build_diagnosis_user_content,
)
from ai_bridge.runtime.skill_manager import DEFAULT_DIAGNOSIS_SKILL


def _request(*, raw: dict[str, Any] | None = None) -> AiRequest:
    data: dict[str, Any] = {
        "req_id": "r1",
        "device_id": "dev01",
        "created_ts_ms": 1,
        "type": "diagnosis",
        "payload_hash": "h1",
    }
    if raw:
        data.update(raw)
    return AiRequest(
        req_id="r1",
        device_id="dev01",
        created_ts_ms=1,
        type="diagnosis",
        payload_hash="h1",
        raw=data,
    )


def test_user_content_renders_context_sections() -> None:
    content = build_diagnosis_user_content(
        _request(
            raw={
                "context": {
                    "event": {"event_id": "evt_1", "severity": "warning"},
                    "history": [{"ts_ms": 1, "values": {"temperature": 72.8}}],
                    "rules": [{"rule_id": "r1", "expr": "temperature > 70"}],
                    "device": {"name": "Motor Temp"},
                }
            }
        )
    )
    data = json.loads(content)
    assert data["device_id"] == "dev01"
    assert data["req_id"] == "r1"
    assert data["type"] == "diagnosis"
    assert data["context"]["event"]["event_id"] == "evt_1"
    assert data["context"]["history"][0]["values"]["temperature"] == 72.8
    assert data["context"]["rules"][0]["rule_id"] == "r1"
    assert data["context"]["device"]["name"] == "Motor Temp"
    assert "context_notes" not in data


def test_user_content_marks_all_sections_missing() -> None:
    data = json.loads(build_diagnosis_user_content(_request()))
    assert data["context"] == {}
    assert data["context_notes"] == [
        "event missing",
        "history missing",
        "rules missing",
        "device missing",
    ]


def test_user_content_marks_partial_missing() -> None:
    data = json.loads(
        build_diagnosis_user_content(
            _request(raw={"context": {"event": {"severity": "low"}}})
        )
    )
    assert data["context"] == {"event": {"severity": "low"}}
    assert data["context_notes"] == [
        "history missing",
        "rules missing",
        "device missing",
    ]


def test_history_truncated_to_50_items() -> None:
    raw = {
        "context": {
            "history": [{"ts_ms": i, "values": {"v": i}} for i in range(70)]
        }
    }
    data = json.loads(build_diagnosis_user_content(_request(raw=raw)))
    assert len(data["context"]["history"]) == 50


def test_rules_truncated_to_20_items() -> None:
    raw = {"context": {"rules": [{"rule_id": f"r{i}"} for i in range(30)]}}
    data = json.loads(build_diagnosis_user_content(_request(raw=raw)))
    assert len(data["context"]["rules"]) == 20


def test_non_object_entries_dropped() -> None:
    raw = {
        "context": {
            "history": [{"ts_ms": 1}, "bad", 42, {"ts_ms": 2}],
            "rules": ["bad", {"rule_id": "r1"}],
        }
    }
    data = json.loads(build_diagnosis_user_content(_request(raw=raw)))
    assert data["context"]["history"] == [
        {"ts_ms": 1, "__missing__": ["values"]},
        {"ts_ms": 2, "__missing__": ["values"]},
    ]
    assert data["context"]["rules"] == [{"rule_id": "r1"}]


def test_history_entries_missing_ts_ms_or_values_marked() -> None:
    raw = {
        "context": {
            "history": [
                {"ts_ms": 1},
                {"values": {"temperature": 72.8}},
                {"ts_ms": 2, "values": {}},
            ]
        }
    }
    data = json.loads(build_diagnosis_user_content(_request(raw=raw)))
    history = data["context"]["history"]
    assert history[0] == {"ts_ms": 1, "__missing__": ["values"]}
    assert history[1] == {
        "values": {"temperature": 72.8},
        "__missing__": ["ts_ms"],
    }
    assert history[2] == {"ts_ms": 2, "values": {}}


def test_oversized_event_truncated_with_marker() -> None:
    raw = {
        "context": {
            "event": {"title": "x" * 9000, "severity": "high"},
        }
    }
    data = json.loads(build_diagnosis_user_content(_request(raw=raw)))
    assert data["context"]["event"]["__truncated__"] == "...[truncated]"


def test_oversized_history_truncated_with_marker() -> None:
    raw = {
        "context": {
            "history": [
                {"ts_ms": i, "values": {"v": "y" * 500}} for i in range(40)
            ]
        }
    }
    data = json.loads(build_diagnosis_user_content(_request(raw=raw)))
    assert data["context"]["history"][-1] == "...[truncated]"


def test_user_content_total_length_bounded() -> None:
    raw = {
        "context": {
            "history": [
                {"ts_ms": i, "values": {"v": "z" * 1000}} for i in range(60)
            ],
            "rules": [{"expr": "q" * 1000} for _ in range(30)],
            "event": {"title": "p" * 5000},
            "device": {"description": "d" * 3000},
        }
    }
    content = build_diagnosis_user_content(_request(raw=raw))
    assert len(content) <= MAX_USER_CONTENT_CHARS
    json.loads(content)  # must remain valid JSON


def test_user_content_bounded_with_long_identity_fields() -> None:
    raw: dict[str, Any] = {
        "req_id": "r1",
        "device_id": "dev01",
        "created_ts_ms": 1,
        "type": "diagnosis",
        "payload_hash": "h1",
        "context": {
            "event": {"title": "p" * 5000},
            "device": {"description": "d" * 3000},
        },
    }
    request = AiRequest(
        req_id="r" + "x" * 5000,
        device_id="dev" + "y" * 5000,
        created_ts_ms=1,
        type="diagnosis",
        payload_hash="h1",
        raw=raw,
    )
    content = build_diagnosis_user_content(request)
    assert len(content) <= MAX_USER_CONTENT_CHARS
    parsed = json.loads(content)  # must remain valid JSON
    assert parsed["device_id"].endswith("...[truncated]")
    assert parsed["req_id"].endswith("...[truncated]")


def test_messages_system_includes_skill_and_schema_instructions() -> None:
    messages = build_diagnosis_messages(_request(), DEFAULT_DIAGNOSIS_SKILL)
    assert [m["role"] for m in messages] == ["system", "user"]
    system = messages[0]["content"]
    assert "VelaGuard industrial fault diagnosis" in system
    assert "Simplified Chinese" in system
    assert "diagnosis_summary" in system
    assert "device IDs" in system
    assert "need_shutdown" in system
    assert "JSON object" in system
    user = json.loads(messages[1]["content"])
    assert user["context"] == {}


def test_language_rule_is_added_to_custom_skill() -> None:
    messages = build_diagnosis_messages(_request(), "Custom diagnosis role")
    system = messages[0]["content"]
    assert system.startswith("Custom diagnosis role")
    assert "Simplified Chinese" in system
    assert "recommended_actions" in system
