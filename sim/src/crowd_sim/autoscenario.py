"""A reasonable demo scenario for any valid venue (used for venues drawn in the editor)."""
from __future__ import annotations

from typing import Any

from crowd_core.geometry import polygon_area

from .venuegen import VERSION

CROWD_KINDS = ("open_area", "stage_front", "concourse", "seating", "queue")


def auto_scenario(venue: dict[str, Any], total: int = 3000, seed: int = 42) -> dict[str, Any]:
    zs = [z for z in venue["zones"] if z["kind"] in CROWD_KINDS] or list(venue["zones"])
    areas = [polygon_area(z["polygon"]) for z in zs]
    tot = sum(areas) or 1.0
    spawn = [{"zone": z["id"], "share": a / tot} for z, a in zip(zs, areas)]
    spawn[-1]["share"] = 1.0 - sum(s["share"] for s in spawn[:-1])
    dests = [d["id"] for d in venue["destinations"] if d["kind"] == "exit"] or \
            [d["id"] for d in venue["destinations"] if d.get("safe")]
    share = [1.0 / len(dests)] * len(dests)
    share[-1] = 1.0 - sum(share[:-1])
    return {
        "schema_version": VERSION, "id": "auto-egress", "venue": venue["id"], "seed": seed,
        "description": "Crowd spread over the venue by area, all heading for the exits.",
        "start_time": "2026-11-14T22:00:00+11:00", "duration_s": 3600, "mode": "egress",
        "groups": {"share_in_groups": 0.6, "mean_size": 3.0},
        "compliance": {"normal": 0.7, "egress": 0.7, "evacuation": 0.85},
        "crowd": {"total": total, "spawn": spawn,
                  "destinations": [{"id": d, "share": s} for d, s in zip(dests, share)]},
        "events": []}
