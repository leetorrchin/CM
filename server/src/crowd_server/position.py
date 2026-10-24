"""Turn noisy phone positions into a stable zone."""
from __future__ import annotations

from dataclasses import dataclass

from crowd_core.geometry import polygon_distance
from crowd_core.positioning import snap_to_zone

MAX_ACCURACY_M = 50.0     # ignore fixes worse than this
OUTSIDE_M = 80.0          # further than this from every zone: not at the venue
HYSTERESIS_M = 2.0        # stay in the current zone while this close to it
CONFIRM = 2               # consecutive reports before moving to a different zone


@dataclass
class Fix:
    status: str             # ok | pending | low_accuracy | outside_venue
    zone: str | None        # the zone the guest is now considered to be in
    changed: bool = False
    off_venue_m: float = 0.0


class PositionFilter:
    def __init__(self, venue: dict) -> None:
        self.venue = venue
        self._zones = {z["id"]: z for z in venue["zones"]}
        self.zone: str | None = None
        self._cand: str | None = None
        self._count = 0

    def update(self, x: float, y: float, accuracy_m: float | None = None, level: str | None = None) -> Fix:
        if accuracy_m is not None and accuracy_m > MAX_ACCURACY_M:
            return Fix("low_accuracy", self.zone)
        cand = snap_to_zone(self.venue, x, y, level)
        off = polygon_distance(x, y, self._zones[cand]["polygon"])
        if off > OUTSIDE_M:
            return Fix("outside_venue", self.zone, off_venue_m=off)
        if self.zone is None:
            self.zone = cand
            return Fix("ok", cand, True, off)
        if cand == self.zone:
            self._cand, self._count = None, 0
            return Fix("ok", cand, False, off)
        if polygon_distance(x, y, self._zones[self.zone]["polygon"]) <= HYSTERESIS_M:
            self._cand, self._count = None, 0
            return Fix("ok", self.zone, False, off)
        self._count = self._count + 1 if cand == self._cand else 1
        self._cand = cand
        if self._count >= CONFIRM:
            self.zone, self._cand, self._count = cand, None, 0
            return Fix("ok", cand, True, off)
        return Fix("pending", self.zone, False, off)
