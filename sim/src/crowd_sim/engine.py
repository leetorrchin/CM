"""Zone-level crowd simulation.

People move in units: a group is one unit and a lone person is a unit of one, so groups never split.
Each directed threshold has a FIFO queue and admits units at its capacity (people per second, a
group of four uses four people's worth). Crossing takes the edge travel time, divided by the
slowest member's speed and slowed as the source zone nears jam density.

Planners give guidance. A unit follows it if any member has the app and a fixed draw is below the
compliance of the current mode. Followers can leave a queue and join another when guidance changes
(after a cooldown) and can be redirected to an equivalent destination (another exit, say). Everyone
else takes the fastest route to their own destination, as the baseline planner would.
"""
from __future__ import annotations

import heapq
import math
import random
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from crowd_core.graph import VenueGraph
from crowd_core.planner import Planner, shortest_path_field
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


@dataclass(eq=False)
class Unit:
    id: str
    members: list[Person]
    zone: str
    dest: str
    has_app: bool            # any member has the app, so the unit can get guidance
    u: float                 # fixed draw: follows guidance if u < compliance of the mode
    speed: float             # slowest member
    guide_id: str | None     # an app member whose guidance the unit uses
    state: str = "wait"      # wait | undecided | stuck | queued | transit | done | gone
    t_goal: float = 0.0
    t_arrive: float | None = None
    edge: str | None = None
    next_zone: str | None = None
    ticket: int = 0
    queued_at: float = 0.0

    @property
    def size(self) -> int:
        return len(self.members)


def build_units(people: list[Person], group_mode: str) -> list[Unit]:
    by_group: dict[str, list[Person]] = {}
    chunks: list[list[Person]] = []
    for p in people:
        if p.group and group_mode == "unit":
            by_group.setdefault(p.group, []).append(p)
        else:
            chunks.append([p])
    chunks.extend(by_group.values())
    chunks.sort(key=lambda c: c[0].id)
    units = []
    for c in chunks:
        app = [m for m in c if m.has_app]
        units.append(Unit(
            id=c[0].group if (len(c) > 1 and c[0].group) else c[0].id, members=c, zone=c[0].zone,
            dest=c[0].dest, has_app=bool(app), u=c[0].u, speed=min(m.speed for m in c),
            guide_id=app[0].id if app else None))
    return units


class Simulation:
    def __init__(self, vg: VenueGraph, scenario: dict[str, Any], planner: Planner, *,
                 dt_s: float = 1.0, replan_s: float = 10.0, app_adoption: float | None = None,
                 seed: int | None = None, log: EventLog | None = None, clock: SimClock | None = None,
                 log_every_s: float = 5.0, log_plans: bool = False, sensors: list | None = None,
                 group_mode: str = "unit", queue_switching: bool = True,
                 switch_cooldown_s: float = 30.0) -> None:
        if group_mode not in ("unit", "individual"):
            raise ValueError("group_mode must be 'unit' or 'individual'")
        self.vg, self.sc, self.planner = vg, scenario, planner
        self.dt, self.replan_s, self.log_every_s, self.log_plans = dt_s, replan_s, log_every_s, log_plans
        self.group_mode, self.queue_switching, self.switch_cooldown_s = group_mode, queue_switching, switch_cooldown_s
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
        self.units = build_units(self.people, group_mode)
        self.unit_of: dict[str, Unit] = {m.id: un for un in self.units for m in un.members}
        self.groups: dict[str, list[Person]] = {}
        for p in self.people:
            if p.group:
                self.groups.setdefault(p.group, []).append(p)
        self.group_units: dict[str, list[Unit]] = {}
        if group_mode == "individual":
            for un in self.units:
                if un.members[0].group:
                    self.group_units.setdefault(un.members[0].group, []).append(un)

        self.occ: dict[str, int] = {z: 0 for z in vg.zones}
        for un in self.units:
            self.occ[un.zone] += un.size
        self.inbound: dict[str, int] = {z: 0 for z in vg.zones}
        self.queues: dict[str, deque[tuple[Unit, int]]] = {}
        self.qcount: dict[str, int] = {}
        self.tokens: dict[str, float] = {}
        self.transit_n: dict[str, int] = {}
        self.heap: list[tuple[float, int, Unit]] = []
        self._seq = 0
        self.pending: dict[int, Unit] = {id(u): u for u in self.units}
        self.plan_cache: dict[str, tuple[str, str | None, str]] = {}
        self._own: dict[str, dict] = {}
        self._targets: dict[str, set[str]] = {}
        self.cleared = 0
        self.first_goal_change: float | None = None
        self.redirected = 0
        self.queue_switches = 0

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

    def _follows(self, un: Unit) -> bool:
        return un.has_app and un.u < self.compliance[self.mode]

    # ------------------------------------------------------------------ queues
    def _enqueue(self, un: Unit, thr: str, v: str, t: float) -> None:
        key = self._key(thr, un.zone, v)
        un.state, un.edge, un.next_zone, un.queued_at = "queued", key, v, t
        un.ticket += 1
        self.queues.setdefault(key, deque()).append((un, un.ticket))
        self.qcount[key] = self.qcount.get(key, 0) + un.size
        self.tokens.setdefault(key, 0.0)

    def _unqueue(self, un: Unit) -> None:
        """Take a queued unit out of its queue (its old entry becomes stale and is skipped)."""
        self.qcount[un.edge] -= un.size
        un.state, un.edge, un.next_zone = "undecided", None, None
        un.ticket += 1

    def _valid(self, entry: tuple[Unit, int], key: str) -> bool:
        un, tk = entry
        return un.state == "queued" and un.edge == key and un.ticket == tk

    def _drain_queues(self, match) -> None:
        for key in [k for k in self.queues if match(k)]:
            for entry in self.queues.pop(key):
                if self._valid(entry, key):
                    self._unqueue(entry[0])
                    self.pending[id(entry[0])] = entry[0]
            self.qcount[key] = 0

    # ------------------------------------------------------------------ decisions
    def _decide(self, un: Unit, t: float) -> None:
        self.pending.pop(id(un), None)
        if un.zone in self._target_zones(un.dest):
            self._arrive(un, t)
            return
        thr: str | None
        if self._follows(un):
            c = self.plan_cache.get(un.guide_id)
            if c is None or c[0] != un.zone or c[1] is None:
                un.state = "undecided"
                self.pending[id(un)] = un
                return
            thr = c[1]
            self._adopt(un, c[2])
        else:
            r = self._own_field(un.dest).get(un.zone)
            if r is None or r[1] is None:
                un.state = "stuck"
                self.pending[id(un)] = un
                return
            thr = r[1]
        th = self.vg.thresholds[thr]
        v = th["to_zone"] if th["from_zone"] == un.zone else th["from_zone"]
        if thr in self.closed or self._key(thr, un.zone, v) not in self.edges:
            un.state = "undecided"
            self.pending[id(un)] = un
            return
        self._enqueue(un, thr, v, t)

    def _adopt(self, un: Unit, dest: str) -> None:
        """Follow a planner redirect to an equivalent destination. 'nearest_safe' is a class, not a
        pick, so it stays as is (the planner may resolve it differently next time)."""
        if dest != un.dest and un.dest != NEAREST_SAFE:
            self.redirected += un.size
            un.dest = dest

    def _arrive(self, un: Unit, t: float) -> None:
        un.t_arrive = t
        if self._is_sink(un.dest):
            un.state = "gone"
            self.occ[un.zone] -= un.size
            self.cleared += un.size
        else:
            un.state = "done"

    def _process_pending(self, t: float) -> None:
        for un in list(self.pending.values()):
            self._decide(un, t)

    def _reconsider_queues(self, t: float) -> None:
        """Followers waiting in a queue move to a better one if the new guidance says so."""
        moves = []
        for key, q in self.queues.items():
            for entry in q:
                if not self._valid(entry, key):
                    continue
                un = entry[0]
                if not self._follows(un) or t - un.queued_at < self.switch_cooldown_s:
                    continue
                c = self.plan_cache.get(un.guide_id)
                if c is None or c[0] != un.zone or c[1] is None:
                    continue
                if c[1] != self.edges[key][4] and c[1] not in self.closed:
                    moves.append((un, c))
        for un, c in moves:
            th = self.vg.thresholds[c[1]]
            v = th["to_zone"] if th["from_zone"] == un.zone else th["from_zone"]
            if self._key(c[1], un.zone, v) not in self.edges:
                continue
            self._unqueue(un)
            self._adopt(un, c[2])
            self._enqueue(un, c[1], v, t)
            self.queue_switches += un.size

    # ------------------------------------------------------------------ planning
    def _replan(self, t: float) -> None:
        entities, member_ids = [], set()
        groups = []
        for un in self.units:
            if not un.has_app or un.state not in ACTIVE:
                continue
            zone = un.next_zone if un.state == "transit" else un.zone
            app = [m for m in un.members if m.has_app]
            gid = un.id if un.size > 1 else None
            for m in app:
                entities.append(EntityState(m.id, zone, un.dest, gid))
                member_ids.add(m.id)
            if gid and len(app) >= 2:
                groups.append(GroupState(gid, [m.id for m in app]))
        state = LiveState(
            self.clock.iso(t), self.mode, entities, groups, set(self.closed),
            zone_counts={z: float(n) for z, n in self.occ.items() if n},
            edge_queues={k: float(n) for k, n in self.qcount.items() if n},
            edge_transit={k: float(n) for k, n in self.transit_n.items() if n})
        plan = self.planner.plan(self.vg, state)
        if self.log_plans:
            self.log.emit("plan", plan)
        zone_of = {e.id: e.zone for e in entities}
        group_members = {g.id: g.member_ids for g in groups}
        for a in plan["assignments"]:
            subj = a["subject"]
            ids = [subj["id"]] if subj["kind"] == "entity" else group_members.get(subj["id"], [])
            for pid in ids:
                self.plan_cache[pid] = (zone_of[pid], a.get("next_threshold"), a["destination_id"])
        if self.queue_switching:
            self._reconsider_queues(t)

    # ------------------------------------------------------------------ events
    def _apply_event(self, e: dict, t: float) -> None:
        kind = e["type"]
        if kind == "mode_change":
            self.mode = e["mode"]
            self.log.emit("mode_change", {"mode": self.mode, "destination": e.get("destination")})
            if e.get("destination"):
                if self.first_goal_change is None:
                    self.first_goal_change = t
                for un in self.units:
                    if un.state == "gone":
                        continue
                    un.dest, un.t_goal, un.t_arrive = e["destination"], t, None
                    if un.state == "done":
                        un.state = "wait"
                        self.pending[id(un)] = un
                self._drain_queues(lambda k: True)
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

    # ------------------------------------------------------------------ movement
    def _admit(self, t: float) -> None:
        for key in list(self.queues):
            q = self.queues[key]
            u, v, cap, tt, _ = self.edges[key]
            self.tokens[key] += cap * self.dt
            while q:
                if not self._valid(q[0], key):
                    q.popleft()
                    continue
                un = q[0][0]
                if self.tokens[key] < 1.0:
                    break
                if v not in self.safe_zones and self.occ[v] + self.inbound[v] >= self.jam_cap[v]:
                    break
                q.popleft()
                self.tokens[key] -= un.size
                self.qcount[key] -= un.size
                self.crossings[key] = self.crossings.get(key, 0) + un.size
                self.occ[u] -= un.size
                self.inbound[v] += un.size
                slow = max(MIN_SLOWDOWN, 1.0 - self.occ[u] / self.jam_cap[u])
                un.state = "transit"
                self.transit_n[key] = self.transit_n.get(key, 0) + un.size
                self._seq += 1
                heapq.heappush(self.heap, (t + tt / (un.speed * slow), self._seq, un))
            if not q:
                del self.queues[key]
                self.tokens[key] = min(self.tokens[key], 1.0)

    def _land(self, t: float) -> None:
        while self.heap and self.heap[0][0] <= t:
            _, _, un = heapq.heappop(self.heap)
            v = un.next_zone
            self.inbound[v] -= un.size
            self.transit_n[un.edge] -= un.size
            self.occ[v] += un.size
            un.zone, un.edge, un.next_zone = v, None, None
            self._decide(un, t)

    # ------------------------------------------------------------------ logging
    def state_dict(self, t: float, queues: dict | None = None, split: int = 0) -> dict[str, Any]:
        """What a zone_state record holds: counts per zone, crossing and queue, for dashboards."""
        queues = queues if queues is not None else {k: n for k, n in self.qcount.items() if n}
        return {
            "t_s": round(t, 3), "mode": self.mode,
            "zones": {z: n for z, n in self.occ.items() if n},
            "transit": {k: n for k, n in self.transit_n.items() if n},
            "queues": queues, "cleared": self.cleared,
            "active": sum(u.size for u in self.units if u.state in ACTIVE),
            "groups_split": split, "closed": sorted(self.closed)}

    def _sample(self, t: float) -> None:
        for z, n in self.occ.items():
            if n:
                d = n / self.area[z]
                if d > self.peak_density.get(z, 0.0):
                    self.peak_density[z] = d
        queues = {k: n for k, n in self.qcount.items() if n}
        for k, n in queues.items():
            if n > self.peak_queue.get(k, 0):
                self.peak_queue[k] = n
        split = total = 0
        for units in self.group_units.values():
            live = [u for u in units if u.state != "gone"]
            if len(live) >= 2:
                total += 1
                if len({f"edge:{u.edge}" if u.state == "transit" else u.zone for u in live}) > 1:
                    split += 1
        self.split_samples += split
        self.group_samples += total
        self.split_peak = max(self.split_peak, split)
        self.log.emit("zone_state", self.state_dict(t, queues, split))
        for s in self.sensors:
            for typ, data in s.observe(self, t):
                self.log.emit(typ, data)

    # ------------------------------------------------------------------ run
    def begin(self) -> None:
        sc = self.sc
        self.log.emit("run_start", {
            "venue": self.vg.venue["id"], "scenario": sc["id"], "planner": self.planner.name,
            "seed": self.seed, "dt_s": self.dt, "replan_s": self.replan_s, "app_adoption": self.adoption,
            "people": len(self.people), "group_mode": self.group_mode,
            "queue_switching": self.queue_switching})
        self._events = sorted(sc["events"], key=lambda e: e["at_s"])
        self._ei, self._next_replan, self._next_log, self._step, self._t = 0, 0.0, 0.0, 0, 0.0
        self._injected: deque[dict] = deque()

    def inject(self, event: dict) -> None:
        """Queue an event (mode_change, closure, reopen) to be applied at the next step."""
        if event.get("type") not in ("mode_change", "closure", "reopen"):
            raise ValueError(f"unknown event type {event.get('type')!r}")
        self._injected.append(dict(event))

    def add_guest(self, zone: str, dest: str = NEAREST_SAFE) -> str:
        """Add one real user to the crowd. They always follow guidance."""
        if zone not in self.vg.zones:
            raise KeyError(zone)
        n = sum(1 for p in self.people if p.id.startswith("guest-")) + 1
        p = Person(f"guest-{n}", None, zone, dest, True, 0.0, 1.0, t_goal=self._t)
        un = build_units([p], self.group_mode)[0]
        self.people.append(p)
        self.units.append(un)
        self.unit_of[p.id] = un
        self.occ[zone] += 1
        self.pending[id(un)] = un
        return p.id

    def set_destination(self, person_id: str, dest: str) -> bool:
        """A user changes where they want to go. Allowed until they have left the venue."""
        un = self.unit_of.get(person_id)
        if un is None or un.state == "gone" or (dest != NEAREST_SAFE and dest not in self.vg.destinations):
            return False
        if un.state == "queued":
            self._unqueue(un)
            self.pending[id(un)] = un
        un.dest, un.t_goal, un.t_arrive = dest, self._t, None
        if un.state == "done":
            un.state = "wait"
            self.pending[id(un)] = un
        return True

    def _idle(self) -> bool:
        return self._ei >= len(self._events) and not any(u.state in ACTIVE for u in self.units)

    def _tick(self) -> None:
        dt, t = self.dt, self._step * self.dt
        self._t = t
        self.clock.set(t)
        while self._injected:
            self._apply_event(self._injected.popleft(), t)
        while self._ei < len(self._events) and self._events[self._ei]["at_s"] <= t:
            self._apply_event(self._events[self._ei], t)
            self._ei += 1
        if t >= self._next_replan:
            self._replan(t)
            self._process_pending(t)
            self._next_replan = t + self.replan_s
        self._land(t)
        self._admit(t)
        if t >= self._next_log:
            self._sample(t)
            self._next_log = t + self.log_every_s
        self._step += 1

    def advance(self, until_s: float, stop_when_idle: bool = False) -> bool:
        """Step the simulation up to sim time `until_s`. Returns True if it went idle."""
        while self._step * self.dt <= until_s:
            self._tick()
            if stop_when_idle and self._idle():
                return True
        return False

    def finish(self) -> dict[str, Any]:
        self._sample(self._t)
        metrics = self.metrics(self._t)
        self.log.emit("metric", {"scope": "final", **metrics})
        self.log.emit("run_end", {"t_s": round(self._t, 3)})
        self.log.close()
        return metrics

    def run(self) -> dict[str, Any]:
        self.begin()
        self.advance(math.ceil(self.sc["duration_s"] / self.dt) * self.dt, stop_when_idle=True)
        return self.finish()

    # ------------------------------------------------------------------ live queries
    def guidance(self, person_id: str) -> dict[str, Any] | None:
        """What a phone would show for this person right now."""
        un = self.unit_of.get(person_id)
        if un is None:
            return None
        zone = un.zone
        out: dict[str, Any] = {"person_id": person_id, "state": un.state, "zone": zone, "mode": self.mode,
                               "destination": un.dest, "group_size": un.size,
                               "following": self._follows(un), "t_s": round(self._t, 1)}
        if un.state == "transit" and un.edge:
            tid, rest = un.edge.split(":", 1)
            out.update(crossing=tid, from_zone=rest.split("->")[0], zone=rest.split("->")[0], to_zone=un.next_zone)
        elif un.state == "queued" and un.edge:
            tid = un.edge.split(":", 1)[0]
            out.update(next_threshold=tid, next_zone=un.next_zone, queue_ahead=int(self.qcount.get(un.edge, 0)),
                       waited_s=round(self._t - un.queued_at, 1))
        elif un.state in ("undecided", "wait", "stuck"):
            c = self.plan_cache.get(un.guide_id) if un.guide_id else None
            if c and c[0] == zone and c[1]:
                th = self.vg.thresholds[c[1]]
                out.update(next_threshold=c[1], next_zone=th["to_zone"] if th["from_zone"] == zone else th["from_zone"])
        if un.state == "gone":
            out["arrived"] = True
        if un.state == "done":
            out["arrived"] = True
        out["closed"] = sorted(self.closed)
        return out

    def metrics(self, t_end: float) -> dict[str, Any]:
        arrived = [u for u in self.units if u.t_arrive is not None]
        times = sorted(t for u in arrived for t in [u.t_arrive - u.t_goal] * u.size)
        n = len(self.people)
        n_arrived = sum(u.size for u in arrived)

        def pct(q: float) -> float | None:
            return round(times[max(0, math.ceil(q * len(times)) - 1)], 1) if times else None

        t0 = self.first_goal_change or 0.0
        top = lambda d, k=3: dict(sorted(d.items(), key=lambda kv: -kv[1])[:k])  # noqa: E731
        out = {
            "people": n,
            "arrived_share": round(n_arrived / n, 4),
            "stuck": sum(u.size for u in self.units if u.state == "stuck"),
            "travel_time_mean_s": round(sum(times) / len(times), 1) if times else None,
            "travel_time_p95_s": pct(0.95),
            "clearance_s": (round(max(u.t_arrive for u in arrived) - t0, 1)
                            if arrived and n_arrived == n else None),
            "peak_density_pp_m2": {k: round(v, 2) for k, v in top(self.peak_density).items()},
            "peak_queue": top(self.peak_queue),
            "groups": len(self.groups),
            "groups_split_peak": self.split_peak,
            "groups_split_mean_share": (round(self.split_samples / self.group_samples, 4)
                                        if self.group_samples else 0.0),
            "queue_switches": self.queue_switches,
            "redirected": self.redirected,
            "t_end_s": round(t_end, 1),
        }
        if self.sensors:
            out["sensors"] = {getattr(s, "id", "app_position"): s.stats() for s in self.sensors}
        return out
