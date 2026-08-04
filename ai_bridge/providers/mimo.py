"""Real MiMo HTTPS provider (OpenAI-compatible chat completions).

Isolates all MiMo-specific HTTP transport and response parsing here so that
nothing provider-specific leaks into MQTT contracts. The bridge treats the
provider result exactly as it treats any other ``Provider``: schema-validated
success or a classified ``ProviderFailure``.

Secret handling: the MiMo API key is supplied through the constructor (from the
deploy-time env var ``MIMO_API_KEY``) and is only ever used in the
``Authorization`` header of the HTTPS request. It is never logged, never
serialized into payloads, and never echoed in error messages.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from typing import Any

import requests

from ai_bridge.contracts.request import AiRequest
from ai_bridge.observability.logging import get_logger
from ai_bridge.providers.base import ProviderFailure, ProviderResult, ProviderSuccess
from ai_bridge.providers.schema import SchemaValidationError, validate_diagnosis_result
from ai_bridge.runtime.skill_manager import DEFAULT_DIAGNOSIS_SKILL

logger = get_logger(__name__)

# Backward-compatible constant: when no Skill is injected, the built-in v2
# diagnosis prompt is used (single source of truth in runtime.skill_manager).
DIAGNOSIS_SYSTEM_PROMPT = DEFAULT_DIAGNOSIS_SKILL

_USER_CONTENT_MAX_CHARS = 2048

_NON_RETRYABLE_STATUSES = frozenset({400, 401, 403})


class MiMoProvider:
    """Calls MiMo ``{base_url}/chat/completions`` and validates structured output.

    ``deadline_s`` is the overall request deadline owned by the application
    layer. Every HTTP attempt uses a per-attempt timeout that never exceeds the
    remaining budget, and transient failures (429/5xx/network) are retried a
    bounded number of times inside that budget. Breaching the deadline is
    reported as ``ProviderFailure(code="timeout")``.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        http_timeout_ms: int = 15_000,
        max_retries: int = 2,
        retry_backoff_ms: int = 500,
        system_prompt: str = DIAGNOSIS_SYSTEM_PROMPT,
        user_content_builder: Callable[[AiRequest], str] | None = None,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("MiMoProvider requires a non-empty api_key")
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._http_timeout_ms = max(1, int(http_timeout_ms))
        self._max_retries = max(0, int(max_retries))
        self._retry_backoff_ms = max(0, int(retry_backoff_ms))
        self._system_prompt = system_prompt
        self._user_content_builder = user_content_builder
        self._session = session if session is not None else requests.Session()

    # -- Provider protocol ---------------------------------------------------

    def handle(self, request: AiRequest, *, deadline_s: float) -> ProviderResult:
        if deadline_s <= 0:
            return ProviderFailure(code="timeout", message="request deadline exceeded")

        started = time.monotonic()
        messages = self._build_messages(request)
        last_error = "mimo request failed"

        attempts = self._max_retries + 1
        for attempt in range(1, attempts + 1):
            if self._remaining_ms(deadline_s, started) <= 0:
                return ProviderFailure(code="timeout", message="request deadline exceeded")

            attempt_timeout_s = self._attempt_timeout_s(deadline_s, started)
            try:
                response = self._post_chat_completion(
                    messages, timeout=attempt_timeout_s
                )
            except requests.exceptions.Timeout:
                last_error = "mimo request timed out"
                logger.warning(
                    "mimo_attempt device_id=%s req_id=%s attempt=%s outcome=timeout "
                    "elapsed_ms=%s",
                    request.device_id,
                    request.req_id,
                    attempt,
                    self._elapsed_ms(started),
                )
                continue
            except requests.exceptions.RequestException:
                last_error = "mimo request failed (network error)"
                logger.warning(
                    "mimo_attempt device_id=%s req_id=%s attempt=%s outcome=network_error "
                    "elapsed_ms=%s",
                    request.device_id,
                    request.req_id,
                    attempt,
                    self._elapsed_ms(started),
                )
                continue

            status = response.status_code
            if status in _NON_RETRYABLE_STATUSES:
                logger.warning(
                    "mimo_attempt device_id=%s req_id=%s attempt=%s status=%s "
                    "outcome=provider_error elapsed_ms=%s",
                    request.device_id,
                    request.req_id,
                    attempt,
                    status,
                    self._elapsed_ms(started),
                )
                return ProviderFailure(
                    code="provider_error",
                    message=f"mimo provider error (HTTP {status})",
                    fallback_eligible=True,
                )

            if status == 429 or status >= 500:
                logger.warning(
                    "mimo_attempt device_id=%s req_id=%s attempt=%s status=%s "
                    "outcome=retryable elapsed_ms=%s",
                    request.device_id,
                    request.req_id,
                    attempt,
                    status,
                    self._elapsed_ms(started),
                )
                last_error = f"mimo provider error (HTTP {status})"
                # Only back off when a further attempt is actually possible.
                # Sleeping after the final attempt burns the remaining deadline
                # for nothing and can misclassify an exhausted-transient
                # failure as `timeout` instead of `provider_error`.
                if attempt < attempts:
                    self._sleep_backoff(deadline_s, started)
                continue

            if status != 200:
                logger.warning(
                    "mimo_attempt device_id=%s req_id=%s attempt=%s status=%s "
                    "outcome=provider_error elapsed_ms=%s",
                    request.device_id,
                    request.req_id,
                    attempt,
                    status,
                    self._elapsed_ms(started),
                )
                return ProviderFailure(
                    code="provider_error",
                    message=f"mimo provider error (HTTP {status})",
                    fallback_eligible=True,
                )

            try:
                content = self._extract_content(response)
                data = json.loads(content) if isinstance(content, str) else content
                result = validate_diagnosis_result(data)
            except (SchemaValidationError, json.JSONDecodeError, ValueError) as exc:
                # Provider output failed the v2 schema; never success, never retried.
                logger.warning(
                    "mimo_attempt device_id=%s req_id=%s attempt=%s "
                    "outcome=schema_invalid elapsed_ms=%s",
                    request.device_id,
                    request.req_id,
                    attempt,
                    self._elapsed_ms(started),
                )
                _ = exc
                return ProviderFailure(
                    code="provider_error",
                    message="provider output failed schema validation",
                    # Schema-invalid output never enters fallback.
                    fallback_eligible=False,
                )

            result["source"] = "mimo"
            logger.info(
                "mimo_attempt device_id=%s req_id=%s attempt=%s status=200 "
                "outcome=success elapsed_ms=%s",
                request.device_id,
                request.req_id,
                attempt,
                self._elapsed_ms(started),
            )
            return ProviderSuccess(result=result)

        # Retry budget exhausted. Distinguish a deadline breach from an
        # ordinary exhausted-transient failure.
        if self._remaining_ms(deadline_s, started) <= 0:
            return ProviderFailure(code="timeout", message="request deadline exceeded")
        return ProviderFailure(
            code="provider_error",
            message=last_error,
            fallback_eligible=True,
        )

    # -- request building ----------------------------------------------------

    def _build_messages(self, request: AiRequest) -> list[dict[str, str]]:
        if self._user_content_builder is not None:
            user_content = self._user_content_builder(request)
        else:
            user_content = self._safe_user_content(request)
        return [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_content},
        ]

    def _safe_user_content(self, request: AiRequest) -> str:
        """Bounded user message: identity fields plus a truncated request body."""
        body = json.dumps(request.raw, ensure_ascii=True, sort_keys=True)
        if len(body) > _USER_CONTENT_MAX_CHARS:
            body = body[:_USER_CONTENT_MAX_CHARS] + "...[truncated]"
        return json.dumps(
            {
                "device_id": request.device_id,
                "req_id": request.req_id,
                "type": request.type,
                "request": body,
            },
            ensure_ascii=True,
        )

    # -- HTTP ----------------------------------------------------------------

    def _post_chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        timeout: float,
    ) -> requests.Response:
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        return self._session.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout,
        )

    def _extract_content(self, response: requests.Response) -> str | dict[str, Any]:
        """Extract ``choices[0].message.content`` from a chat completion."""
        try:
            body = response.json()
        except ValueError as exc:
            raise ValueError("chat completion body is not valid JSON") from exc

        choices = body.get("choices") if isinstance(body, dict) else None
        if not isinstance(choices, list) or not choices:
            raise ValueError("chat completion has no choices")

        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None

        if content is None:
            raise ValueError("chat completion message has no content")
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            return content
        raise ValueError("chat completion content has invalid type")

    # -- deadline / budget ---------------------------------------------------

    def _attempt_timeout_s(self, deadline_s: float, started: float) -> float:
        remaining_ms = self._remaining_ms(deadline_s, started)
        return min(self._http_timeout_ms, max(remaining_ms, 1)) / 1000.0

    def _sleep_backoff(self, deadline_s: float, started: float) -> None:
        remaining_ms = self._remaining_ms(deadline_s, started)
        if remaining_ms <= 0:
            return
        jittered = self._retry_backoff_ms * (0.5 + random.random())
        sleep_ms = min(remaining_ms, jittered)
        if sleep_ms > 0:
            time.sleep(sleep_ms / 1000.0)

    def _remaining_ms(self, deadline_s: float, started: float) -> float:
        return deadline_s * 1000.0 - self._elapsed_ms(started)

    def _elapsed_ms(self, started: float) -> float:
        return (time.monotonic() - started) * 1000.0
