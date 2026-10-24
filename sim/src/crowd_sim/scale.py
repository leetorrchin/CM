"""Time planners on a large crowd: python -m crowd_sim.scale --total 50000 [--run]"""
from __future__ import annotations

import argparse
import time

from crowd_core.graph import compile_venue
from crowd_core.optimiser import AdaptivePlanner, FlowPlanner, QueueAwarePlanner
from crowd_core.planner import BaselinePlanner
from crowd_core.state import EntityState, LiveState

from .engine import Simulation
from .venuegen import VenueParams, generate_scenarios, generate_venue


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--total", type=int, default=50000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--run", action="store_true", help="also run the full evacuation simulation")
    a = ap.parse_args()
    v = generate_venue(VenueParams(seed=a.seed))
    vg = compile_venue(v)
    zones = sorted(vg.zones)
    ents = [EntityState(f"p{i:06d}", zones[i % len(zones)], "nearest_safe") for i in range(a.total)]
    for mode in ("normal", "evacuation"):
        st = LiveState("2026-01-01T00:00:00Z", mode, ents,
                       zone_counts={z: a.total / len(zones) for z in zones})
        for cls in (BaselinePlanner, QueueAwarePlanner, FlowPlanner, AdaptivePlanner):
            p = cls()
            t = time.perf_counter(); p.plan(vg, st); t1 = time.perf_counter() - t
            t = time.perf_counter(); p.plan(vg, st); t2 = time.perf_counter() - t
            print(f"{mode:10} {p.name:24} first {t1:6.2f}s  second {t2:6.2f}s", flush=True)
    if a.run:
        sc = generate_scenarios(v, total=a.total)["evacuation-blocked-exit"]
        for name, cls in (("baseline", BaselinePlanner), ("adaptive", AdaptivePlanner)):
            t = time.perf_counter()
            m = Simulation(vg, sc, cls()).run()
            print(f"sim {name}: wall {time.perf_counter()-t:.0f}s clearance {m['clearance_s']} "
                  f"mean {m['travel_time_mean_s']} p95 {m['travel_time_p95_s']}", flush=True)


if __name__ == "__main__":
    main()
