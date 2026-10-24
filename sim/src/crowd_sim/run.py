"""Run a scenario: python -m crowd_sim.run --venue V --scenario S [--planner baseline] [--out F]"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from crowd_core.graph import compile_venue
from crowd_core.optimiser import AdaptivePlanner, FlowPlanner, QueueAwarePlanner
from crowd_core.planner import BaselinePlanner
from crowd_core.scenario import load_scenario
from crowd_core.venue import load_venue

from .clock import SimClock
from .engine import Simulation
from .eventlog import EventLog
from .sensors import DEFAULT_CONFIG, build_sensors

PLANNERS = {"baseline": BaselinePlanner, "queue-aware": QueueAwarePlanner, "flow": FlowPlanner,
            "adaptive": AdaptivePlanner}


def run_scenario(venue_path, scenario_path, *, planner="baseline", out=None, validate_log=False,
                 total=None, sensors=None, **kwargs):
    """`sensors`: None (use the scenario's own config), True (default sensors), or a config dict."""
    venue = load_venue(venue_path)
    scenario = load_scenario(scenario_path, venue)
    if total is not None:
        scenario["crowd"]["total"] = total
    clock = SimClock(scenario["start_time"])
    seed = kwargs.get("seed") if kwargs.get("seed") is not None else scenario["seed"]
    run_id = f"{scenario['id']}-{planner}-s{seed}"
    log = EventLog(out, run_id, clock, validate=validate_log)
    cfg = DEFAULT_CONFIG if sensors is True else (sensors or scenario.get("sensors"))
    sim = Simulation(compile_venue(venue), scenario, PLANNERS[planner](), log=log, clock=clock,
                     sensors=build_sensors(venue, cfg, seed), **kwargs)
    return sim.run()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--venue", required=True)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--planner", default="baseline", choices=sorted(PLANNERS))
    ap.add_argument("--out", help="event log path (JSONL); default runs/<id>.jsonl")
    ap.add_argument("--dt", type=float, default=1.0)
    ap.add_argument("--replan", type=float, default=10.0)
    ap.add_argument("--app-adoption", type=float)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--total", type=int, help="override crowd size")
    ap.add_argument("--sensors", action="store_true", help="emulate cameras, turnstiles and app position noise")
    a = ap.parse_args()
    sc_id = json.loads(Path(a.scenario).read_text())["id"]
    out = a.out or f"runs/{sc_id}-{a.planner}.jsonl"
    m = run_scenario(a.venue, a.scenario, planner=a.planner, out=out, total=a.total,
                     dt_s=a.dt, replan_s=a.replan, app_adoption=a.app_adoption, seed=a.seed,
                     sensors=True if a.sensors else None)
    print(json.dumps(m, indent=2))
    print(f"event log: {out}")


if __name__ == "__main__":
    main()
