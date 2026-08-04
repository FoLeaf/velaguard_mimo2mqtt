"""Process entrypoint: ``python -m ai_bridge``."""

from __future__ import annotations

import signal
import sys
import threading

from ai_bridge.application.handle_request import HandleAiRequest
from ai_bridge.configuration.settings import Settings, load_settings
from ai_bridge.observability.logging import configure_logging, get_logger
from ai_bridge.persistence.idempotency import InMemoryIdempotencyStore
from ai_bridge.providers.base import build_provider
from ai_bridge.runtime.fallback import build_fallback_diagnosis
from ai_bridge.transport.mqtt.client import MqttBridgeClient, run_until_stopped

logger = get_logger(__name__)


def build_runtime(settings: Settings) -> tuple[MqttBridgeClient, HandleAiRequest]:
    store = InMemoryIdempotencyStore()
    provider = build_provider(
        settings.provider,
        stub_delay_ms=settings.stub_delay_ms,
        settings=settings,
    )

    client = MqttBridgeClient(
        host=settings.mqtt_host,
        port=settings.mqtt_port,
        client_id=settings.mqtt_client_id,
        username=settings.mqtt_username,
        password=settings.mqtt_password,
    )

    use_case = HandleAiRequest(
        store=store,
        provider=provider,
        publish=client.publish_json,
        request_timeout_ms=settings.request_timeout_ms,
        fallback_builder=build_fallback_diagnosis,
        fallback_enabled=settings.fallback_enabled,
    )
    client.set_message_handler(use_case.handle_message)
    return client, use_case


def main(argv: list[str] | None = None) -> int:
    _ = argv
    settings = load_settings()
    configure_logging(settings.log_level)
    logger.info(
        "ai_bridge_starting provider=%s timeout_ms=%s client_id=%s",
        settings.provider,
        settings.request_timeout_ms,
        settings.mqtt_client_id,
    )
    logger.warning(
        "idempotency_store=in_memory disposable=true restart_safe=false "
        "(process lifetime only; not production behavior)"
    )

    client, _use_case = build_runtime(settings)
    stop_event = threading.Event()

    def _stop(*_args: object) -> None:
        logger.info("shutdown_signal_received")
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    client.start()
    if not client.wait_connected(timeout=15.0):
        logger.error("mqtt_connect_timeout host=%s port=%s", settings.mqtt_host, settings.mqtt_port)
        client.stop()
        return 1

    logger.info("ai_bridge_ready subscribed=vg/+/ai/request")
    run_until_stopped(client, stop_event=stop_event)
    client.stop()
    logger.info("ai_bridge_stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
