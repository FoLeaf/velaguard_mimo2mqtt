"""Provider protocol and result types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from ai_bridge.contracts.request import AiRequest

if TYPE_CHECKING:
    from ai_bridge.configuration.settings import Settings


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


def build_provider(
    name: str,
    *,
    stub_delay_ms: int = 0,
    settings: Settings | None = None,
) -> Provider:
    """Create a provider from configuration.

    ``stub`` (default) is deterministic and needs no credentials. ``mimo``
    builds the real HTTPS adapter and fails fast with a clear ``ValueError`` at
    startup when ``MIMO_API_KEY`` is unset.
    """
    from ai_bridge.providers.stub import StubProvider

    normalized = name.strip().lower()
    if normalized == "stub":
        return StubProvider(delay_ms=stub_delay_ms)
    if normalized == "mimo":
        from ai_bridge.configuration.settings import load_settings
        from ai_bridge.providers.mimo import MiMoProvider

        config = settings if settings is not None else load_settings()
        if not config.mimo_api_key:
            raise ValueError(
                "PROVIDER=mimo requires MIMO_API_KEY to be set "
                "(inject via server env; never commit the key)"
            )
        return MiMoProvider(
            base_url=config.mimo_base_url,
            model=config.mimo_model,
            api_key=config.mimo_api_key,
            http_timeout_ms=config.mimo_http_timeout_ms,
            max_retries=config.mimo_max_retries,
            retry_backoff_ms=config.mimo_retry_backoff_ms,
        )
    raise ValueError(f"unknown provider: {name}")
