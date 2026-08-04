"""Unit tests for application orchestration (no live MQTT)."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from ai_bridge.application.handle_request import HandleAiRequest
from ai_bridge.contracts.request import AiRequest
from ai_bridge.persistence.idempotency import InMemoryIdempotencyStore
from ai_bridge.providers.base import ProviderFailure, ProviderResult, ProviderSuccess
from ai_bridge.providers.stub import StubProvider
from ai_bridge.runtime.fallback import build_fallback_diagnosis


class RecordingPublisher:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict[str, Any]]] = []
        self.lock = threading.Lock()

    def __call__(self, topic: str, payload: dict[str, Any]) -> None:
        with self.lock:
            self.messages.append((topic, payload))

    def by_status(self, status: str) -> list[dict[str, Any]]:
        return [p for _, p in self.messages if p.get("status") == status]


class SlowProvider:
    def __init__(self, delay_s: float) -> None:
        self.delay_s = delay_s
        self.calls = 0

    def handle(self, request: AiRequest, *, deadline_s: float) -> ProviderResult:
        self.calls += 1
        time.sleep(self.delay_s)
        if self.delay_s >= deadline_s:
            return ProviderFailure(code="timeout", message="request deadline exceeded")
        return ProviderSuccess(
            result={
                "diagnosis_summary": "slow",
                "source": "stub",
                "advisory_only": True,
            }
        )


class CountingProvider:
    def __init__(self) -> None:
        self.calls = 0
        self._inner = StubProvider()

    def handle(self, request: AiRequest, *, deadline_s: float) -> ProviderResult:
        self.calls += 1
        return self._inner.handle(request, deadline_s=deadline_s)


class FailingProvider:
    def __init__(
        self,
        code: str = "provider_error",
        *,
        message: str = "boom",
        fallback_eligible: bool = True,
    ) -> None:
        self.calls = 0
        self.code = code
        self.message = message
        self.fallback_eligible = fallback_eligible

    def handle(self, request: AiRequest, *, deadline_s: float) -> ProviderResult:
        self.calls += 1
        return ProviderFailure(
            code=self.code,
            message=self.message,
            fallback_eligible=self.fallback_eligible,
        )


class SlowEligibleProvider:
    """Returns an eligible provider failure after burning the deadline."""

    def __init__(self, delay_s: float) -> None:
        self.delay_s = delay_s
        self.calls = 0

    def handle(self, request: AiRequest, *, deadline_s: float) -> ProviderResult:
        self.calls += 1
        time.sleep(self.delay_s)
        return ProviderFailure(
            code="provider_error",
            message="mimo provider error (HTTP 500)",
            fallback_eligible=True,
        )


def _payload(**overrides: object) -> bytes:
    data: dict[str, Any] = {
        "req_id": "r1",
        "device_id": "dev01",
        "created_ts_ms": 1_700_000_000_000,
        "type": "diagnosis",
        "payload_hash": "hash-1",
    }
    data.update(overrides)
    return json.dumps(data).encode("utf-8")


def _use_case(
    *,
    provider: Any | None = None,
    timeout_ms: int = 5_000,
    publish_processing: bool = True,
    fallback_builder: Any | None = build_fallback_diagnosis,
    fallback_enabled: bool = True,
) -> tuple[HandleAiRequest, RecordingPublisher, Any]:
    pub = RecordingPublisher()
    store = InMemoryIdempotencyStore()
    prov = provider if provider is not None else CountingProvider()
    uc = HandleAiRequest(
        store=store,
        provider=prov,
        publish=pub,
        request_timeout_ms=timeout_ms,
        publish_processing=publish_processing,
        fallback_builder=fallback_builder,
        fallback_enabled=fallback_enabled,
    )
    return uc, pub, prov


def test_valid_request_success_envelope() -> None:
    uc, pub, prov = _use_case(publish_processing=False)
    uc.handle_message("vg/dev01/ai/request", _payload())
    assert prov.calls == 1
    assert len(pub.messages) == 1
    topic, body = pub.messages[0]
    assert topic == "vg/dev01/ai/response/r1"
    assert body["req_id"] == "r1"
    assert body["device_id"] == "dev01"
    assert body["status"] == "success"
    assert body["error_code"] is None
    assert body["result"]["source"] == "stub"
    assert body["result"]["advisory_only"] is True
    assert body["result"]["risk_level"] == "low"
    assert body["result"]["possible_causes"] == []
    assert body["result"]["need_shutdown"] is False
    assert body["result"]["confidence"] == 0.0
    assert "received_ts_ms" in body and "bridge_ts_ms" in body


def test_validation_error_no_provider() -> None:
    uc, pub, prov = _use_case()
    bad = json.dumps(
        {
            "req_id": "r-bad",
            "device_id": "dev01",
            "created_ts_ms": 1,
            "type": "diagnosis",
            # missing payload_hash
        }
    ).encode("utf-8")
    uc.handle_message("vg/dev01/ai/request", bad)
    assert prov.calls == 0
    assert len(pub.messages) == 1
    body = pub.messages[0][1]
    assert body["status"] == "error"
    assert body["error_code"] == "validation_error"
    assert body["req_id"] == "r-bad"


def test_completed_duplicate_replays_without_second_provider_call() -> None:
    uc, pub, prov = _use_case(publish_processing=False)
    uc.handle_message("vg/dev01/ai/request", _payload())
    uc.handle_message("vg/dev01/ai/request", _payload())
    assert prov.calls == 1
    successes = pub.by_status("success")
    assert len(successes) == 2
    # Exact stored response replay (same status/result/timestamps).
    assert successes[0] == successes[1]
    assert successes[0]["result"]["source"] == "stub"
    assert successes[0]["result"]["risk_level"] == "low"


def test_processing_duplicate_no_second_provider() -> None:
    slow = SlowProvider(delay_s=0.2)
    store = InMemoryIdempotencyStore()
    pub = RecordingPublisher()
    uc = HandleAiRequest(
        store=store,
        provider=slow,
        publish=pub,
        request_timeout_ms=5_000,
        publish_processing=False,
    )

    def first() -> None:
        uc.handle_message("vg/dev01/ai/request", _payload())

    t = threading.Thread(target=first)
    t.start()
    time.sleep(0.05)
    uc.handle_message("vg/dev01/ai/request", _payload())
    t.join(timeout=2.0)
    assert slow.calls == 1
    processing = pub.by_status("processing")
    assert processing, "expected processing response for in-flight duplicate"
    assert all(p["error_code"] is None for p in processing)


def test_conflict_different_payload_hash() -> None:
    uc, pub, prov = _use_case(publish_processing=False)
    uc.handle_message("vg/dev01/ai/request", _payload(payload_hash="h1"))
    uc.handle_message("vg/dev01/ai/request", _payload(payload_hash="h2"))
    assert prov.calls == 1
    errors = pub.by_status("error")
    assert any(e["error_code"] == "conflict" for e in errors)


def test_timeout_path() -> None:
    slow = SlowProvider(delay_s=0.15)
    uc, pub, _ = _use_case(provider=slow, timeout_ms=50, publish_processing=False)
    uc.handle_message("vg/dev01/ai/request", _payload())
    errors = pub.by_status("error")
    assert len(errors) == 1
    assert errors[0]["error_code"] == "timeout"
    assert errors[0]["req_id"] == "r1"


def test_device_mismatch_validation() -> None:
    uc, pub, prov = _use_case()
    uc.handle_message("vg/other/ai/request", _payload())
    assert prov.calls == 0
    assert pub.messages[0][1]["error_code"] == "validation_error"


def test_fallback_on_eligible_provider_error() -> None:
    failing = FailingProvider(message="mimo provider error (HTTP 500)")
    uc, pub, _ = _use_case(provider=failing, publish_processing=False)
    uc.handle_message("vg/dev01/ai/request", _payload())
    assert failing.calls == 1
    successes = pub.by_status("success")
    assert len(successes) == 1
    body = successes[0]
    assert body["status"] == "success"
    assert body["result"]["source"] == "fallback"
    assert body["result"]["advisory_only"] is True
    assert body["result"]["fallback_reason"] == "mimo provider error (HTTP 500)"
    assert body["result"]["risk_level"] == "low"
    assert body["result"]["need_shutdown"] is False
    assert body["result"]["confidence"] == 0.0


def test_fallback_disabled_publishes_provider_error() -> None:
    failing = FailingProvider(message="mimo provider error (HTTP 500)")
    uc, pub, _ = _use_case(
        provider=failing,
        publish_processing=False,
        fallback_enabled=False,
    )
    uc.handle_message("vg/dev01/ai/request", _payload())
    errors = pub.by_status("error")
    assert len(errors) == 1
    assert errors[0]["error_code"] == "provider_error"
    assert errors[0]["result"] is None


def test_ineligible_failure_no_fallback() -> None:
    failing = FailingProvider(
        message="provider output failed schema validation",
        fallback_eligible=False,
    )
    uc, pub, _ = _use_case(provider=failing, publish_processing=False)
    uc.handle_message("vg/dev01/ai/request", _payload())
    errors = pub.by_status("error")
    assert len(errors) == 1
    assert errors[0]["error_code"] == "provider_error"
    assert errors[0]["result"] is None


def test_timeout_failure_no_fallback() -> None:
    failing = FailingProvider(
        code="timeout",
        message="request deadline exceeded",
        fallback_eligible=False,
    )
    uc, pub, _ = _use_case(provider=failing, publish_processing=False)
    uc.handle_message("vg/dev01/ai/request", _payload())
    errors = pub.by_status("error")
    assert len(errors) == 1
    assert errors[0]["error_code"] == "timeout"
    assert errors[0]["result"] is None


def test_fallback_budget_exhausted_no_fallback() -> None:
    slow = SlowEligibleProvider(delay_s=0.15)
    uc, pub, _ = _use_case(provider=slow, timeout_ms=50, publish_processing=False)
    uc.handle_message("vg/dev01/ai/request", _payload())
    errors = pub.by_status("error")
    assert len(errors) == 1
    assert errors[0]["error_code"] == "provider_error"
    assert len(pub.by_status("success")) == 0


def test_fallback_replay_is_exact() -> None:
    failing = FailingProvider(message="mimo provider error (HTTP 500)")
    uc, pub, _ = _use_case(provider=failing, publish_processing=False)
    uc.handle_message("vg/dev01/ai/request", _payload())
    uc.handle_message("vg/dev01/ai/request", _payload())
    assert failing.calls == 1
    successes = pub.by_status("success")
    assert len(successes) == 2
    assert successes[0] == successes[1]
    assert successes[0]["result"]["source"] == "fallback"


def test_fallback_builder_exception_publishes_internal_error() -> None:
    def bad_builder(_request: AiRequest, _reason: str) -> dict[str, Any]:
        raise RuntimeError("boom")

    failing = FailingProvider(message="mimo provider error (HTTP 500)")
    uc, pub, _ = _use_case(
        provider=failing,
        publish_processing=False,
        fallback_builder=bad_builder,
    )
    uc.handle_message("vg/dev01/ai/request", _payload())
    errors = pub.by_status("error")
    assert len(errors) == 1
    assert errors[0]["error_code"] == "internal_error"
