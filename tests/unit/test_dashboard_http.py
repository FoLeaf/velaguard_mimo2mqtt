"""Broker-free HTTP smoke coverage for the standalone dashboard."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from dashboard.application.collector import Collector
from dashboard.http.server import DashboardHttpServer, _bounded_int
from dashboard.storage.db import DashboardStore


def test_http_serves_collected_state_and_remains_read_only(tmp_path) -> None:
    store = DashboardStore(str(tmp_path / "dashboard.db"))
    collector = Collector(store)
    collector.handle_message(
        "vg/dev01/status", b'{"device_id":"dev01","online":true,"ts_ms":123}'
    )
    server = DashboardHttpServer(store, "127.0.0.1", 0)
    server.start()
    try:
        assert server.port > 0
        root = f"http://127.0.0.1:{server.port}"
        with urllib.request.urlopen(root + "/api/devices", timeout=5) as response:
            devices = json.load(response)["devices"]
        assert devices[0]["device_id"] == "dev01"
        assert devices[0]["online"] is True
        assert devices[0]["status"]["ts_ms"] == 123
        collector.handle_message(
            "vg/dev01/alarm",
            b'{"id":"temp","state":"raised","kind":"threshold_high","value":36,"thr":35}',
        )
        with urllib.request.urlopen(root + "/api/devices/dev01", timeout=5) as response:
            detail = json.load(response)
        assert detail["active_alarms"] == 1
        assert detail["alarms"][0]["point_id"] == "temp"
        for path in ("/", "/app.js", "/styles.css"):
            with urllib.request.urlopen(root + path, timeout=5) as response:
                assert response.status == 200
                assert response.read()
        with pytest.raises(urllib.error.HTTPError) as missing_point:
            urllib.request.urlopen(root + "/api/devices/dev01/history", timeout=5)
        assert missing_point.value.code == 400
        missing_point.value.close()
        request = urllib.request.Request(root + "/api/devices", data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=5)
        assert error.value.code == 501
        error.value.close()
    finally:
        server.stop()
        store.close()


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([], 60),
        (["invalid"], 60),
        (["0"], 60),
        (["-1"], 60),
        (["15"], 15),
        (["2000"], 1440),
    ],
)
def test_query_values_keep_defaults_and_bounds(values, expected) -> None:
    assert _bounded_int({"minutes": values}, "minutes", default=60, maximum=1440) == expected
