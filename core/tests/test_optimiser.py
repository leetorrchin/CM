import copy
import json
from pathlib import Path

import pytest

from crowd_core.graph import compile_venue
from crowd_core.optimiser import AdaptivePlanner, FlowPlanner, QueueAwarePlanner
from crowd_core.schemas import schema_errors
from crowd_core.state import EntityState, GroupState, LiveState

ROOT = Path(__file__).resolve().parents[2]
VENUE = json.loads((ROOT / "venues/example-minimal-festival.json").read_text())


def vg(**edit):
    v = copy.deepcopy(VENUE)
    return compile_venue(v)


def state(n, zone, dest, mode="normal", **kw):
    ents = [EntityState(f"p{i:03d}", zone, dest) for i in range(n)]
    return LiveState("2026-01-01T00:00:00Z", mode, ents, [], kw.pop("closed", set()), **kw)


PLANNERS = [QueueAwarePlanner, FlowPlanner, AdaptivePlanner]


@pytest.mark.parametrize("cls", PLANNERS)
def test_plans_are_schema_valid(cls):
    g = vg()
    plan = cls().plan(g, state(40, "main_field", "nearest_safe", "evacuation"))
    assert schema_errors("plan", plan) == []
    assert len(plan["assignments"]) == 40


@pytest.mark.parametrize("cls", PLANNERS)
def test_respects_closure(cls):
    g = vg()
    plan = cls().plan(g, state(30, "main_field", "nearest_safe", "evacuation",
                               closed={"t_field_exit_south"}))
    assert all(a.get("next_threshold") != "t_field_exit_south" for a in plan["assignments"])


def test_splits_across_exits_when_one_is_swamped():
    g = vg()
    # a big crowd with both exits open: some must be sent the longer way
    plan = QueueAwarePlanner().plan(g, state(3000, "main_field", "nearest_safe"))
    used = {a.get("next_threshold") for a in plan["assignments"]}
    assert len(used) >= 2


def test_flexible_exit_redirect_resolves_destination():
    g = vg()
    plan = QueueAwarePlanner().plan(g, state(2000, "main_field", "exit_south",
                                             edge_queues={"t_field_exit_south:main_field->exit_lane_south": 3000}))
    dests = {a["destination_id"] for a in plan["assignments"]}
    assert "exit_north" in dests


def test_groups_stay_one_subject():
    g = vg()
    ents = [EntityState(f"p{i}", "main_field", "nearest_safe", "g1") for i in range(3)]
    st = LiveState("2026-01-01T00:00:00Z", "normal", ents, [GroupState("g1", ["p0", "p1", "p2"])])
    plan = QueueAwarePlanner().plan(g, st)
    assert len(plan["assignments"]) == 1 and plan["assignments"][0]["subject"] == {"kind": "group", "id": "g1"}


def test_deterministic():
    g = vg()
    a = QueueAwarePlanner().plan(g, state(500, "main_field", "nearest_safe"))
    b = QueueAwarePlanner().plan(g, state(500, "main_field", "nearest_safe"))
    assert a == b


def test_flow_horizon_is_lower_bounded_by_bottleneck():
    g = vg()
    fp = FlowPlanner()
    fp.plan(g, state(1200, "main_field", "nearest_safe", "evacuation", closed={"t_field_exit_south"}))
    assert fp.last_horizon_s is not None and fp.last_horizon_s >= 10


def test_unroutable_listed():
    g = vg()
    ql = QueueAwarePlanner()
    closed = {t for t in g.thresholds if t != "nothing"}
    plan = ql.plan(g, state(5, "main_field", "nearest_safe", closed=closed))
    assert plan["assignments"] == [] and len(ql.last_unroutable) == 5
