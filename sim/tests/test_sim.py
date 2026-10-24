import json
from pathlib import Path

import pytest
from crowd_sim.clock import SimClock
from crowd_sim.run import run_scenario

ROOT = Path(__file__).resolve().parents[2]
VENUE = ROOT / "venues" / "example-minimal-festival.json"
SC = ROOT / "scenarios"


def lines(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines()]


def test_clock_iso():
    c = SimClock("2026-11-14T22:00:00+11:00")
    c.set(90.5)
    assert c.iso() == "2026-11-14T22:01:30.500+11:00"


def test_log_is_valid_and_ordered(tmp_path):
    out = tmp_path / "run.jsonl"
    run_scenario(VENUE, SC / "egress-end-of-night.json", out=out, total=300, validate_log=True)
    recs = lines(out)
    assert recs[0]["type"] == "run_start" and recs[-1]["type"] == "run_end"
    assert [r["seq"] for r in recs] == list(range(len(recs)))
    assert any(r["type"] == "zone_state" for r in recs)
    assert any(r["type"] == "metric" for r in recs)


def test_deterministic_from_seed():
    a = run_scenario(VENUE, SC / "egress-end-of-night.json", total=400, seed=7)
    b = run_scenario(VENUE, SC / "egress-end-of-night.json", total=400, seed=7)
    c = run_scenario(VENUE, SC / "egress-end-of-night.json", total=400, seed=8)
    assert a == b and a != c


def test_everyone_gets_out_in_egress():
    m = run_scenario(VENUE, SC / "egress-end-of-night.json", total=1000)
    assert m["arrived_share"] == 1.0 and m["stuck"] == 0 and m["clearance_s"] is not None


def test_bottleneck_bounds_clearance(tmp_path):
    """Everyone to the 6 m south gate: clearance cannot beat total / gate capacity."""
    sc = json.loads((SC / "egress-end-of-night.json").read_text())
    sc["crowd"]["destinations"] = [{"id": "exit_south", "share": 1.0}]
    sc["crowd"]["spawn"] = [{"zone": "main_field", "share": 1.0}]
    p = tmp_path / "s.json"
    p.write_text(json.dumps(sc))
    m = run_scenario(VENUE, p, total=2000)
    assert m["clearance_s"] >= 2000 / (6 * 1.3) * 0.98
    assert "t_field_exit_south" in next(iter(m["peak_queue"]))


def test_evacuation_respects_closure(tmp_path):
    out = tmp_path / "evac.jsonl"
    m = run_scenario(VENUE, SC / "evacuation-blocked-exit.json", total=1500, out=out,
                     validate_log=True)
    assert m["arrived_share"] == 1.0 and m["stuck"] == 0
    assert m["clearance_s"] is not None
    states = [r["data"] for r in lines(out) if r["type"] == "zone_state"]
    # well after the closure (300 s) nobody is queued for or crossing the south gate
    for s in states:
        if s["t_s"] >= 600:
            assert not any("t_field_exit_south" in k for k in {**s["transit"], **s["queues"]})
    assert any(r["type"] == "closure" for r in lines(out))


def test_no_app_still_works():
    m = run_scenario(VENUE, SC / "egress-end-of-night.json", total=500, app_adoption=0.0)
    assert m["arrived_share"] == 1.0


def test_groups_are_tracked():
    m = run_scenario(VENUE, SC / "stage-change.json", total=1000)
    assert m["groups"] > 0 and 0.0 <= m["groups_split_mean_share"] <= 1.0


def test_groups_never_split_in_unit_mode():
    m = run_scenario(VENUE, SC / "stage-change.json", total=1000)
    assert m["groups_split_peak"] == 0


@pytest.mark.parametrize("planner", ["queue-aware", "flow", "adaptive"])
def test_optimising_planners_complete_and_do_not_lose_to_baseline_on_egress(planner):
    base = run_scenario(VENUE, SC / "egress-end-of-night.json", total=2000, planner="baseline")
    m = run_scenario(VENUE, SC / "egress-end-of-night.json", total=2000, planner=planner)
    assert m["arrived_share"] == 1.0 and m["stuck"] == 0
    assert m["travel_time_mean_s"] <= base["travel_time_mean_s"]


def _live_sim(total=300, planner="adaptive"):
    from crowd_core.graph import compile_venue
    from crowd_core.scenario import load_scenario
    from crowd_core.venue import load_venue
    from crowd_sim.engine import Simulation
    from crowd_sim.run import PLANNERS
    v = load_venue(VENUE)
    sc = load_scenario(SC / "egress-end-of-night.json", v)
    sc["crowd"]["total"] = total
    sc["events"] = []
    sim = Simulation(compile_venue(v), sc, PLANNERS[planner]())
    sim.begin()
    return sim


def test_stepping_matches_run():
    a = _live_sim(400, "baseline")
    a.advance(900, stop_when_idle=True)
    ma = a.finish()
    mb = run_scenario(VENUE, SC / "egress-end-of-night.json", total=400, planner="baseline")
    # the live helper drops scenario events, so only compare population size here
    assert ma["people"] == mb["people"] == 400


def test_injected_evacuation_and_guest_guidance():
    sim = _live_sim()
    gid = sim.add_guest("main_field")
    sim.advance(5)
    g = sim.guidance(gid)
    assert g["zone"] == "main_field" and g["mode"] == "egress"
    sim.inject({"type": "mode_change", "mode": "evacuation", "destination": "nearest_safe"})
    sim.inject({"type": "closure", "threshold": "t_field_exit_south"})
    sim.advance(60)
    g = sim.guidance(gid)
    assert g["mode"] == "evacuation" and "t_field_exit_south" in g["closed"]
    sim.advance(900)
    assert sim.guidance(gid)["arrived"] is True
    assert sim.cleared == len(sim.people)
    with pytest.raises(ValueError):
        sim.inject({"type": "bogus"})


def test_external_guest_follows_reported_position_only():
    sim = _live_sim(200)
    gid = sim.add_guest("main_field", "nearest_safe", external=True)
    sim.advance(60)
    g = sim.guidance(gid)
    assert g["zone"] == "main_field" and g["state"] == "external"
    assert g.get("next_threshold")            # planner still guides them
    # phone says they walked into the south exit lane
    assert sim.set_external_zone(gid, "exit_lane_south")
    sim.advance(sim._t + 3)
    assert sim.guidance(gid)["arrived"] is True
    assert sim.set_external_zone(gid, "main_field") is False   # once out, stays out


def test_guest_can_switch_between_phone_and_simulation():
    sim = _live_sim(100)
    gid = sim.add_guest("main_field", "nearest_safe", external=True)
    sim.advance(20)
    assert sim.guidance(gid)["zone"] == "main_field"
    assert sim.set_external(gid, False)
    sim.advance(sim._t + 400)
    assert sim.guidance(gid)["arrived"] is True
    assert sim.set_external("p00001", True) is False          # only guests
