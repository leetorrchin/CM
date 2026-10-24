"""Run planners across scenarios and generated venues and write a comparison table.

    python -m crowd_sim.bench --seeds 3 7 11 --total 3000 --out docs/benchmarks.md

The headline per mode: evacuation = clearance time, egress/normal = mean travel time with p95.
"""
from __future__ import annotations

import argparse
import statistics
from pathlib import Path

from crowd_core.graph import compile_venue
from crowd_core.optimiser import AdaptivePlanner, QueueAwarePlanner
from crowd_core.planner import BaselinePlanner

from .engine import Simulation
from .venuegen import VenueParams, generate_scenarios, generate_venue

PLANNERS = {"baseline": BaselinePlanner, "queue-aware": QueueAwarePlanner, "adaptive": AdaptivePlanner}


def bench(seeds: list[int], total: int, planners: list[str]) -> list[dict]:
    rows = []
    for seed in seeds:
        venue = generate_venue(VenueParams(seed=seed))
        for sid, sc in generate_scenarios(venue, total=total).items():
            for name in planners:
                m = Simulation(compile_venue(venue), sc, PLANNERS[name]()).run()
                rows.append({"venue": venue["id"], "scenario": sid, "planner": name, **m})
    return rows


def table(rows: list[dict]) -> str:
    out = ["| scenario | planner | clearance s | mean travel s | p95 travel s | groups split | venues |",
           "|---|---|---|---|---|---|---|"]
    keys = sorted({(r["scenario"], r["planner"]) for r in rows})
    for sc, pl in keys:
        rs = [r for r in rows if r["scenario"] == sc and r["planner"] == pl]

        def avg(k):
            v = [r[k] for r in rs if r[k] is not None]
            return f"{statistics.mean(v):.0f}" if v else "-"

        split = statistics.mean(r["groups_split_mean_share"] for r in rs)
        out.append(f"| {sc} | {pl} | {avg('clearance_s')} | {avg('travel_time_mean_s')} | "
                   f"{avg('travel_time_p95_s')} | {split:.3f} | {len(rs)} |")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[3, 7, 11])
    ap.add_argument("--total", type=int, default=3000)
    ap.add_argument("--planners", nargs="+", default=list(PLANNERS), choices=list(PLANNERS))
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    t = table(bench(a.seeds, a.total, a.planners))
    print(t)
    if a.out:
        a.out.write_text(f"# Planner benchmarks\n\nGenerated venues, seeds {a.seeds}, {a.total} people, "
                         f"app adoption 1.0. Means across venues.\n\n{t}\n")


if __name__ == "__main__":
    main()
