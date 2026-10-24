"""Venue loading and semantic validation (checks JSON Schema cannot express)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import networkx as nx

from .geometry import polygon_area
from .schemas import schema_errors


def semantic_errors(v: dict[str, Any]) -> list[str]:
    errs: list[str] = []

    def ids(section: str) -> list[str]:
        return [x["id"] for x in v.get(section, [])]

    for section in ("levels", "zones", "thresholds", "pathways", "destinations", "sensor_sites"):
        seen: set[str] = set()
        for i in ids(section):
            if i in seen:
                errs.append(f"{section}: duplicate id '{i}'")
            seen.add(i)

    levels, zones, thresholds = set(ids("levels")), set(ids("zones")), set(ids("thresholds"))
    zone_by_id = {z["id"]: z for z in v["zones"]}

    for z in v["zones"]:
        if z["level"] not in levels:
            errs.append(f"zone '{z['id']}': unknown level '{z['level']}'")
        if polygon_area(z["polygon"]) <= 0:
            errs.append(f"zone '{z['id']}': polygon has zero area")

    for t in v["thresholds"]:
        for end in ("from_zone", "to_zone"):
            if t[end] not in zones:
                errs.append(f"threshold '{t['id']}': unknown {end} '{t[end]}'")
        if t["from_zone"] == t["to_zone"]:
            errs.append(f"threshold '{t['id']}': connects a zone to itself")
        (x1, y1), (x2, y2) = t["segment"]
        if ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 == 0:
            errs.append(f"threshold '{t['id']}': zero-length segment")
        a, b = zone_by_id.get(t["from_zone"]), zone_by_id.get(t["to_zone"])
        if a and b and a["level"] != b["level"] and t["kind"] not in ("stairs", "ramp"):
            errs.append(f"threshold '{t['id']}': connects levels but kind is '{t['kind']}'")
        if a and b and a["level"] == b["level"] and t["kind"] in ("stairs", "ramp"):
            errs.append(f"threshold '{t['id']}': {t['kind']} should connect different levels")

    for p in v.get("pathways", []):
        for z in p["zones"]:
            if z not in zones:
                errs.append(f"pathway '{p['id']}': unknown zone '{z}'")

    for d in v["destinations"]:
        if d["zone"] not in zones:
            errs.append(f"destination '{d['id']}': unknown zone '{d['zone']}'")

    for s in v.get("sensor_sites", []):
        for c in s["covers"]:
            known = zones if c["kind"] == "zone" else thresholds
            if c["id"] not in known:
                errs.append(f"sensor site '{s['id']}': unknown {c['kind']} '{c['id']}'")

    # Every zone must be able to reach a safe destination (needed for evacuation).
    if not errs:
        g = nx.DiGraph()
        g.add_nodes_from(zones)
        for t in v["thresholds"]:
            g.add_edge(t["from_zone"], t["to_zone"])
            if not t.get("one_way", False):
                g.add_edge(t["to_zone"], t["from_zone"])
        safe = {d["zone"] for d in v["destinations"] if d.get("safe")}
        if not safe:
            errs.append("no destination is marked safe: evacuation has nowhere to go")
        for z in zones:
            if safe and not any(nx.has_path(g, z, s) for s in safe):
                errs.append(f"zone '{z}' cannot reach any safe destination")
    return errs


def validate_venue(v: dict[str, Any]) -> list[str]:
    errs = schema_errors("venue", v)
    return errs if errs else semantic_errors(v)


def load_venue(path: str | Path) -> dict[str, Any]:
    v = json.loads(Path(path).read_text())
    errs = validate_venue(v)
    if errs:
        raise ValueError(f"invalid venue {path}:\n  " + "\n  ".join(errs))
    return v


def main(argv: list[str]) -> int:
    bad = 0
    for p in argv:
        errs = validate_venue(json.loads(Path(p).read_text()))
        print(f"{p}: {'ok' if not errs else 'INVALID'}")
        for e in errs:
            print(f"  {e}")
        bad += bool(errs)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
