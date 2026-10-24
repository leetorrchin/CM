"""Zone-level crowd simulation.

People are lightweight agents that hop between zones. Each directed threshold has a FIFO queue and
admits people at its capacity (people per second). Crossing takes the edge travel time, slowed by
how crowded the source zone is. Planners give guidance; people with the app follow it with a
probability set by the scenario, everyone else takes the fastest route they would find themselves.
"""
from __future__ import annotations

import heapq
import math
import random
from collections import deque
from typing import Any

from crowd_core.graph import VenueGraph
from crowd_core.planner import BaselinePlanner, Planner, shortest_path_field
from crowd_core.scenario import NEAREST_SAFE
from crowd_core.state import EntityState, GroupState, LiveState

from . import config
from .clock import SimClock
from .eventlog import EventLog
from .population import Person, spawn

JAM_DENSITY_PP_M2 = 5.4   # density at which walking all but stops
MIN_SLOWDOWN = 0.15
SINK_KINDS = {"exit", "assembly_point"}
ACTIVE = ("wait", "undecided", "stuck", "queued", "transit")


class Simulation:
    def __init__(self, vg: VenueGraph, scenario: dict[str, Any], planner: Planner, *,
                 dt_s: float = 1.0, replan_s: float = 10.0, app_adoption: float | None = None,
                 seed: int | None = None, log: EventLog | None = None, clock: SimClock | None = None,
                 log_every_s: float = 5.0, log_plans: bool = False,
                 sensors: list | None = None) -> None:
        self.vg, self.sc, self.planner = vg, scenario, planner
        self.dt, self.replan_s, self.log_every_s, self.log_plans = dt_s, replan_s, log_every_s, log_plans
        self.clock = clock or SimClock(scenario["start_time"])
        self.log = log or EventLog(None, "none", self.clock)
        self.seed = scenario["seed"] if seed is None else seed
        self.adoption = (app_adoption if app_adoption is not None
                         else scenario.get("app_adoption", config.DEFAULT_APP_ADOPTION))
        self.rng = random.Random(self.seed)
        self.sensors = sensors or []
        self.crossings: dict[str, int] = {}  # people admitted so far, per directed threshold

        self.mode = scenario["mode"]
        self.closed: set[str] = set()
        self.compliance = scenario["compliance"]
        self.safe_zones = vg.safe_zones()
        self.area = {z: d["area_m2"] for z, d in vg.graph.nodes(data=True)}
        self.jam_cap = {z: a * JAM_DENSITY_PP_M2 for z, a in self.area.items()}

        # directed edges: key -> (from, to, capacity pp/s, travel time s, threshold id)
        self.edges: dict[str, tuple[str, str, float, float, str]] = {}
        for u, v, tid, d in vg.graph.edges(keys=True, data=True):
            self.edges[self._key(tid, u, v)] = (u, v, d["capacity_pp_s"], d["travel_time_s"], tid)

        self.people = spawn(scenario, self.adoption, self.rng)
        self.by_id = {p.id: p for p in self.people}
        self.groups: dict[str, list[Person]] = {}
        for p in self.people:
            if p.group:
                self.groups.setdefault(p.group, []).append(p)

        self.occ: dict[str, int] = {z: 0 for z in vg.zones}
        for p in self.people:
            self.occ[p.zone] += 1
        self.inbound: dict[str, int] = {z: 0 for z in vg.zones}
        self.queues: dict[str, deque[Person]] = {}
        self.tokens: dict[str, float] = {}
        self.transit_n: dict[str, int] = {}
        self.heap: list[tuple[float, int, Person]] = []
        self._seq = 0
        self.pending: dict[str, Person] = {p.id: p for p in self.people}
        self.plan_cache: dict[str, tuple[str, str | None, str]] = {}
        self._own: dict[str, dict] = {}
        self._targets: dict[str, set[str]] = {}
        self.cleared = 0
        self.first_goal_change: float | None = None

        self.peak_density: dict[str, float] = {}
        self.peak_queue: dict[str, int] = {}
        self.split_samples = self.group_samples = self.split_peak = 0

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _key(tid: str, u: str, v: str) -> str:
        return f"{tid}:{u}->{v}"

    def _target_zones(self, dest: str) -> set[str]:
        if dest not in self._targets:
            self._targets[dest] = (set(self.safe_zones) if dest == NEAREST_SAFE
                                   else {self.vg.destinations[dest]["zone"]})
        return self._targets[dest]

    def _is_sink(self, dest: str) -> bool:
        if dest == NEAREST_SAFE:
            return True
        d = self.vg.destinations[dest]
        return d["kind"] in SINK_KINDS or bool(d.get("safe"))

    def _own_field(self, dest: str) -> dict:
        if dest not in self._own:
            self._own[dest] = shortest_path_field(self.vg, self.closed, dest, False)
        return self._own[dest]

    # ------------------------------------------------------------------ decisions
    def _decide(self, p: Person, t: float) -> None:
        self.pending.pop(p.id, None)
        if p.zone in self._target_zones(p.dest):
            self._arrive(p, t)
            return
        follows = p.has_app and p.u < self.compliance[self.mode]
        thr: str | None
        if follows:
            c = self.plan_cache.get(p.id)
            if c is None or c[0] != p.zone or c[1] is None:
                p.state = "undecided"
                self.pending[p.id] = p
                return
            thr = c[1]
        else:
            r = self._own_field(p.dest).get(p.zone)
            if r is None or r[1] is None:
                p.state = "stuck"
                self.pending[p.id] = p
                return
            thr = r[1]
        t_def = self.vg.thresholds[thr]
        v = t_def["to_zone"] if t_def["from_zone"] == p.zone else t_def["from_zone"]
        key = self._key(thr, p.zone, v)
        if thr in self.closed or key not in self.edges:
            p.state = "undecided"
            self.pending[p.id] = p
            return
        p.state, p.edge, p.next_zone = "queued", key, v
        self.queues.setdefault(key, deque()).append(p)
        self.tokens.setdefault(key, 0.0)

    def _arrive(self, p: Person, t: float) -> None:
        p.t_arrive = t
        if self._is_sink(p.dest):
            p.state = "gone"
            self.occ[p.zone] -= 1
            self.cleared += 1
        else:
            p.state = "done"

    def _process_pending(self, t: float) -> None:
        for p in list(self.pending.values()):
            self._decide(p, t)

    # ------------------------------------------------------------------ planning
    def _replan(self, t: float) -> None:
        entities, member_ids = [], set()
        for p in self.people:
            if p.has_app and p.state in ACTIVE:
                zone = p.next_zone if p.state == "transit" else p.zone
                entities.append(EntityState(p.id, zone, p.dest, p.group))
                member_ids.add(p.id)
        groups = []
        for gid, members in self.groups.items():
            ids = [m.id for m in members if m.id in member_ids]
            if len(ids) >= 2:
                groups.append(GroupState(gid, ids))
        state = LiveState(self.clock.iso(t), self.mode, entities, groups, set(self.closed))
        plan = self.planner.plan(self.vg, state)
        if self.log_plans:
            self.log.emit("plan", plan)
        zone_of = {e.id: e.zone for e in entities}
        for a in plan["assignments"]:
            subj = a["subject"]
            ids = ([subj["id"]] if subj["kind"] == "entity"
                   else [m.id for m in self.groups[subj["id"]] if m.id in member_ids])
            for pid in ids:
                self.plan_cache[pid] = (zone_of[pid], a.get("next_threshold"), a["destination_id"])

    # ------------------------------------------------------------------ events
    def _apply_event(self, e: dict, t: float) -> None:
        kind = e["type"]
        if kind == "mode_change":
            self.mode = e["mode"]
            self.log.emit("mode_change", {"mode": self.mode, "destination": e.get("destination")})
            if e.get("destination"):
                if self.first_goal_change is None:
                    self.first_goal_change = t
                for p in self.people:
                    if p.state == "gone":
                        continue
                    p.dest, p.t_goal, p.t_arrive = e["destination"], t, None
                    if p.state == "done":
                        p.state = "wait"
                        self.pending[p.id] = p
                self._drain_all_queues()
        elif kind == "closure":
            self.closed.add(e["threshold"])
            self.log.emit("closure", {"threshold": e["threshold"], "closed": True})
            self._drain_queues(lambda k: self.edges[k][4] == e["threshold"])
        elif kind == "reopen":
            self.closed.discard(e["threshold"])
            self.log.emit("closure", {"threshold": e["threshold"], "closed": False})
        self._own.clear()
        self._replan(t)
        self._process_pending(t)

    def _drain_queues(self, match) -> None:
        for key in [k for k in self.queues if match(k)]:
            for p in self.queues.pop(key):
                p.state = "undecided"
                self.pending[p.id] = p

    def _drain_all_queues(self) -> None:
        self._drain_queues(lambda k: True)

    # ------------------------------------------------------------------ movement
    def _admit(self, t: float) -> None:
        for key in list(self.queues):
            q = self.queues[key]
            u, v, cap, tt, _ = self.edges[key]
            self.tokens[key] += cap * self.dt
            while q and self.tokens[key] >= 1.0:
                if v not in self.safe_zones and self.occ[v] + self.inbound[v] >= self.jam_cap[v]:
                    break
                p = q.popleft()
                self.tokens[key] -= 1.0
                self.crossings[key] = self.crossings.get(key, 0) + 1
                self.occ[u] -= 1
                self.inbound[v] += 1
                slow = max(MIN_SLOWDOWN, 1.0 - self.occ[u] / self.jam_cap[u])
                p.state = "transit"
                self.transit_n[key] = self.transit_n.get(key, 0) + 1
                self._seq += 1
                heapq.heappush(self.heap, (t + tt / (p.speed * slow), self._seq, p))
            if not q:
                del self.queues[key]
                self.tokens[key] = min(self.tokens[key], 1.0)

    def _land(self, t: float) -> None:
        while self.heap and self.heap[0][0] <= t:
            _, _, p = heapq.heappop(self.heap)
            v = p.next_zone
            self.inbound[v] -= 1
            self.transit_n[p.edge] -= 1
            self.occ[v] += 1
            p.zone, p.edge, p.next_zone = v, None, None
            self._decide(p, t)

    # ------------------------------------------------------------------ logging
    def _loc(self, p: Person) -> str:
        return f"edge:{p.edge}" if p.state == "transit" else p.zone

    def _sample(self, t: float) -> None:
        for z, n in self.occ.items():
            if n:
                d = n / self.area[z]
                if d > self.peak_density.get(z, 0.0):
                    self.peak_density[z] = d
        queues = {k: len(q) for k, q in self.queues.items() if q}
        for k, n in queues.items():
            if n > self.peak_queue.get(k, 0):
                self.peak_queue[k] = n
        split = total = 0
        for members in self.groups.values():
            live = [m for m in members if m.state != "gone"]
            if len(live) >= 2:
                total += 1
                if len({self._loc(m) for m in live}) > 1:
                    split += 1
        self.split_samples += split
        self.group_samples += total
        self.split_peak = max(self.split_peak, split)
        self.log.emit("zone_state", {
            "t_s": round(t, 3), "mode": self.mode,
            "zones": {z: n for z, n in self.occ.items() if n},
            "transit": {k: n for k, n in self.transit_n.items() if n},
            "queues": queues, "cleared": self.cleared,
            "active": sum(1 for p in self.people if p.state in ACTIVE),
            "groups_split": split, "closed": sorted(self.closed)})
        for s in self.sensors:
            for typ, data in s.observe(self, t):
                self.log.emit(typ, data)

    # ------------------------------------------------------------------ run
    def run(self) -> dict[str, Any]:
        sc, dt = self.sc, self.dt
        self.log.emit("run_start", {
            "venue": self.vg.venue["id"], "scenario": sc["id"], "planner": self.planner.name,
            "seed": self.seed, "dt_s": dt, "replan_s": self.replan_s,
            "app_adoption": self.adoption, "people": len(self.people)})
        events = sorted(sc["events"], key=lambda e: e["at_s"])
        ei, next_replan, next_log = 0, 0.0, 0.0
        n_steps = int(math.ceil(sc["duration_s"] / dt))
        t = 0.0
        for step in range(n_steps + 1):
            t = step * dt
            self.clock.set(t)
            while ei < len(events) and events[ei]["at_s"] <= t:
                self._apply_event(events[ei], t)
                ei += 1
            if t >= next_replan:
                self._replan(t)
                self._process_pending(t)
                next_replan = t + self.replan_s
            self._land(t)
            self._admit(t)
            if t >= next_log:
                self._sample(t)
                next_log = t + self.log_every_s
            if ei >= len(events) and not any(p.state in ACTIVE for p in self.people):
                break
        self._sample(t)
        metrics = self.metrics(t)
        self.log.emit("metric", {"scope": "final", **metrics})
        self.log.emit("run_end", {"t_s": round(t, 3)})
        self.log.close()
        return metrics

    def metrics(self, t_end: float) -> dict[str, Any]:
        arrived = [p for p in self.people if p.t_arrive is not None]
        times = sorted(p.t_arrive - p.t_goal for p in arrived)

        def pct(q: float) -> float | None:
            return round(times[max(0, math.ceil(q * len(times)) - 1)], 1) if times else None

        n = len(self.people)
        all_in = len(arrived) == n
        t0 = self.first_goal_change or 0.0
        top = lambda d, k=3: dict(sorted(d.items(), key=lambda kv: -kv[1])[:k])  # noqa: E731
        out = {
            "people": n,
            "arrived_share": round(len(arrived) / n, 4),
            "stuck": sum(1 for p in self.people if p.state == "stuck"),
            "travel_time_mean_s": round(sum(times) / len(times), 1) if times else None,
            "travel_time_p95_s": pct(0.95),
            "clearance_s": round(max(p.t_arrive for p in arrived) - t0, 1) if arrived and all_in else None,
            "peak_density_pp_m2": {k: round(v, 2) for k, v in top(self.peak_density).items()},
            "peak_queue": top(self.peak_queue),
            "groups": len(self.groups),
            "groups_split_peak": self.split_peak,
            "groups_split_mean_share": (round(self.split_samples / self.group_samples, 4)
                                        if self.group_samples else 0.0),
            "t_end_s": round(t_end, 1),
        }
        if self.sensors:
            out["sensors"] = {s.id if hasattr(s, "id") else "app_position": s.stats() for s in self.sensors}
        return out
