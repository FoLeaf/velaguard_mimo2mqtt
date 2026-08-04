"""Unit tests for MiMoProvider against a local OpenAI-compatible stub server.

No live MiMo API key or network access is required.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from ai_bridge.configuration.settings import Settings
from ai_bridge.contracts.request import AiRequest
from ai_bridge.providers.base import ProviderFailure, ProviderSuccess, build_provider
from ai_bridge.providers.mimo import MiMoProvider
from ai_bridge.providers.schema import (
    SchemaValidationError,
    validate_diagnosis_result,
)
from ai_bridge.runtime.prompt_builder import (
    MAX_USER_CONTENT_CHARS,
    build_diagnosis_user_content,
)
from tests.helpers.mimo_stub_server import (
    MiMoStubServer,
    chat_completion_response_missing_content,
)

TEST_KEY = "test-mimo-key-not-a-real-secret"


def _request(**overrides: Any) -> AiRequest:
    raw: dict[str, Any] = {
        "req_id": "r1",
        "device_id": "dev01",
        "created_ts_ms": 1_700_000_000_000,
        "type": "diagnosis",
        "payload_hash": "h1",
        "alarm_code": "E-101",
        "sensor": {"a": 1},
    }
    raw.update(overrides)
    return AiRequest(
        req_id=str(raw["req_id"]),
        device_id=str(raw["device_id"]),
        created_ts_ms=int(raw["created_ts_ms"]),
        type=str(raw["type"]),
        payload_hash=str(raw["payload_hash"]),
        raw=dict(raw),
    )


def _provider(base_url: str, **kwargs: Any) -> MiMoProvider:
    return MiMoProvider(
        base_url=base_url,
        model="mimo-chat",
        api_key=TEST_KEY,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# request building / wire shape
# ---------------------------------------------------------------------------


def test_requests_chat_completions_with_expected_wire_shape() -> None:
    with MiMoStubServer() as server:
        provider = _provider(server.base_url)
        result = provider.handle(_request(), deadline_s=10.0)
        assert isinstance(result, ProviderSuccess)

    assert len(server.requests) == 1
    req = server.requests[0]
    assert req["path"] == "/chat/completions"
    assert req["headers"]["Authorization"] == f"Bearer {TEST_KEY}"
    assert req["headers"]["Content-Type"] == "application/json"
    body = req["body"]
    assert body["model"] == "mimo-chat"
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user"]
    assert "diagnosis_summary" in body["messages"][0]["content"]
    user = json.loads(body["messages"][1]["content"])
    assert user["device_id"] == "dev01"
    assert user["req_id"] == "r1"
    assert user["type"] == "diagnosis"


def test_user_content_truncates_oversized_request_body() -> None:
    huge = {"x": "a" * 10_000}
    raw = _request()
    raw = AiRequest(
        req_id=raw.req_id,
        device_id=raw.device_id,
        created_ts_ms=raw.created_ts_ms,
        type=raw.type,
        payload_hash=raw.payload_hash,
        raw={**raw.raw, **huge},
    )
    with MiMoStubServer() as server:
        provider = _provider(server.base_url)
        result = provider.handle(raw, deadline_s=10.0)
        assert isinstance(result, ProviderSuccess)
    user = json.loads(server.requests[0]["body"]["messages"][1]["content"])
    assert user["request"].endswith("...[truncated]")
    assert len(user["request"]) <= 2048 + len("...[truncated]")


def test_success_normalizes_and_adds_source() -> None:
    content = {
        "diagnosis_summary": "  Bearing wear suspected.  ",
        "risk_level": "medium",
        "possible_causes": ["bearing wear"],
        "recommended_actions": ["inspect bearing"],
        "need_shutdown": False,
        "reasons": ["vibration high"],
        "recommendations": ["inspect bearing"],
        "confidence": 0.9,
        "extra_future_field": "kept",
    }
    with MiMoStubServer() as server:
        server.script.append({"content": json.dumps(content)})
        provider = _provider(server.base_url)
        result = provider.handle(_request(), deadline_s=10.0)
    assert isinstance(result, ProviderSuccess)
    assert result.result["diagnosis_summary"] == "Bearing wear suspected."
    assert result.result["risk_level"] == "medium"
    assert result.result["possible_causes"] == ["bearing wear"]
    assert result.result["need_shutdown"] is False
    assert result.result["source"] == "mimo"
    assert result.result["reasons"] == ["vibration high"]
    assert result.result["extra_future_field"] == "kept"


# ---------------------------------------------------------------------------
# schema validation matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "not-json-at-all",
        "[]",  # JSON but not an object
        "null",
    ],
)
def test_invalid_json_is_provider_error(content: str) -> None:
    with MiMoStubServer() as server:
        server.script.append({"content": content})
        provider = _provider(server.base_url)
        result = provider.handle(_request(), deadline_s=10.0)
    assert isinstance(result, ProviderFailure)
    assert result.code == "provider_error"
    assert result.fallback_eligible is False


@pytest.mark.parametrize(
    "payload",
    [
        {"reasons": ["x"]},  # missing summary
        {"diagnosis_summary": "   "},  # blank summary
        {"diagnosis_summary": 42},  # wrong type
        {"diagnosis_summary": "", "reasons": []},
    ],
)
def test_missing_or_invalid_summary_is_provider_error(payload: dict) -> None:
    with MiMoStubServer() as server:
        server.script.append({"content": json.dumps(payload)})
        provider = _provider(server.base_url)
        result = provider.handle(_request(), deadline_s=10.0)
    assert isinstance(result, ProviderFailure)
    assert result.code == "provider_error"


@pytest.mark.parametrize(
    "payload",
    [
        {"diagnosis_summary": "ok", "reasons": "not-a-list"},
        {"diagnosis_summary": "ok", "reasons": [1, 2]},
        {"diagnosis_summary": "ok", "recommendations": [True]},
        {"diagnosis_summary": "ok", "confidence": "high"},
        {"diagnosis_summary": "ok", "confidence": True},
        {"diagnosis_summary": "ok", "confidence": 1.5},
        {"diagnosis_summary": "ok", "confidence": -0.1},
        {"diagnosis_summary": "ok", "confidence": 10**1000},
    ],
)
def test_bad_optional_types_are_provider_error(payload: dict) -> None:
    with MiMoStubServer() as server:
        server.script.append({"content": json.dumps(payload)})
        provider = _provider(server.base_url)
        result = provider.handle(_request(), deadline_s=10.0)
    assert isinstance(result, ProviderFailure)
    assert result.code == "provider_error"
    assert result.fallback_eligible is False


@pytest.mark.parametrize(
    "payload",
    [
        {"diagnosis_summary": "ok", "risk_level": "low",
         "possible_causes": [], "recommended_actions": [], "need_shutdown": False},
        {"diagnosis_summary": "ok", "risk_level": "medium",
         "possible_causes": [], "recommended_actions": [],
         "need_shutdown": False, "reasons": [], "recommendations": []},
        {"diagnosis_summary": "ok", "risk_level": "high",
         "possible_causes": ["a"], "recommended_actions": ["b"],
         "need_shutdown": True, "confidence": 0},
        {"diagnosis_summary": "ok", "risk_level": "low",
         "possible_causes": [], "recommended_actions": [],
         "need_shutdown": False, "confidence": 1.0},
        {"diagnosis_summary": "ok", "risk_level": "low",
         "possible_causes": ["a"], "recommended_actions": ["b"],
         "need_shutdown": False, "reasons": ["a"], "confidence": 0.5},
    ],
)
def test_valid_schema_variants_succeed(payload: dict) -> None:
    with MiMoStubServer() as server:
        server.script.append({"content": json.dumps(payload)})
        provider = _provider(server.base_url)
        result = provider.handle(_request(), deadline_s=10.0)
    assert isinstance(result, ProviderSuccess)
    assert result.result["diagnosis_summary"] == "ok"
    assert result.result["source"] == "mimo"


@pytest.mark.parametrize(
    "payload",
    [
        {"diagnosis_summary": "ok", "possible_causes": [],
         "recommended_actions": [], "need_shutdown": False},  # missing risk_level
        {"diagnosis_summary": "ok", "risk_level": "extreme",
         "possible_causes": [], "recommended_actions": [], "need_shutdown": False},
        {"diagnosis_summary": "ok", "risk_level": "low",
         "need_shutdown": False},  # missing possible_causes
        {"diagnosis_summary": "ok", "risk_level": "low",
         "possible_causes": "not-a-list", "recommended_actions": [],
         "need_shutdown": False},
        {"diagnosis_summary": "ok", "risk_level": "low",
         "possible_causes": [1], "recommended_actions": [], "need_shutdown": False},
        {"diagnosis_summary": "ok", "risk_level": "low",
         "possible_causes": [], "recommended_actions": [True],
         "need_shutdown": False},
        {"diagnosis_summary": "ok", "risk_level": "low",
         "possible_causes": [], "recommended_actions": [], "need_shutdown": 1},
        {"diagnosis_summary": "ok", "risk_level": "low",
         "possible_causes": [], "recommended_actions": [], "need_shutdown": "yes"},
    ],
)
def test_v2_required_field_errors_are_provider_error(payload: dict) -> None:
    with MiMoStubServer() as server:
        server.script.append({"content": json.dumps(payload)})
        provider = _provider(server.base_url)
        result = provider.handle(_request(), deadline_s=10.0)
    assert isinstance(result, ProviderFailure)
    assert result.code == "provider_error"
    assert result.fallback_eligible is False


def test_missing_message_content_is_provider_error() -> None:
    with MiMoStubServer() as server:
        server.script.append({"content": chat_completion_response_missing_content()})
        provider = _provider(server.base_url)
        result = provider.handle(_request(), deadline_s=10.0)
    assert isinstance(result, ProviderFailure)
    assert result.code == "provider_error"


# ---------------------------------------------------------------------------
# HTTP error classification / retries
# ---------------------------------------------------------------------------


def test_401_no_retry_and_provider_error() -> None:
    with MiMoStubServer() as server:
        server.script.append({"status": 401, "body": {"error": "unauthorized"}})
        provider = _provider(server.base_url)
        result = provider.handle(_request(), deadline_s=10.0)
    assert isinstance(result, ProviderFailure)
    assert result.code == "provider_error"
    assert result.fallback_eligible is True
    assert len(server.requests) == 1  # no retry


def test_400_no_retry_and_provider_error() -> None:
    with MiMoStubServer() as server:
        server.script.append({"status": 400, "body": {"error": "bad request"}})
        provider = _provider(server.base_url)
        result = provider.handle(_request(), deadline_s=10.0)
    assert isinstance(result, ProviderFailure)
    assert result.code == "provider_error"
    assert result.fallback_eligible is True
    assert len(server.requests) == 1


def test_429_then_success_retries() -> None:
    with MiMoStubServer() as server:
        server.script.append({"status": 429, "body": {"error": "rate limited"}})
        server.script.append(
            {
                "content": json.dumps(
                    {
                        "diagnosis_summary": "ok after retry",
                        "risk_level": "low",
                        "possible_causes": [],
                        "recommended_actions": [],
                        "need_shutdown": False,
                    }
                )
            }
        )
        provider = _provider(server.base_url)
        result = provider.handle(_request(), deadline_s=10.0)
    assert isinstance(result, ProviderSuccess)
    assert result.result["diagnosis_summary"] == "ok after retry"
    assert len(server.requests) == 2


def test_500_exhausted_retries_is_provider_error() -> None:
    with MiMoStubServer() as server:
        server.script.append({"status": 500, "body": {"error": "boom"}})
        server.script.append({"status": 500, "body": {"error": "boom"}})
        server.script.append({"status": 500, "body": {"error": "boom"}})
        provider = _provider(server.base_url, max_retries=2)
        result = provider.handle(_request(), deadline_s=10.0)
    assert isinstance(result, ProviderFailure)
    assert result.code == "provider_error"
    assert result.fallback_eligible is True
    assert len(server.requests) == 3  # 1 initial + 2 retries


def test_no_retry_when_max_retries_zero() -> None:
    with MiMoStubServer() as server:
        server.script.append({"status": 503, "body": {"error": "unavailable"}})
        provider = _provider(server.base_url, max_retries=0)
        result = provider.handle(_request(), deadline_s=10.0)
    assert isinstance(result, ProviderFailure)
    assert result.code == "provider_error"
    assert result.fallback_eligible is True
    assert len(server.requests) == 1


def test_final_attempt_never_sleeps_past_deadline() -> None:
    # A definitive 429 with no retry budget must be classified as
    # provider_error, not timeout. The final attempt must not sleep a backoff
    # that burns the remaining deadline (regression: it used to consume the
    # whole budget and flip the classification to `timeout`).
    with MiMoStubServer() as server:
        server.script.append({"status": 429, "body": {"error": "rate limited"}})
        provider = _provider(
            server.base_url,
            max_retries=0,
            retry_backoff_ms=50_000,
        )
        result = provider.handle(_request(), deadline_s=0.5)
    assert isinstance(result, ProviderFailure)
    assert result.code == "provider_error"
    assert result.fallback_eligible is True
    assert len(server.requests) == 1


# ---------------------------------------------------------------------------
# timeout path
# ---------------------------------------------------------------------------


def test_slow_response_times_out_with_code_timeout() -> None:
    with MiMoStubServer() as server:
        # Every retry attempt also sleeps longer than its per-attempt timeout so
        # the deadline is breached regardless of clock skew.
        for _ in range(3):
            server.script.append({"sleep_ms": 600, "content": "never inspected"})
        provider = _provider(
            server.base_url,
            http_timeout_ms=400,
            max_retries=1,
        )
        # The attempt timeout consumes the whole deadline; the follow-up
        # attempt immediately observes the deadline breach.
        result = provider.handle(_request(), deadline_s=0.3)
    assert isinstance(result, ProviderFailure)
    assert result.code == "timeout"
    assert result.fallback_eligible is False


def test_zero_deadline_is_immediate_timeout() -> None:
    provider = _provider("http://127.0.0.1:1")  # would fail to connect if called
    result = provider.handle(_request(), deadline_s=0.0)
    assert isinstance(result, ProviderFailure)
    assert result.code == "timeout"
    assert result.fallback_eligible is False


def test_network_error_retries_then_provider_error() -> None:
    # Port 1 refuses connections on 127.0.0.1; connection errors are transient.
    provider = _provider("http://127.0.0.1:1", http_timeout_ms=200, max_retries=1)
    result = provider.handle(_request(), deadline_s=10.0)
    assert isinstance(result, ProviderFailure)
    assert result.code == "provider_error"
    assert result.fallback_eligible is True


# ---------------------------------------------------------------------------
# injected prompt builder (skill runtime)
# ---------------------------------------------------------------------------


def test_injected_user_content_contains_normalized_context() -> None:
    req = _request(
        context={
            "event": {"event_id": "evt_1", "severity": "critical"},
            "history": [{"ts_ms": 1, "values": {"temperature": 90}}],
            "rules": [{"rule_id": "r1", "expr": "temperature > 70"}],
            "device": {"name": "Motor Temp"},
        }
    )
    with MiMoStubServer() as server:
        provider = _provider(
            server.base_url,
            user_content_builder=build_diagnosis_user_content,
        )
        result = provider.handle(req, deadline_s=10.0)
        assert isinstance(result, ProviderSuccess)

    user = json.loads(server.requests[0]["body"]["messages"][1]["content"])
    assert user["context"]["event"]["severity"] == "critical"
    assert user["context"]["history"][0]["values"]["temperature"] == 90
    assert user["context"]["rules"][0]["rule_id"] == "r1"
    assert user["context"]["device"]["name"] == "Motor Temp"
    assert "context_notes" not in user


def test_injected_user_content_is_bounded_and_contains_no_api_key() -> None:
    huge_history = [
        {"ts_ms": i, "values": {"v": "x" * 500}} for i in range(60)
    ]
    req = _request(context={"history": huge_history})
    with MiMoStubServer() as server:
        provider = _provider(
            server.base_url,
            user_content_builder=build_diagnosis_user_content,
        )
        result = provider.handle(req, deadline_s=10.0)
        assert isinstance(result, ProviderSuccess)

    body = server.requests[0]["body"]
    assert len(body["messages"][1]["content"]) <= MAX_USER_CONTENT_CHARS
    assert TEST_KEY not in json.dumps(body["messages"])


# ---------------------------------------------------------------------------
# startup / config
# ---------------------------------------------------------------------------


def test_build_provider_mimo_without_key_raises() -> None:
    settings = Settings(
        PROVIDER="mimo",
        MIMO_BASE_URL="http://127.0.0.1:1",
        MIMO_MODEL="mimo-chat",
        MIMO_API_KEY=None,
    )
    with pytest.raises(ValueError, match="MIMO_API_KEY"):
        build_provider("mimo", settings=settings)


def test_build_provider_mimo_with_key_builds_provider() -> None:
    settings = Settings(
        PROVIDER="mimo",
        MIMO_BASE_URL="http://127.0.0.1:1",
        MIMO_MODEL="mimo-chat",
        MIMO_API_KEY=TEST_KEY,
    )
    provider = build_provider("mimo", settings=settings)
    assert isinstance(provider, MiMoProvider)


def test_build_provider_mimo_blank_key_treated_as_unset() -> None:
    settings = Settings(
        PROVIDER="mimo",
        MIMO_BASE_URL="http://127.0.0.1:1",
        MIMO_MODEL="mimo-chat",
        MIMO_API_KEY="   ",
    )
    assert settings.mimo_api_key is None
    with pytest.raises(ValueError, match="MIMO_API_KEY"):
        build_provider("mimo", settings=settings)


def test_build_provider_unknown_name_raises() -> None:
    with pytest.raises(ValueError, match="unknown provider"):
        build_provider("nope")


# ---------------------------------------------------------------------------
# schema helper direct tests
# ---------------------------------------------------------------------------


def test_schema_passes_through_unknown_keys() -> None:
    data = {
        "diagnosis_summary": "ok",
        "risk_level": "low",
        "possible_causes": [],
        "recommended_actions": [],
        "need_shutdown": False,
        "future_meta": {"a": 1},
    }
    normalized = validate_diagnosis_result(data)
    assert normalized["future_meta"] == {"a": 1}


@pytest.mark.parametrize(
    "data",
    [
        "a string",
        42,
        None,
        ["not", "a", "dict"],
    ],
)
def test_schema_rejects_non_object(data: object) -> None:
    with pytest.raises(SchemaValidationError):
        validate_diagnosis_result(data)


def test_schema_rejects_bool_confidence() -> None:
    with pytest.raises(SchemaValidationError):
        validate_diagnosis_result({"diagnosis_summary": "ok", "confidence": True})


def test_error_message_has_no_provider_content() -> None:
    payload = {"diagnosis_summary": "nope", "confidence": "garbage"}
    with MiMoStubServer() as server:
        server.script.append({"content": json.dumps(payload)})
        provider = _provider(server.base_url)
        result = provider.handle(_request(), deadline_s=10.0)
    assert isinstance(result, ProviderFailure)
    assert "garbage" not in result.message
    assert result.message == "provider output failed schema validation"
