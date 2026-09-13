"""Process entrypoint: ``python -m dashboard`` (console script ``vg-dashboard``).

Assembles: SQLite store → collector → MQTT subscriber (read-only) → HTTP server.
The dashboard never publishes to device-facing topics (boundary V5).
"""

from __future__ import annotations

import signal
import sys
import threading

from ai_bridge.observability.logging import configure_logging, get_logger
from ai_bridge.transport.mqtt.client import run_until_stopped
from dashboard.application.collector import Collector
from dashboard.configuration.settings import Settings, load_settings
from dashboard.http.server import DashboardHttpServer
from dashboard.storage.db import DashboardStore
from dashboard.transport.subscriber import build_subscriber

logger = get_logger(__name__)


def build_runtime(
    settings: Settings,
) -> tuple[DashboardStore, Collector, DashboardHttpServer, threading.Timer]:
    store = DashboardStore(settings.db_path)
    collector = Collector(store, message_buffer_limit=settings.message_buffer_limit)
    http_server = DashboardHttpServer(store, settings.http_host, settings.http_port)

    def _cleanup() -> None:
        try:
            store.cleanup(
                settings.history_retention_hours,
                settings.message_buffer_limit,
                settings.alarm_event_limit,
            )
            logger.debug("dashboard_retention_cleanup_done")
        except Exception:
            logger.exception("dashboard_retention_cleanup_error")

    timer = threading.Timer(settings.cleanup_interval_s, _cleanup)
    timer.daemon = True
    return store, collector, http_server, timer


def main(argv: list[str] | None = None) -> int:
    _ = argv
    settings = load_settings()
    configure_logging(settings.log_level)
    logger.info(
        "dashboard_starting mqtt=%s:%s client_id=%s tls=%s http=%s:%s db=%s",
        settings.mqtt_host,
        settings.mqtt_port,
        settings.mqtt_client_id,
        settings.mqtt_tls,
        settings.http_host,
        settings.http_port,
        settings.db_path,
    )

    store, collector, http_server, cleanup_timer = build_runtime(settings)
    client = build_subscriber(
        host=settings.mqtt_host,
        port=settings.mqtt_port,
        client_id=settings.mqtt_client_id,
        username=settings.mqtt_username,
        password=settings.mqtt_password,
        tls_enabled=settings.mqtt_tls,
        ca_path=settings.mqtt_ca_path,
        client_cert_path=settings.mqtt_client_cert_path,
        client_key_path=settings.mqtt_client_key_path,
        on_message=collector.handle_message,
    )

    stop_event = threading.Event()

    def _stop(*_args: object) -> None:
        logger.info("shutdown_signal_received")
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    client.start()
    if not client.wait_connected(timeout=15.0):
        logger.error(
            "mqtt_connect_timeout host=%s port=%s", settings.mqtt_host, settings.mqtt_port
        )
        client.stop()
        store.close()
        return 1

    http_server.start()
    cleanup_timer.start()
    logger.info("dashboard_ready filters=vg/+/status,vg/+/telemetry,vg/+/alarm,vg/+/point_table")

    try:
        run_until_stopped(client, stop_event=stop_event)
    finally:
        client.stop()
        http_server.stop()
        cleanup_timer.cancel()
        store.close()
    logger.info("dashboard_stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
