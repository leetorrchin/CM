import copy
import json
from pathlib import Path

import pytest
from crowd_core.schemas import schema_errors
from crowd_core.venue import load_venue, validate_venue

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "venues" / "example-minimal-festival.json"


@pytest.fixture
def venue():
    return json.loads(EXAMPLE.read_text())


def test_example_venue_is_valid():
    assert validate_venue(json.loads(EXAMPLE.read_text())) == []
    assert load_venue(EXAMPLE)["id"] == "example-minimal-festival"


def test_unknown_zone_in_threshold(venue):
    venue["thresholds"][0]["to_zone"] = "nowhere"
    assert any("unknown to_zone" in e for e in validate_venue(venue))


def test_duplicate_zone_id(venue):
    venue["zones"].append(copy.deepcopy(venue["zones"][0]))
    assert any("duplicate id" in e for e in validate_venue(venue))


def test_stairs_must_change_level(venue):
    venue["thresholds"][-1]["to_zone"] = "stage_a_front"
    venue["thresholds"][-1]["from_zone"] = "food_court"
    assert any("different levels" in e for e in validate_venue(venue))


def test_level_change_needs_stairs_or_ramp(venue):
    venue["thresholds"][-1]["kind"] = "opening"
    assert any("connects levels" in e for e in validate_venue(venue))


def test_unreachable_zone_is_flagged(venue):
    venue["thresholds"] = [t for t in venue["thresholds"] if t["id"] != "t_plaza_field"]
    venue["thresholds"] = [t for t in venue["thresholds"] if t["id"] != "t_plaza_assembly"]
    venue["sensor_sites"] = []  # they referenced the removed thresholds
    assert any("cannot reach any safe destination" in e for e in validate_venue(venue))


def test_schema_rejects_missing_field(venue):
    del venue["zones"][0]["polygon"]
    assert schema_errors("venue", venue)


def test_other_message_schemas_accept_samples():
    assert schema_errors("occupancy_reading", {
        "schema_version": "0.1.0", "source_id": "cam_stage_a", "source_type": "camera",
        "target": {"kind": "zone", "id": "stage_a_front"},
        "timestamp": "2026-10-24T18:00:00+11:00", "count": 1840, "confidence": 0.85}) == []
    assert schema_errors("occupancy_reading", {
        "schema_version": "0.1.0", "source_id": "x", "source_type": "camera",
        "target": {"kind": "zone", "id": "z"}, "timestamp": "2026-10-24T18:00:00+11:00",
        "confidence": 0.5}) != []  # needs count or flow
    assert schema_errors("group", {"schema_version": "0.1.0", "id": "g1",
                                   "member_ids": ["a", "b"]}) == []
    assert schema_errors("entity", {"schema_version": "0.1.0", "id": "e1", "group_id": "g1"}) == []
    assert schema_errors("plan", {
        "schema_version": "0.1.0", "timestamp": "2026-10-24T18:00:00+11:00", "mode": "evacuation",
        "assignments": [{"subject": {"kind": "group", "id": "g1"}, "destination_id": "exit_north"}]}) == []
    assert schema_errors("event", {
        "schema_version": "0.1.0", "run_id": "r1", "seq": 0,
        "timestamp": "2026-10-24T18:00:00+11:00", "type": "mode_change",
        "data": {"mode": "evacuation"}}) == []
