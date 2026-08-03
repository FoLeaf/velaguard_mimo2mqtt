"""Synthetic AI request publisher for local Mosquitto verification.

Example:
  python -m ai_bridge.cli.synthetic_publisher --device-id dev01
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from typing import Any

import paho.mqtt.client as mqtt


def _build_client(client_id: str) -> mqtt.Client:
    try:
        return mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
            clean_session=True,
        )
    except (TypeError, AttributeError):
        return mqtt.Client(client_id=client_id, clean_session=True)


def build_request(
    *,
    device_id: str,
    type_: str = "diagnosis",
    req_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = {
        "req_id": req_id or str(uuid.uuid4()),
        "device_id": device_id,
        "created_ts_ms": int(time.time() * 1000),
        "type": type_,
        "note": "synthetic publisher",
    }
    if extra:
        body.update(extra)
    # payload_hash over stable canonical content excluding the hash itself
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    body["payload_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish a synthetic AI request and wait for response")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--device-id", default="dev01")
    parser.add_argument("--type", default="diagnosis", dest="type_")
    parser.add_argument("--req-id", default=None)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    args = parser.parse_args(argv)

    request = build_request(device_id=args.device_id, type_=args.type_, req_id=args.req_id)
    req_id = request["req_id"]
    request_topic = f"vg/{args.device_id}/ai/request"
    response_topic = f"vg/{args.device_id}/ai/response/{req_id}"

    responses: list[dict[str, Any]] = []
    done = False

    client = _build_client(client_id=f"synthetic-pub-{req_id[:8]}")
    if args.username:
        client.username_pw_set(args.username, args.password)

    def on_connect(client: mqtt.Client, userdata: Any, *cb_args: Any) -> None:
        client.subscribe(response_topic, qos=1)
        payload = json.dumps(request).encode("utf-8")
        client.publish(request_topic, payload, qos=1, retain=False)
        print(f"published topic={request_topic} req_id={req_id}")

    def on_message(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        nonlocal done
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except Exception as exc:
            print(f"invalid response payload: {exc}")
            return
        responses.append(data)
        print(json.dumps(data, indent=2, ensure_ascii=False))
        if data.get("status") in {"success", "error"}:
            done = True

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.host, args.port, keepalive=30)
    client.loop_start()

    deadline = time.time() + args.timeout
    try:
        while time.time() < deadline and not done:
            time.sleep(0.05)
    finally:
        client.loop_stop()
        client.disconnect()

    if not responses:
        print("no response received before timeout", file=sys.stderr)
        return 1

    terminal = [r for r in responses if r.get("status") in {"success", "error"}]
    if not terminal:
        print("only processing responses received", file=sys.stderr)
        return 2
    return 0 if terminal[-1].get("status") == "success" else 3


if __name__ == "__main__":
    sys.exit(main())
