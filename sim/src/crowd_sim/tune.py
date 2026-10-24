"""Grid search for QueueAwarePlanner settings on generated venues.

    python -m crowd_sim.tune --seeds 3 7 11 --total 3000
Score per run: evacuation = clearance, others = mean travel; reported relative to baseline (lower is better).
"""
from __future__ import annotations

import argparse
import itertools
import statistics

from crowd_core.graph import compile_venue
from crowd_core.optimiser import QueueAwarePlanner
from crowd_core.planner import BaselinePlanner

from .engine import Simulation
from .venuegen import VenueParams, generate_scenarios, generate_venue


def score(m: dict, sid: str) -> float:
    return m["clearance_s"] if sid.startswith("evac") else m["travel_time_mean_s"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[3, 7, 11])
    ap.add_argument("--total", type=int, default=3000)
    ap.add_argument("--weights", type=float, nargs="+", default=[0.25, 0.5, 1.0, 2.0])
    ap.add_argument("--iters", type=int, nargs="+", default=[4, 8])
    a = ap.parse_args()
    cases = []
    for seed in a.seeds:
        for bn in (0.2, 0.5, 0.8):
            v = generate_venue(VenueParams(seed=seed, bottleneck=bn))
            for sid, sc in generate_scenarios(v, total=a.total).items():
                if sid != "stage-change":
                    cases.append((v, sid, sc))
    base = [score(Simulation(compile_venue(v), sc, BaselinePlanner()).run(), sid) for v, sid, sc in cases]
    for w, k in itertools.product(a.weights, a.iters):
        rel = []
        for (v, sid, sc), b in zip(cases, base):
            m = Simulation(compile_venue(v), sc, QueueAwarePlanner(iterations=k, congestion_weight=w)).run()
            rel.append(score(m, sid) / b)
        print(f"weight={w} iters={k}: mean ratio vs baseline {statistics.mean(rel):.3f} "
              f"(worst {max(rel):.3f}, best {min(rel):.3f})", flush=True)


if __name__ == "__main__":
    main()
