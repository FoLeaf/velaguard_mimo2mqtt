"""Local demo harness (no broker needed): feeds the collector the same
messages synthetic_board would publish, then serves the dashboard.

Usage: python scripts/demo_dashboard_seed.py  (Ctrl+C to stop)
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.application.collector import Collector  # noqa: E402
from dashboard.http.server import DashboardHttpServer  # noqa: E402
from dashboard.storage.db import DashboardStore  # noqa: E402
from dashboard.tools.synthetic_board import (  # noqa: E402
    DEMO_POINT_TABLE,
    build_alarm,
    build_status,
)

DB_PATH = "dashboard-demo.db"
HOST, PORT = "127.0.0.1", 8765


def publish(collector: Collector, topic: str, payload) -> None:
    body = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
    collector.handle_message(topic, body)


def main() -> int:
    Path(DB_PATH).unlink(missing_ok=True)
    store = DashboardStore(DB_PATH)
    collector = Collector(store, message_buffer_limit=200)
    device = "vg-demo01"

    publish(collector, f"vg/{device}/status",
            build_status(device, True, 1000))
    publish(collector, f"vg/{device}/point_table", DEMO_POINT_TABLE)

    # A second device that stays offline (LWT payload).
    publish(collector, "vg/vg-demo02/status",
            {"device_id": "vg-demo02", "online": False})

    # Telemetry wave for the trend chart.
    for tick in range(40):
        temp = round(30 + 6 * math.sin(tick / 4.0), 1)
        humidity = round(55 + 8 * math.cos(tick / 5.0), 1)
        publish(collector, f"vg/{device}/telemetry", [
            {"id": "temp", "value": temp, "ok": True, "age_ms": 100},
            {"id": "humidity", "value": humidity, "ok": True, "age_ms": 100},
            {"id": "flood", "value": 0, "ok": True, "age_ms": 110},
        ])
        time.sleep(0.15)

    # Alarm raised (still active) on a second sensor id.
    publish(collector, f"vg/{device}/alarm",
            build_alarm(device, "temp", "threshold_high", "raised", 36.0, 35.0, 1))
    # One quarantined message to demo the debug view.
    collector.handle_message(f"vg/{device}/telemetry", b"not-json-at-all")

    server = DashboardHttpServer(store, HOST, PORT)
    server.start()
    print(f"demo dashboard: http://{HOST}:{PORT}  (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
