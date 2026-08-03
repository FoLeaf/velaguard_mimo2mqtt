"""Provider protocol and result types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ai_bridge.contracts.request import AiRequest


@dataclass(frozen=True, slots=True)
class ProviderSuccess:
    result: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    code: str
    message: str


ProviderResult = ProviderSuccess | ProviderFailure


class Provider(Protocol):
    """External AI provider seam. No MQTT knowledge."""

    def handle(self, request: AiRequest, *, deadline_s: float) -> ProviderResult:
        """Produce a structured result or classified failure before deadline_s elapses."""


def build_provider(name: str, *, stub_delay_ms: int = 0) -> Provider:
    """Create a provider from configuration.

    Only ``stub`` is implemented in this slice. ``mimo`` is reserved for later.
    """
    from ai_bridge.providers.stub import StubProvider

    normalized = name.strip().lower()
    if normalized == "stub":
        return StubProvider(delay_ms=stub_delay_ms)
    if normalized == "mimo":
        raise NotImplementedError(
            "MiMo provider is not implemented in this minimal slice; use PROVIDER=stub"
        )
    raise ValueError(f"unknown provider: {name}")
