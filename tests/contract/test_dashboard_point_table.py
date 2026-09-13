"""Contract tests for the point_table payload schema.

Fixture is the TeamFalcons reference demo table
(``contest2026_004_TeamFalcons/scripts/vgpoint_demo_points.json``), copied so
the cloud validates against the real device format.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard.application.ingest import IngestError, parse_point_table

FIXTURE = Path(__file__).parent / "fixtures" / "vgpoint_demo_points.json"


def _fixture_payload() -> bytes:
    return FIXTURE.read_bytes()


def test_reference_fixture_parses() -> None:
    parsed = parse_point_table("dev01", _fixture_payload())
    assert parsed.kind == "point_table"
    points = parsed.record["points"]
    assert [p["id"] for p in points] == ["temp", "flood"]
    assert points[0]["name"] == "温度"
    assert points[0]["scale"] == pytest.approx(0.1)
    assert points[1]["crit"] == 1


def test_reference_fixture_roundtrips_unknown_fields() -> None:
    parsed = parse_point_table("dev01", _fixture_payload())
    spec = parsed.record["points"][0]
    original = json.loads(_fixture_payload())["points"][0]
    assert json.loads(spec["spec_json"]) == original


def test_valid_minimal_table() -> None:
    payload = json.dumps(
        {"schema_version": 1, "points": [{"id": "temp", "name": "温度"}]}
    ).encode()
    parsed = parse_point_table("dev01", payload)
    assert parsed.record["points"][0]["id"] == "temp"


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b"[1,2,3]",  # not an object
        json.dumps({"schema_version": 2, "points": [{"id": "a"}]}).encode(),
        json.dumps({"points": [{"id": "a"}]}).encode(),  # missing schema_version
        json.dumps({"schema_version": 1, "points": []}).encode(),  # empty
        json.dumps({"schema_version": 1}).encode(),  # missing points
        json.dumps({"schema_version": 1, "points": [{"id": "bad id!"}]}).encode(),
        json.dumps({"schema_version": 1, "points": [{"id": "x" * 24}]}).encode(),
        json.dumps(
            {"schema_version": 1, "points": [{"id": "a", "warn": None}]}
        ).encode(),  # null threshold forbidden (TeamFalcons rule)
        json.dumps(
            {"schema_version": 1, "points": [{"id": "a", "crit": None}]}
        ).encode(),
        json.dumps({"schema_version": 1, "points": ["nope"]}).encode(),
    ],
)
def test_invalid_tables_quarantined(payload: bytes) -> None:
    with pytest.raises(IngestError):
        parse_point_table("dev01", payload)
