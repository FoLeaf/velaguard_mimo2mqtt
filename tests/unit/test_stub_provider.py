"""Unit tests for StubProvider."""

from __future__ import annotations

from ai_bridge.contracts.request import AiRequest
from ai_bridge.providers.base import ProviderFailure, ProviderSuccess, build_provider
from ai_bridge.providers.stub import StubProvider


def _request() -> AiRequest:
    return AiRequest(
        req_id="r1",
        device_id="dev01",
        created_ts_ms=1,
        type="diagnosis",
        payload_hash="h1",
        raw={},
    )


def test_stub_success_shape() -> None:
    provider = StubProvider()
    result = provider.handle(_request(), deadline_s=5.0)
    assert isinstance(result, ProviderSuccess)
    assert result.result["source"] == "stub"
    assert result.result["advisory_only"] is True
    assert "diagnosis_summary" in result.result
    assert result.result["risk_level"] == "low"
    assert result.result["possible_causes"] == []
    assert result.result["recommended_actions"] == [
        "Retry with PROVIDER=mimo for live diagnosis"
    ]
    assert result.result["need_shutdown"] is False
    assert result.result["confidence"] == 0.0


def test_stub_timeout_when_delay_exceeds_deadline() -> None:
    provider = StubProvider(delay_ms=200)
    result = provider.handle(_request(), deadline_s=0.05)
    assert isinstance(result, ProviderFailure)
    assert result.code == "timeout"


def test_build_provider_stub() -> None:
    provider = build_provider("stub")
    assert isinstance(provider.handle(_request(), deadline_s=1.0), ProviderSuccess)
