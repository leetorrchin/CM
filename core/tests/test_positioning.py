import json
from pathlib import Path

import pytest

from crowd_core.positioning import snap_to_zone

VENUE = json.loads((Path(__file__).resolve().parents[2] / "venues" / "example-minimal-festival.json").read_text())


def test_inside_a_zone():
    assert snap_to_zone(VENUE, 100, 60) == "main_field"
    assert snap_to_zone(VENUE, 230, 60) == "stage_a_front"


def test_outside_snaps_to_nearest():
    assert snap_to_zone(VENUE, 205, -5) == "main_field"      # just south of the field, nearest is the field
    assert snap_to_zone(VENUE, 118, -10) == "exit_lane_south"


def test_level_filter_separates_floors():
    # same x,y footprint region: the grandstand is on the upper level only
    assert snap_to_zone(VENUE, 230, 105, "upper") == "grandstand"
    assert snap_to_zone(VENUE, 230, 105, "ground") != "grandstand"
    with pytest.raises(ValueError):
        snap_to_zone(VENUE, 0, 0, "basement")
