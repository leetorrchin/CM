"""Every shipped scenario loads, validates and runs to the end with a small crowd."""
from pathlib import Path

import pytest
from crowd_core.scenario import load_scenario, scenario_errors
from crowd_core.venue import load_venue
from crowd_sim.run import run_scenario

ROOT = Path(__file__).resolve().parents[2]
VENUE = ROOT / "venues" / "example-minimal-festival.json"
FILES = sorted((ROOT / "scenarios").glob("*.json"))


def test_there_are_scenarios():
    assert len(FILES) >= 9


@pytest.mark.parametrize("f", FILES, ids=lambda f: f.stem)
def test_scenario_valid(f):
    v = load_venue(VENUE)
    sc = load_scenario(f, v)
    assert scenario_errors(sc, v) == []
    assert sc["id"] == f.stem


@pytest.mark.parametrize("f", FILES, ids=lambda f: f.stem)
@pytest.mark.parametrize("planner", ["baseline", "adaptive"])
def test_scenario_runs(f, planner):
    m = run_scenario(VENUE, f, planner=planner, total=400)
    assert m["arrived_share"] == 1.0
    assert m["stuck"] == 0


def test_bad_arrival_window():
    v = load_venue(VENUE)
    sc = load_scenario(ROOT / "scenarios" / "entry-rush.json", v)
    sc["crowd"]["arrival"] = {"start_s": 500, "end_s": 100}
    assert any("arrival" in e for e in scenario_errors(sc, v))
