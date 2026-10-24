"""Procedural festival venues built from rectangular blocks on a grid.

Layout (x east, y north, metres): a main field in the middle; stage fronts with an upper grandstand
along the north edge; food courts along the south edge; entry plazas and an assembly field on the
west; exit lanes on the east. Blocks share edges, and thresholds sit on the shared edge, so the
result is always connected and passes core validation. Same params give the same venue.
"""
from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from crowd_core.scenario import scenario_errors
from crowd_core.venue import validate_venue

VERSION = "0.1.0"
STAGE_NAMES = "ABCDEFGH"


@dataclass
class VenueParams:
    seed: int = 0
    stages: int = 3
    entries: int = 3
    exits: int = 3
    food_courts: int = 2
    grandstands: bool = True
    bottleneck: float = 0.5  # 0 = every exit wide, 1 = exit 1 is a very narrow gate

    def check(self) -> None:
        if not (1 <= self.stages <= 8 and 1 <= self.entries <= 8 and 1 <= self.exits <= 8
                and 1 <= self.food_courts <= 8):
            raise ValueError("stages, entries, exits and food_courts must each be between 1 and 8")
        if not 0.0 <= self.bottleneck <= 1.0:
            raise ValueError("bottleneck must be between 0 and 1")


def _rect(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def generate_venue(p: VenueParams) -> dict[str, Any]:
    p.check()
    rng = random.Random(p.seed)
    n_side = max(p.entries, p.exits)
    W = max(rng.uniform(220, 320), 70 * p.stages + 20, 70 * p.food_courts + 20)
    H = max(rng.uniform(140, 200), 40 * n_side + 20)
    W, H = round(W), round(H)
    STAGE_D, GRAND_D, FOOD_D, PLAZA_D, LANE_D = 50, 25, 35, 40, 30

    zones: list[dict] = []
    thresholds: list[dict] = []
    destinations: list[dict] = []
    sensors: list[dict] = []
    pathways: list[dict] = []

    zones.append({"id": "main_field", "name": "Main field", "level": "ground", "kind": "open_area",
                  "polygon": _rect(0, 0, W, H)})

    # stages (north), each with an upper grandstand
    slot = W / p.stages
    for i in range(p.stages):
        x0, x1 = round(i * slot + 10), round((i + 1) * slot - 10)
        n = i + 1
        name = f"Stage {STAGE_NAMES[i]}"
        zones.append({"id": f"stage_{n}", "name": f"{name} front", "level": "ground",
                      "kind": "stage_front", "polygon": _rect(x0, H, x1, H + STAGE_D),
                      "capacity": {"max_density_pp_m2": 4.0}})
        thresholds.append({"id": f"t_field_stage_{n}", "kind": "opening", "from_zone": "main_field",
                           "to_zone": f"stage_{n}", "segment": [[x0 + 12, H], [x1 - 12, H]],
                           "width_m": x1 - x0 - 24})
        destinations.append({"id": f"stage_{n}", "name": name, "kind": "stage", "zone": f"stage_{n}"})
        sensors.append({"id": f"cam_stage_{n}", "kind": "camera",
                        "covers": [{"kind": "zone", "id": f"stage_{n}"}]})
        if p.grandstands:
            y = H + STAGE_D
            zones.append({"id": f"grandstand_{n}", "name": f"{name} grandstand", "level": "upper",
                          "kind": "seating", "polygon": _rect(x0, y, x1, y + GRAND_D)})
            thresholds.append({"id": f"t_stairs_{n}", "kind": "stairs", "from_zone": f"stage_{n}",
                               "to_zone": f"grandstand_{n}", "segment": [[x0 + 4, y], [x0 + 10, y]],
                               "width_m": 6, "step_free": False})
            thresholds.append({"id": f"t_ramp_{n}", "kind": "ramp", "from_zone": f"stage_{n}",
                               "to_zone": f"grandstand_{n}", "segment": [[x1 - 8, y], [x1 - 4, y]],
                               "width_m": 4})

    # food courts (south)
    slot = W / p.food_courts
    for i in range(p.food_courts):
        x0, x1 = round(i * slot + 10), round((i + 1) * slot - 10)
        n = i + 1
        zones.append({"id": f"food_{n}", "name": f"Food court {n}", "level": "ground", "kind": "concourse",
                      "polygon": _rect(x0, -FOOD_D, x1, 0)})
        thresholds.append({"id": f"t_field_food_{n}", "kind": "opening", "from_zone": "main_field",
                           "to_zone": f"food_{n}", "segment": [[x0 + 8, 0], [x1 - 8, 0]],
                           "width_m": x1 - x0 - 16})
        destinations.append({"id": f"food_{n}", "name": f"Food stalls {n}", "kind": "food", "zone": f"food_{n}"})
        destinations.append({"id": f"toilets_{n}", "name": f"Toilets {n}", "kind": "toilets", "zone": f"food_{n}"})
    destinations.append({"id": "first_aid", "name": "First aid", "kind": "medical", "zone": "food_1"})

    # entry plazas (west) with gates, and the assembly field behind the first plaza
    slot = H / p.entries
    for i in range(p.entries):
        y0, y1 = round(i * slot + 5), round((i + 1) * slot - 5)
        n, yc = i + 1, (y0 + y1) / 2
        gate_w = round(min(rng.uniform(6, 12), (y1 - y0) - 2), 1)
        zones.append({"id": f"plaza_{n}", "name": f"Entry plaza {n}", "level": "ground", "kind": "open_area",
                      "polygon": _rect(-PLAZA_D, y0, 0, y1)})
        thresholds.append({"id": f"t_gate_{n}", "name": f"Gate {n}", "kind": "gate",
                           "from_zone": f"plaza_{n}", "to_zone": "main_field",
                           "segment": [[0, yc - gate_w / 2], [0, yc + gate_w / 2]], "width_m": gate_w})
        destinations.append({"id": f"gate_entry_{n}", "name": f"Entry {n}", "kind": "entry", "zone": f"plaza_{n}"})
        sensors.append({"id": f"turnstile_gate_{n}", "kind": "turnstile",
                        "covers": [{"kind": "threshold", "id": f"t_gate_{n}"}]})
    destinations.append({"id": "meet_plaza", "name": "Meeting point", "kind": "meeting_point", "zone": "plaza_1"})
    y0, y1 = 5, round(slot - 5)
    zones.append({"id": "assembly_west", "name": "Western assembly field", "level": "ground",
                  "kind": "assembly_point", "polygon": _rect(-PLAZA_D - 70, y0, -PLAZA_D, y1)})
    yc = (y0 + y1) / 2
    thresholds.append({"id": "t_plaza_assembly", "kind": "opening", "from_zone": "plaza_1",
                       "to_zone": "assembly_west",
                       "segment": [[-PLAZA_D, yc - min(5, (y1 - y0) / 2 - 1)], [-PLAZA_D, yc + min(5, (y1 - y0) / 2 - 1)]],
                       "width_m": 2 * min(5, (y1 - y0) / 2 - 1)})
    destinations.append({"id": "assembly_west", "name": "Western assembly", "kind": "assembly_point",
                         "zone": "assembly_west", "safe": True})

    # exit lanes (east); exit 1 is the one the bottleneck setting squeezes
    slot = H / p.exits
    for i in range(p.exits):
        y0, y1 = round(i * slot + 4), round((i + 1) * slot - 4)
        n, yc = i + 1, (y0 + y1) / 2
        wide = min(20.0, (y1 - y0) - 2)
        width = round(wide - (wide - 4.0) * p.bottleneck if i == 0 else wide, 1)
        zones.append({"id": f"exit_lane_{n}", "name": f"Exit lane {n}", "level": "ground", "kind": "corridor",
                      "polygon": _rect(W, y0, W + LANE_D, y1)})
        thresholds.append({"id": f"t_field_exit_{n}", "name": f"Exit gate {n}", "kind": "gate",
                           "from_zone": "main_field", "to_zone": f"exit_lane_{n}",
                           "segment": [[W, yc - width / 2], [W, yc + width / 2]], "width_m": width})
        destinations.append({"id": f"exit_{n}", "name": f"Exit {n}", "kind": "exit",
                             "zone": f"exit_lane_{n}", "safe": True})
        pathways.append({"id": f"evac_{n}", "name": f"Evacuation route {n}",
                         "zones": ["main_field", f"exit_lane_{n}"], "one_way": True, "purpose": "evacuation"})
    sensors.append({"id": "cam_field", "kind": "camera", "covers": [{"kind": "zone", "id": "main_field"}]})

    venue = {
        "schema_version": VERSION,
        "id": f"gen-{p.seed}",
        "name": f"Generated festival (seed {p.seed}, {p.stages} stages, {p.entries} gates, {p.exits} exits)",
        "units": "metres",
        "levels": [{"id": "ground", "name": "Ground", "elevation_m": 0},
                   {"id": "upper", "name": "Grandstand deck", "elevation_m": 4}],
        "zones": zones, "thresholds": thresholds, "pathways": pathways,
        "destinations": destinations, "sensor_sites": sensors,
    }
    if not p.grandstands:
        venue["levels"] = venue["levels"][:1]
    errs = validate_venue(venue)
    if errs:  # a generator bug, never a user error
        raise AssertionError(f"generated venue is invalid: {errs}")
    return venue


def _shares(parts: list[tuple[list[str], float]]) -> list[tuple[str, float]]:
    """Spread each group's share equally over its members, merge, and make the total exactly 1."""
    merged: dict[str, float] = {}
    for items, share in parts:
        for k in items:
            merged[k] = merged.get(k, 0.0) + share / len(items)
    out = [(k, round(v, 6)) for k, v in merged.items()]
    out[-1] = (out[-1][0], round(1.0 - sum(v for _, v in out[:-1]), 6))
    return out


def generate_scenarios(venue: dict[str, Any], total: int = 8000, seed: int = 42) -> dict[str, dict]:
    """The three standard scenarios for any generated venue."""
    zids = lambda prefix: [z["id"] for z in venue["zones"] if z["id"].startswith(prefix)]  # noqa: E731
    dids = lambda kind: [d["id"] for d in venue["destinations"] if d["kind"] == kind]  # noqa: E731
    stages, foods, plazas, grands = zids("stage_"), zids("food_"), zids("plaza_"), zids("grandstand_")
    exits = dids("exit")
    top = grands or ["main_field"]

    def crowd(spawn, dest):
        return {"total": total,
                "spawn": [{"zone": k, "share": v} for k, v in _shares(spawn)],
                "destinations": [{"id": k, "share": v} for k, v in _shares(dest)]}

    base = {"schema_version": VERSION, "venue": venue["id"], "seed": seed,
            "groups": {"share_in_groups": 0.6, "mean_size": 3.0},
            "compliance": {"normal": 0.7, "egress": 0.7, "evacuation": 0.85}}
    narrow = min((t for t in venue["thresholds"] if t["id"].startswith("t_field_exit_")),
                 key=lambda t: t["width_m"])["id"]

    out = {
        "egress-end-of-night": {
            **base, "id": "egress-end-of-night", "start_time": "2026-11-14T22:00:00+11:00",
            "description": "Headline act ends and most of the crowd heads for the exits.",
            "duration_s": 1800, "mode": "egress",
            "crowd": crowd([(stages, 0.6), (["main_field"], 0.3), (foods, 0.1)], [(exits, 1.0)]),
            "events": []},
        "stage-change": {
            **base, "id": "stage-change", "start_time": "2026-11-14T19:30:00+11:00",
            "description": "Set ends and the crowd disperses to food, toilets, other stages and meeting points.",
            "duration_s": 1200, "mode": "normal",
            "crowd": crowd([(stages, 0.75), (["main_field"], 0.15), (top, 0.10)],
                           [(dids("food"), 0.35), (dids("toilets"), 0.25), (dids("stage"), 0.25),
                            (["meet_plaza"], 0.10), (["first_aid"], 0.05)]),
            "events": []},
        "evacuation-blocked-exit": {
            **base, "id": "evacuation-blocked-exit", "start_time": "2026-11-14T21:00:00+11:00",
            "description": "Normal event, then evacuation is declared at 5 minutes and the narrowest exit is blocked.",
            "duration_s": 1800, "mode": "normal",
            "crowd": crowd([(stages, 0.4), (["main_field"], 0.3), (foods, 0.15), (plazas, 0.10), (top, 0.05)],
                           [(dids("stage"), 0.5), (dids("food"), 0.3), (dids("toilets"), 0.2)]),
            "events": [{"at_s": 300, "type": "mode_change", "mode": "evacuation", "destination": "nearest_safe"},
                       {"at_s": 300, "type": "closure", "threshold": narrow}]},
    }
    for sc in out.values():
        errs = scenario_errors(sc, venue)
        if errs:
            raise AssertionError(f"generated scenario {sc['id']} is invalid: {errs}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a festival venue and its three scenarios")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--stages", type=int, default=3)
    ap.add_argument("--entries", type=int, default=3)
    ap.add_argument("--exits", type=int, default=3)
    ap.add_argument("--food-courts", type=int, default=2)
    ap.add_argument("--no-grandstands", action="store_true")
    ap.add_argument("--bottleneck", type=float, default=0.5)
    ap.add_argument("--total", type=int, default=8000)
    ap.add_argument("--out", help="venue file, default venues/generated/gen-<seed>.json")
    ap.add_argument("--scenarios-dir", help="default scenarios/generated/gen-<seed>/")
    a = ap.parse_args()
    params = VenueParams(a.seed, a.stages, a.entries, a.exits, a.food_courts, not a.no_grandstands, a.bottleneck)
    venue = generate_venue(params)
    out = Path(a.out or f"venues/generated/{venue['id']}.json")
    sdir = Path(a.scenarios_dir or f"scenarios/generated/{venue['id']}")
    out.parent.mkdir(parents=True, exist_ok=True)
    sdir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(venue, indent=2) + "\n")
    for name, sc in generate_scenarios(venue, a.total).items():
        (sdir / f"{name}.json").write_text(json.dumps(sc, indent=2) + "\n")
    print(f"venue: {out}\nscenarios: {sdir}/\nparams: {asdict(params)}")


if __name__ == "__main__":
    main()
