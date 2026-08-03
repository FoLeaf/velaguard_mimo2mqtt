"""Deterministic stub provider for contract verification without live MiMo."""

from __future__ import annotations

import time

from ai_bridge.contracts.request import AiRequest
from ai_bridge.providers.base import ProviderFailure, ProviderResult, ProviderSuccess


class StubProvider:
    """Returns a fixed advisory diagnosis result.

    Optional ``delay_ms`` supports timeout-path tests.
    """

    def __init__(self, *, delay_ms: int = 0) -> None:
        self._delay_ms = max(0, delay_ms)

    def handle(self, request: AiRequest, *, deadline_s: float) -> ProviderResult:
        if deadline_s <= 0:
            return ProviderFailure(code="timeout", message="request deadline exceeded")

        delay_s = self._delay_ms / 1000.0
        # If configured delay cannot finish inside the remaining deadline, time out.
        if delay_s >= deadline_s:
            # Sleep up to the remaining budget so callers observe real elapsed time.
            time.sleep(max(deadline_s, 0.0))
            return ProviderFailure(code="timeout", message="request deadline exceeded")

        if delay_s > 0:
            time.sleep(delay_s)

        # request is unused for content but keeps the seam realistic
        _ = request
        return ProviderSuccess(
            result={
                "diagnosis_summary": "stub: no live MiMo call",
                "source": "stub",
                "advisory_only": True,
            }
        )
