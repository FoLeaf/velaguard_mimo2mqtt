"""paho-mqtt client with explicit subscriptions and reconnect handling."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import paho.mqtt.client as mqtt

from dashboard.observability.logging import get_logger

logger = get_logger(__name__)

MessageHandler = Callable[[str, bytes], None]
SubscribeFilter = tuple[str, int]


class MqttClient:
    """MQTT transport shared by the collector and synthetic board.

    - Subscribes only to explicitly configured filters on connect/reconnect
    - A publisher-only client has no subscriptions
    - clean_session / clean_start True (no durable broker session assumed)
    - Dispatches inbound messages off the network loop so in-flight work
      cannot block MQTT network processing
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        client_id: str,
        username: str | None = None,
        password: str | None = None,
        on_message: MessageHandler | None = None,
        keepalive: int = 60,
        worker_threads: int = 8,
        tls_enabled: bool = False,
        ca_path: str | None = None,
        client_cert_path: str | None = None,
        client_key_path: str | None = None,
        subscribe_filters: Sequence[SubscribeFilter] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._keepalive = keepalive
        self._on_message = on_message
        self._subscribe_filters = tuple(subscribe_filters or ())
        self._connected = threading.Event()
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, worker_threads),
            thread_name_prefix="dashboard-mqtt",
        )
        self._closed = False

        try:
            # paho-mqtt 2.x
            self._client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=client_id,
                protocol=mqtt.MQTTv311,
                clean_session=True,
            )
        except (TypeError, AttributeError):
            # paho-mqtt 1.x fallback
            self._client = mqtt.Client(client_id=client_id, clean_session=True)

        if username:
            self._client.username_pw_set(username, password)

        if tls_enabled:
            # Certificate verification is always on; no insecure skip switch
            # is exposed. Empty ca_path falls back to the system CA store.
            self._client.tls_set(
                ca_certs=ca_path or None,
                certfile=client_cert_path,
                keyfile=client_key_path,
            )

        self._client.on_connect = self._handle_connect
        self._client.on_disconnect = self._handle_disconnect
        self._client.on_message = self._handle_message

    def set_message_handler(self, handler: MessageHandler) -> None:
        self._on_message = handler

    def start(self) -> None:
        logger.info("mqtt_connecting host=%s port=%s", self._host, self._port)
        self._client.connect_async(self._host, self._port, keepalive=self._keepalive)
        self._client.loop_start()

    def stop(self) -> None:
        self._closed = True
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            logger.exception("mqtt_stop_error")
        self._connected.clear()
        self._executor.shutdown(wait=True, cancel_futures=False)
        logger.info("mqtt_stopped")

    def wait_connected(self, timeout: float = 10.0) -> bool:
        return self._connected.wait(timeout)

    def publish_json(
        self,
        topic: str,
        payload: dict[str, Any] | list[dict[str, Any]],
        *,
        qos: int,
        retain: bool,
    ) -> mqtt.MQTTMessageInfo:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        info = self._client.publish(topic, body.encode("utf-8"), qos=qos, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.error("mqtt_publish_failed topic=%s rc=%s", topic, info.rc)
        return info

    def is_connected(self) -> bool:
        return self._connected.is_set()

    def _handle_connect(self, client: mqtt.Client, userdata: Any, *args: Any) -> None:
        # paho v1: (flags, rc)  |  paho v2 CallbackAPIVersion.VERSION2: (flags, reason_code, properties)
        if not args:
            logger.error("mqtt_connect_failed missing_args")
            return
        reason = args[0] if len(args) == 1 else args[1]
        if not self._connect_succeeded(reason):
            logger.error("mqtt_connect_failed rc=%s", reason)
            return

        logger.info(
            "mqtt_connected; subscribing filters=%s",
            ", ".join(f"{f} q{q}" for f, q in self._subscribe_filters),
        )
        for topic_filter, qos in self._subscribe_filters:
            client.subscribe(topic_filter, qos=qos)
        self._connected.set()

    @staticmethod
    def _connect_succeeded(reason: Any) -> bool:
        if reason is None:
            return False
        if reason == 0:
            return True
        # paho ReasonCode / enum-like
        is_failure = getattr(reason, "is_failure", None)
        if callable(is_failure):
            return not bool(is_failure())
        value = getattr(reason, "value", reason)
        try:
            return int(value) == 0
        except (TypeError, ValueError):
            text = str(reason)
            return text in {"Success", "0"} or text.endswith(".Success")

    def _handle_disconnect(self, client: mqtt.Client, userdata: Any, *args: Any) -> None:
        self._connected.clear()
        logger.warning("mqtt_disconnected args=%s", args)

    def _handle_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        # Keep ingestion and storage work off the network loop.
        if self._closed:
            return
        handler = self._on_message
        if handler is None:
            return
        try:
            payload = (
                msg.payload
                if isinstance(msg.payload, (bytes, bytearray))
                else bytes(msg.payload)
            )
            topic = msg.topic
            raw = bytes(payload)
        except Exception:
            logger.exception("mqtt_message_decode_error topic=%s", getattr(msg, "topic", None))
            return

        try:
            self._executor.submit(self._dispatch_message, handler, topic, raw)
        except RuntimeError:
            # Executor already shut down during stop().
            logger.warning("mqtt_message_dropped_executor_closed topic=%s", topic)

    def _dispatch_message(self, handler: MessageHandler, topic: str, payload: bytes) -> None:
        try:
            handler(topic, payload)
        except Exception:
            logger.exception("mqtt_message_handler_error topic=%s", topic)


def run_until_stopped(
    client: MqttClient,
    *,
    stop_event: threading.Event | None = None,
    poll_s: float = 0.5,
) -> None:
    """Block until stop_event is set (or KeyboardInterrupt)."""
    event = stop_event or threading.Event()
    try:
        while not event.is_set():
            time.sleep(poll_s)
    except KeyboardInterrupt:
        event.set()
