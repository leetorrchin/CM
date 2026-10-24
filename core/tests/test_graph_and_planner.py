import json
from pathlib import Path

import pytest

from crowd_core.graph import compile_venue
from crowd_core.planner import BaselinePlanner
from crowd_core.scenario import load_scenario, scenario_errors
from crowd_core.schemas import schema_errors
from crowd_core.state import EntityState, GroupState, LiveState
from crowd_core.venue import load_venue

ROOT = Path(__file__).resolve().parents[2]
TS = "2026-10-24T18:00:00+11:00"


@pytest.fixture(scope="module")
def vg():
    return compile_venue(load_venue(ROOT / "venues" / "example-minimal-festival.json"))


def plan_one(vg, zone, dest, closed=(), step_free=False):
    p = BaselinePlanner()
    state = LiveState(TS, entities=[EntityState("e1", zone, dest, needs_step_free=step_free)],
                      closed_thresholds=set(closed))
    plan = p.plan(vg, state)
    assert schema_errors("plan", plan) == []
    return plan, p


def test_graph_shape(vg):
    assert set(vg.graph.nodes) == set(vg.zones)
    # 8 thresholds, none one-way -> 16 directed edges
    assert vg.graph.number_of_edges() == 16
    # main_field is 140 x 120 m at default 3 pp/m2
    assert vg.zone_capacity["main_field"] == pytest.approx(140 * 120 * 3.0)
    # stage zone overrides density to 4.0
    assert vg.zone_capacity["stage_a_front"] == pytest.approx(60 * 60 * 4.0)


def test_bottleneck_capacity(vg):
    e = vg.graph["main_field"]["exit_lane_south"]["t_field_exit_south"]
    assert e["capacity_pp_s"] == pytest.approx(6 * 1.3)
    stairs = vg.graph["stage_a_front"]["grandstand"]["t_stage_grandstand_stairs"]
    assert stairs["travel_time_s"] > 0 and stairs["capacity_pp_s"] == pytest.approx(3 * 1.3 * 0.7)


def test_route_to_south_exit(vg):
    plan, _ = plan_one(vg, "stage_a_front", "exit_south")
    a = plan["assignments"][0]
    assert a["next_threshold"] == "t_field_stage" and a["destination_id"] == "exit_south"
    plan, _ = plan_one(vg, "main_field", "exit_south")
    assert plan["assignments"][0]["next_threshold"] == "t_field_exit_south"


def test_arrived_has_no_next_threshold(vg):
    plan, _ = plan_one(vg, "exit_lane_south", "exit_south")
    a = plan["assignments"][0]
    assert "next_threshold" not in a and a["eta_s"] == 0


def test_closure_forces_detour(vg):
    plan, _ = plan_one(vg, "main_field", "nearest_safe", closed={"t_field_exit_south"})
    a = plan["assignments"][0]
    assert a["destination_id"] != "exit_south"
    assert a["next_threshold"] in {"t_field_food", "t_plaza_field"}


def test_nearest_safe_resolves_to_real_destination(vg):
    plan, _ = plan_one(vg, "main_field", "nearest_safe")
    assert plan["assignments"][0]["destination_id"] in {"exit_south", "exit_north", "assembly_west"}


def test_step_free_avoids_stairs(vg):
    plan, _ = plan_one(vg, "stage_a_front", "stage_a")
    plan2, _ = plan_one(vg, "stage_a_front", "food", step_free=True)
    assert plan2["assignments"][0]["next_threshold"] == "t_field_stage"
    # grandstand is only step-free via the ramp
    p3, _ = plan_one(vg, "stage_a_front", "gate_entry", step_free=True)
    assert p3["assignments"][0]["next_threshold"] == "t_field_stage"


def test_unroutable_is_reported(vg):
    closed = {"t_plaza_field", "t_plaza_assembly"}
    plan, p = plan_one(vg, "gate_plaza", "exit_south", closed=closed)
    assert plan["assignments"] == [] and p.last_unroutable == ["e1"]


def test_group_in_same_place_gets_one_assignment(vg):
    state = LiveState(TS,
        entities=[EntityState("a", "main_field", "food", group_id="g"),
                  EntityState("b", "main_field", "food", group_id="g"),
                  EntityState("c", "main_field", "food")],
        groups=[GroupState("g", ["a", "b"])])
    plan = BaselinePlanner().plan(vg, state)
    assert schema_errors("plan", plan) == []
    kinds = sorted((x["subject"]["kind"], x["subject"]["id"]) for x in plan["assignments"])
    assert kinds == [("entity", "c"), ("group", "g")]


@pytest.mark.parametrize("name", ["egress-end-of-night", "stage-change", "evacuation-blocked-exit"])
def test_scenarios_are_valid(name):
    venue = load_venue(ROOT / "venues" / "example-minimal-festival.json")
    assert load_scenario(ROOT / "scenarios" / f"{name}.json", venue)["venue"] == venue["id"]


def test_scenario_bad_share_is_caught():
    venue = load_venue(ROOT / "venues" / "example-minimal-festival.json")
    s = json.loads((ROOT / "scenarios" / "egress-end-of-night.json").read_text())
    s["crowd"]["spawn"][0]["share"] = 0.1
    assert any("shares sum" in e for e in scenario_errors(s, venue))
