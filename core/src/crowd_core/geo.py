"""Convert between GPS (lat, lon) and venue coordinates (metres, x east, y north).

A venue may carry an `anchor`: the lat/lon of local point (0, 0) and `rotation_deg`, how far the
venue's +y axis is turned clockwise from true north (0 means +y points north). Distances over a
venue (a few kilometres at most) are small enough for a flat-earth approximation.
"""
from __future__ import annotations

import math
from typing import Any

EARTH_RADIUS_M = 6_371_008.8


def _rot(anchor: dict[str, Any]) -> float:
    return math.radians(anchor.get("rotation_deg", 0.0))


def to_local(anchor: dict[str, Any], lat: float, lon: float) -> tuple[float, float]:
    east = math.radians(lon - anchor["lon"]) * EARTH_RADIUS_M * math.cos(math.radians(anchor["lat"]))
    north = math.radians(lat - anchor["lat"]) * EARTH_RADIUS_M
    t = _rot(anchor)
    return east * math.cos(t) - north * math.sin(t), east * math.sin(t) + north * math.cos(t)


def to_latlon(anchor: dict[str, Any], x: float, y: float) -> tuple[float, float]:
    t = _rot(anchor)
    east = x * math.cos(t) + y * math.sin(t)
    north = -x * math.sin(t) + y * math.cos(t)
    lat = anchor["lat"] + math.degrees(north / EARTH_RADIUS_M)
    lon = anchor["lon"] + math.degrees(east / (EARTH_RADIUS_M * math.cos(math.radians(anchor["lat"]))))
    return lat, lon
