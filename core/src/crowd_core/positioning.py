"""Turn a reported position into a zone (used by the server and by the emulated app)."""
from __future__ import annotations

from typing import Any

from .geometry import polygon_distance


def snap_to_zone(venue: dict[str, Any], x: float, y: float, level: str | None = None) -> str:
    """Zone containing the point, or the nearest zone if the point is outside every zone.

    If `level` is given only zones on that level are considered (GPS cannot tell floors apart, so
    the app reports the level separately).
    """
    best, best_d = None, float("inf")
    for z in venue["zones"]:
        if level is not None and z["level"] != level:
            continue
        d = polygon_distance(x, y, z["polygon"])
        if d < best_d:
            best, best_d = z["id"], d
            if d == 0.0:
                break
    if best is None:
        raise ValueError(f"no zones on level '{level}'")
    return best
