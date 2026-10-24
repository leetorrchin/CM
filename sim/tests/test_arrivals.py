import copy
from pathlib import Path

from crowd_core.graph import compile_venue
from crowd_core.scenario import load_scenario
from crowd_core.venue import load_venue
from crowd_sim.engine import Simulation
from crowd_sim.run import PLANNERS

ROOT = Path(__file__).resolve().parents[2]


def make(arrival):
    v = load_venue(ROOT / "venues" / "example-minimal-festival.json")
    sc = copy.deepcopy(load_scenario(ROOT / "scenarios" / "egress-end-of-night.json", v))
    sc["crowd"]["total"] = 300
    sc["crowd"]["arrival"] = arrival
    return Simulation(compile_venue(v), sc, PLANNERS["queue-aware"]())


def test_people_appear_over_window():
    sim = make({"start_s": 60, "end_s": 300})
    sim.begin()
    sim.advance(30)
    assert sum(sim.occ.values()) == 0
    sim.advance(180)
    mid = sum(sim.occ.values()) + sim.cleared
    assert 0 < mid < 300
    sim.advance(1500)
    assert sum(sim.occ.values()) + sim.cleared == 300


def test_not_idle_while_waiting_for_arrivals():
    sim = make({"start_s": 100, "end_s": 120})
    sim.begin()
    sim.advance(50, stop_when_idle=True)
    assert not sim._idle()


def test_groups_arrive_together():
    sim = make({"start_s": 10, "end_s": 400, "shape": "ramp"})
    by_group = {}
    for p in sim.people:
        if p.group:
            by_group.setdefault(p.group, set()).add(p.t_start)
    assert by_group and all(len(v) == 1 for v in by_group.values())
