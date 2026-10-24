"""Simulated clock. Time only moves when the engine sets it, so runs are deterministic."""
from __future__ import annotations

from datetime import datetime, timedelta


class SimClock:
    def __init__(self, start_iso: str) -> None:
        self.start = datetime.fromisoformat(start_iso)
        self.t_s = 0.0

    def set(self, t_s: float) -> None:
        self.t_s = t_s

    def iso(self, t_s: float | None = None) -> str:
        t = self.t_s if t_s is None else t_s
        return (self.start + timedelta(seconds=t)).isoformat(timespec="milliseconds")
