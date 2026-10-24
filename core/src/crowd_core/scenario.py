"""Scenario loading and validation against a venue."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schemas import schema_errors

NEAREST_SAFE = "nearest_safe"


def scenario_errors(s: dict[str, Any], venue: dict[str, Any]) -> list[str]:
    errs = schema_errors("scenario", s)
    if errs:
        return errs
    if s["venue"] != venue["id"]:
        errs.append(f"scenario is for venue '{s['venue']}', got '{venue['id']}'")
    zones = {z["id"] for z in venue["zones"]}
    dests = {d["id"] for d in venue["destinations"]} | {NEAREST_SAFE}
    thresholds = {t["id"] for t in venue["thresholds"]}
    for name, items, key, known in (
        ("spawn", s["crowd"]["spawn"], "zone", zones),
        ("destinations", s["crowd"]["destinations"], "id", dests),
    ):
        total = sum(i["share"] for i in items)
        if abs(total - 1.0) > 1e-6:
            errs.append(f"crowd.{name}: shares sum to {total}, expected 1")
        for i in items:
            if i[key] not in known:
                errs.append(f"crowd.{name}: unknown {key} '{i[key]}'")
    arr = s["crowd"].get("arrival")
    if arr and arr["end_s"] <= arr["start_s"]:
        errs.append("crowd.arrival: end_s must be after start_s")
    if arr and arr["end_s"] > s["duration_s"]:
        errs.append("crowd.arrival: window ends after the scenario does")
    for e in s["events"]:
        if "threshold" in e and e["threshold"] not in thresholds:
            errs.append(f"event at {e['at_s']}s: unknown threshold '{e['threshold']}'")
        if "destination" in e and e["destination"] not in dests:
            errs.append(f"event at {e['at_s']}s: unknown destination '{e['destination']}'")
        if e["at_s"] > s["duration_s"]:
            errs.append(f"event at {e['at_s']}s is after the scenario ends")
    return errs


def load_scenario(path: str | Path, venue: dict[str, Any]) -> dict[str, Any]:
    s = json.loads(Path(path).read_text())
    errs = scenario_errors(s, venue)
    if errs:
        raise ValueError(f"invalid scenario {path}:\n  " + "\n  ".join(errs))
    return s
