"""Synthetic VelaGuard board: publishes the four dashboard topics for
joint debugging, demos, and integration tests without real hardware.

Contract mirrors `.trellis/spec/backend/mqtt-dashboard-contracts.md`
(Scenario: Dashboard consumption contract):

- ``vg/{id}/point_table``  QoS 1, retained  (device point-table JSON)
- ``vg/{id}/status``       QoS 0, retained  (+ optional offline demo)
- ``vg/{id}/telemetry``    QoS 0, not retained (periodic ``[{id,value,ok,age_ms}]``)
- ``vg/{id}/alarm``        QoS 1, not retained (raised/cleared demo)

Usage::

    python -m dashboard.tools.synthetic_board --device-id vg-demo01
    python -m dashboard.tools.synthetic_board --offline   # publish LWT-style offline
"""

from __future__ import annotations

import argparse
import sys
import time

from dashboard.contracts.topics import (
    ALARM_QOS,
    ALARM_RETAINED,
    POINT_TABLE_QOS,
    POINT_TABLE_RETAINED,
    STATUS_QOS,
    STATUS_RETAINED,
    TELEMETRY_QOS,
    TELEMETRY_RETAINED,
)
from dashboard.transport.mqtt import MqttClient

# Demo point table in the TeamFalcons device schema (schema_version 1).
DEMO_POINT_TABLE = {
    "schema_version": 1,
    "bus": {"device": "/dev/rs485", "baud": 9600},
    "hits": [1],
    "points": [
        {"id": "temp", "name": "温度", "addr": 1, "fc": 3, "reg": 0, "qty": 1,
         "dtype": "int16", "scale": 0.1, "unit": "C", "cmp": "ge", "warn": 40, "crit": 55, "fail_n": 3},
        {"id": "humidity", "name": "湿度", "addr": 1, "fc": 3, "reg": 1, "qty": 1,
         "dtype": "uint16", "scale": 0.1, "unit": "%RH", "cmp": "le", "warn": 20, "fail_n": 3},
        {"id": "flood", "name": "水浸", "addr": 2, "fc": 3, "reg": 2, "qty": 1,
         "dtype": "uint16", "scale": 1, "unit": "", "cmp": "eq", "crit": 1, "fail_n": 3},
    ],
}


def build_status(device_id: str, online: bool, uptime_ms: int) -> dict:
    return {
        "device_id": device_id,
        "online": online,
        "firmware": "0.1.0",
        "build_mode": "TEST",
        "network": "rj45",
        "uptime_ms": uptime_ms,
        "ts_ms": int(time.time() * 1000),
        "time_quality": "unknown",
    }


def build_telemetry(tick: int) -> list[dict]:
    temp = round(30 + 8 * (1 + _sin(tick / 12.0)), 1)  # 22..38 周期波动
    humidity = round(55 + 10 * _sin(tick / 9.0), 1)
    return [
        {"id": "temp", "value": temp, "ok": True, "age_ms": 120},
        {"id": "humidity", "value": humidity, "ok": True, "age_ms": 120},
        {"id": "flood", "value": 0, "ok": True, "age_ms": 130},
    ]


def _sin(x: float) -> float:
    import math

    return math.sin(x)


def build_alarm(device_id: str, point_id: str, kind: str, state: str,
                value: float, thr: float, seq: int) -> dict:
    return {
        "ts_ms": int(time.time() * 1000),
        "device_id": device_id,
        "alarm_id": f"{device_id}-demo-{seq}",
        "id": point_id,
        "kind": kind,
        "value": value,
        "thr": thr,
        "state": state,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthetic VelaGuard board publisher")
    parser.add_argument("--device-id", default="vg-demo01")
    parser.add_argument("--host", default=None, help="default: MQTT_HOST env or localhost")
    parser.add_argument("--port", type=int, default=None, help="default: MQTT_PORT env or 1883")
    parser.add_argument("--interval", type=float, default=3.0, help="telemetry period seconds")
    parser.add_argument("--alarm-after", type=float, default=12.0,
                        help="raise the demo alarm after N seconds (0 disables)")
    parser.add_argument("--alarm-clear-after", type=float, default=15.0,
                        help="clear the demo alarm N seconds after raising (0 keeps it open)")
    parser.add_argument("--offline", action="store_true",
                        help="publish a retained offline status (LWT simulation) and exit")
    parser.add_argument("--cycles", type=int, default=0,
                        help="stop after N telemetry cycles (0 = run forever)")
    args = parser.parse_args(argv)

    client = MqttClient(
        host=args.host or _env_default("MQTT_HOST", "localhost"),
        port=args.port or int(_env_default("MQTT_PORT", "1883")),
        client_id=f"synthetic-board-{args.device_id}",
    )
    client.start()
    if not client.wait_connected(timeout=10.0):
        print("ERROR: cannot connect to broker", file=sys.stderr)
        client.stop()
        return 1

    topic_root = f"vg/{args.device_id}"
    client.publish_json(f"{topic_root}/point_table", DEMO_POINT_TABLE,
                        qos=POINT_TABLE_QOS, retain=POINT_TABLE_RETAINED)
    client.publish_json(f"{topic_root}/status", build_status(args.device_id, True, 0),
                        qos=STATUS_QOS, retain=STATUS_RETAINED)
    print(f"published point_table + status(online) for {args.device_id}")

    if args.offline:
        offline = build_status(args.device_id, False, 0)
        client.publish_json(f"{topic_root}/status", offline,
                            qos=STATUS_QOS, retain=STATUS_RETAINED)
        print("published status(offline) LWT simulation")
        time.sleep(0.5)
        client.stop()
        return 0

    start_ms = int(time.time() * 1000)
    tick = 0
    alarm_seq = 0
    alarm_raised_at: float | None = None
    alarm_cleared = False

    try:
        while True:
            client.publish_json(f"{topic_root}/telemetry", build_telemetry(tick),
                                qos=TELEMETRY_QOS, retain=TELEMETRY_RETAINED)
            tick += 1

            uptime = int(time.time() * 1000) - start_ms
            client.publish_json(f"{topic_root}/status",
                                build_status(args.device_id, True, uptime),
                                qos=STATUS_QOS, retain=STATUS_RETAINED)

            elapsed = uptime / 1000.0
            temp = build_telemetry(tick)[0]["value"]
            if (args.alarm_after > 0 and alarm_raised_at is None
                    and elapsed >= args.alarm_after and temp >= 35.0):
                alarm_seq += 1
                client.publish_json(
                    f"{topic_root}/alarm",
                    build_alarm(args.device_id, "temp", "threshold_high",
                                "raised", temp, 35.0, alarm_seq),
                    qos=ALARM_QOS, retain=ALARM_RETAINED,
                )
                alarm_raised_at = time.time()
                alarm_cleared = False
                print(f"alarm raised (seq {alarm_seq}, temp={temp})")
            elif (alarm_raised_at is not None and not alarm_cleared
                  and args.alarm_clear_after > 0
                  and time.time() - alarm_raised_at >= args.alarm_clear_after):
                client.publish_json(
                    f"{topic_root}/alarm",
                    build_alarm(args.device_id, "temp", "threshold_high",
                                "cleared", temp, 35.0, alarm_seq),
                    qos=ALARM_QOS, retain=ALARM_RETAINED,
                )
                alarm_cleared = True
                print("alarm cleared")

            if args.cycles > 0 and tick >= args.cycles:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        client.stop()
    return 0


def _env_default(name: str, default: str) -> str:
    import os

    return os.environ.get(name, default)


if __name__ == "__main__":
    sys.exit(main())
