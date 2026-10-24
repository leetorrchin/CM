"""Emulated sensors. They read the simulation's ground truth and degrade it (noise, bias, lag,
dropouts, outages) so the planner and fusion layer can be tested against realistic inputs.

A sensor has `observe(sim, t)` returning a list of (event type, data) pairs for the event log, and
`stats()` with how far its output was from the truth. Sensors use their own random stream, so
turning them on never changes how the crowd behaves.
"""
from __future__ import annotations

import math
import random
from collections import deque
from typing import Any

from crowd_core.geometry import random_point_in_polygon
from crowd_core.positioning import snap_to_zone

SCHEMA_VERSION = "0.1.0"

DEFAULT_CONFIG: dict[str, Any] = {
    "camera": {"rel_sigma": 0.10, "bias": -0.03, "lag_s": 5.0, "period_s": 5.0, "dropout_prob": 0.02},
    "turnstile": {"miss_rate": 0.01, "period_s": 5.0},
    "app_position": {"sigma_m": 8.0, "dropout_prob": 0.05, "sample_size": 200},
}


class CameraSensor:
    """People counts for the zones a camera covers, as a noisy and delayed estimate."""

    def __init__(self, site: dict, rng: random.Random, rel_sigma: float = 0.10, bias: float = 0.0,
                 lag_s: float = 5.0, period_s: float = 5.0, dropout_prob: float = 0.0,
                 outages: list[dict] | None = None) -> None:
        self.id = site["id"]
        self.zones = [c["id"] for c in site["covers"] if c["kind"] == "zone"]
        self.rng, self.rel_sigma, self.bias = rng, rel_sigma, bias
        self.lag_s, self.period_s, self.dropout_prob = lag_s, period_s, dropout_prob
        self.outages = [o for o in (outages or []) if o.get("site") in (None, self.id)]
        self.history: deque[tuple[float, dict[str, int]]] = deque()
        self.next_emit = 0.0
        self.sent = self.dropped = 0
        self.abs_err = self.truth = 0.0

    def observe(self, sim, t: float) -> list[tuple[str, dict]]:
        self.history.append((t, {z: sim.occ[z] for z in self.zones}))
        cutoff = t - self.lag_s
        seen = self.history[0][1]  # the latest snapshot at least `lag_s` old (else the oldest we have)
        for ts, snap in self.history:
            if ts > cutoff:
                break
            seen = snap
        while len(self.history) > 1 and self.history[1][0] <= cutoff:
            self.history.popleft()
        if t < self.next_emit:
            return []
        self.next_emit = t + self.period_s
        if any(o["from_s"] <= t < o["to_s"] for o in self.outages):
            self.dropped += 1
            return []
        if self.rng.random() < self.dropout_prob:
            self.dropped += 1
            return []
        out = []
        for z in self.zones:
            true = seen[z]
            noisy = max(0, round(true * (1 + self.bias) * (1 + self.rng.gauss(0, self.rel_sigma))))
            now_true = sim.occ[z]
            self.abs_err += abs(noisy - now_true)
            self.truth += now_true
            out.append(("reading", {
                "schema_version": SCHEMA_VERSION, "source_id": self.id, "source_type": "camera",
                "target": {"kind": "zone", "id": z}, "timestamp": sim.clock.iso(t),
                "count": int(noisy), "confidence": round(max(0.05, 1 - 2 * self.rel_sigma), 2)}))
        self.sent += 1
        return out

    def stats(self) -> dict[str, Any]:
        return {"kind": "camera", "readings": self.sent, "dropped": self.dropped,
                "mean_abs_error_share": round(self.abs_err / self.truth, 4) if self.truth else 0.0}


class TurnstileSensor:
    """Crossings per second through a threshold, in its forward direction, with a small miss rate."""

    def __init__(self, site: dict, rng: random.Random, miss_rate: float = 0.01, period_s: float = 5.0) -> None:
        self.id = site["id"]
        self.thresholds = [c["id"] for c in site["covers"] if c["kind"] == "threshold"]
        self.rng, self.miss_rate, self.period_s = rng, miss_rate, period_s
        self.last_t = 0.0
        self.last_counts: dict[str, int] = {}
        self.next_emit = period_s
        self.true_total = self.counted_total = 0

    def observe(self, sim, t: float) -> list[tuple[str, dict]]:
        if t < self.next_emit:
            return []
        dt = t - self.last_t
        out = []
        for tid in self.thresholds:
            th = sim.vg.thresholds[tid]
            key = f"{tid}:{th['from_zone']}->{th['to_zone']}"
            now = sim.crossings.get(key, 0)
            n = now - self.last_counts.get(key, 0)
            self.last_counts[key] = now
            sd = math.sqrt(n * self.miss_rate * (1 - self.miss_rate))
            counted = max(0, round(n * (1 - self.miss_rate) + self.rng.gauss(0, sd)))
            self.true_total += n
            self.counted_total += counted
            out.append(("reading", {
                "schema_version": SCHEMA_VERSION, "source_id": self.id, "source_type": "turnstile",
                "target": {"kind": "threshold", "id": tid}, "timestamp": sim.clock.iso(t),
                "flow_pp_s": round(counted / dt, 4), "confidence": 0.95}))
        self.last_t, self.next_emit = t, t + self.period_s
        return out

    def stats(self) -> dict[str, Any]:
        err = abs(self.counted_total - self.true_total) / self.true_total if self.true_total else 0.0
        return {"kind": "turnstile", "true_crossings": self.true_total,
                "counted_crossings": self.counted_total, "count_error_share": round(err, 4)}


class AppPositionEmulator:
    """GPS-style error on what the app reports. Measures how often the reported position falls in the
    wrong zone, using a random sample of app users each time (reports are only logged if asked)."""

    def __init__(self, venue: dict, rng: random.Random, sigma_m: float = 8.0, dropout_prob: float = 0.05,
                 sample_size: int = 200, emit_updates: bool = False) -> None:
        self.venue, self.rng, self.sigma, self.dropout = venue, rng, sigma_m, dropout_prob
        self.sample_size, self.emit_updates = sample_size, emit_updates
        self.zones = {z["id"]: z for z in venue["zones"]}
        self.true_pos: dict[str, tuple[str, tuple[float, float]]] = {}
        self.reports = self.dropped = self.wrong = 0
        self.err_sum = 0.0

    def observe(self, sim, t: float) -> list[tuple[str, dict]]:
        pool = [p for p in sim.people if p.has_app and p.state in ("wait", "undecided", "stuck", "queued", "done")]
        if not pool:
            return []
        out = []
        for p in self.rng.sample(pool, min(self.sample_size, len(pool))):
            cached = self.true_pos.get(p.id)
            if cached is None or cached[0] != p.zone:
                z = self.zones[p.zone]
                cached = (p.zone, random_point_in_polygon(z["polygon"], self.rng))
                self.true_pos[p.id] = cached
            if self.rng.random() < self.dropout:
                self.dropped += 1
                continue
            x, y = cached[1]
            nx, ny = x + self.rng.gauss(0, self.sigma), y + self.rng.gauss(0, self.sigma)
            level = self.zones[p.zone]["level"]
            snapped = snap_to_zone(self.venue, nx, ny, level)
            self.reports += 1
            self.err_sum += math.hypot(nx - x, ny - y)
            self.wrong += snapped != p.zone
            if self.emit_updates:
                out.append(("position_update", {
                    "schema_version": SCHEMA_VERSION, "entity_id": p.id, "timestamp": sim.clock.iso(t),
                    "position": [round(nx, 2), round(ny, 2)], "level": level,
                    "accuracy_m": round(1.5 * self.sigma, 1), "source": "emulated"}))
        return out

    def stats(self) -> dict[str, Any]:
        return {"kind": "app_position", "reports": self.reports, "dropped": self.dropped,
                "mean_error_m": round(self.err_sum / self.reports, 2) if self.reports else 0.0,
                "wrong_zone_share": round(self.wrong / self.reports, 4) if self.reports else 0.0}


def build_sensors(venue: dict, config: dict | None, seed: int) -> list:
    """Create the sensors a scenario asks for. Camera and turnstile ones follow the venue's sensor sites."""
    if not config:
        return []
    rng = random.Random(f"{seed}-sensors")
    out: list = []
    for site in venue.get("sensor_sites", []):
        if site["kind"] == "camera" and "camera" in config:
            out.append(CameraSensor(site, random.Random(rng.random()), **config["camera"]))
        elif site["kind"] == "turnstile" and "turnstile" in config:
            out.append(TurnstileSensor(site, random.Random(rng.random()), **config["turnstile"]))
    if "app_position" in config:
        out.append(AppPositionEmulator(venue, random.Random(rng.random()), **config["app_position"]))
    return out
