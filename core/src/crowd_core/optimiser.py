"""Congestion-aware planners.

QueueAwarePlanner  – splits people over routes so that no threshold's queue grows needlessly
                     (method of successive averages on queue-aware travel times).
FlowPlanner        – time-expanded min-cost flow: finds the earliest time everyone can be out and
                     the flows that achieve it. Best for evacuation.
AdaptivePlanner    – flow planner in evacuation mode, queue-aware otherwise.

All three return the same plan format as the baseline (schemas/plan.schema.json). Planners see
only app users; zone counts in the live state scale their view up to everyone in the zone.
"""
from __future__ import annotations

import math

from ortools.graph.python import min_cost_flow

from .graph import VenueGraph
from .macro import (Net, Subject, all_or_nothing, assign, build_subjects, class_targets,
                    reverse_dijkstra)
from .planner import SCHEMA_VERSION
from .state import LiveState


class _MacroPlanner:
    name = "macro"

    def __init__(self) -> None:
        self.last_unroutable: list[str] = []
        self._prev: dict[str, tuple[str, int | None]] = {}    # subject -> (zone, tid:u edge)
        self._nets: dict[tuple, Net] = {}

    # subclasses return fractions[(cls, sf, zone)] = {edge index: p}, plus trees
    def _solve(self, vg: VenueGraph, state: LiveState, nets: dict, demand: dict) -> tuple[dict, dict]:
        raise NotImplementedError

    def _net(self, vg: VenueGraph, state: LiveState, sf: bool) -> Net:
        key = (id(vg), frozenset(state.closed_thresholds), sf)
        if key not in self._nets:
            if len(self._nets) > 16:
                self._nets.clear()
            self._nets[key] = Net(vg, state.closed_thresholds, sf)
        return self._nets[key]

    def plan(self, vg: VenueGraph, state: LiveState) -> dict:
        self.last_unroutable = []
        co = build_subjects(vg, state)
        # demand[(cls, sf)][zone] = people
        demand: dict[tuple[str, bool], dict[str, float]] = {}
        for s in co.subjects:
            d = demand.setdefault((s.cls, s.step_free), {})
            d[s.zone] = d.get(s.zone, 0.0) + s.weight * co.scale.get(s.zone, 1.0)
        nets = {sf: self._net(vg, state, sf) for sf in {k[1] for k in demand}}
        fractions, trees = self._solve(vg, state, nets, demand)

        by_cohort: dict[tuple, list[Subject]] = {}
        for s in co.subjects:
            by_cohort.setdefault((s.cls, s.step_free, s.zone), []).append(s)
        assignments, new_prev, load = [], {}, {}
        for ck in sorted(by_cohort):
            cls, sf, zone = ck
            subs = by_cohort[ck]
            net = nets[sf]
            dist, nxt, label = trees[(cls, sf)]
            targets = class_targets(vg, cls)
            if zone in targets:
                for s in subs:
                    assignments.append({"subject": {"kind": s.kind, "id": s.id},
                                        "destination_id": label[zone], "eta_s": 0.0})
                continue
            if zone not in nxt:
                self.last_unroutable += [s.id for s in subs]
                continue
            prev = {s.id: (self._prev[s.id][1] if s.id in self._prev and self._prev[s.id][0] == zone
                           else None) for s in subs}
            pick = assign(subs, fractions.get(ck, {nxt[zone]: 1.0}), prev, net.edges)
            for s in subs:
                ei = pick[s.id]
                if ei is None:
                    ei = nxt[zone]
                e = net.edges[ei]
                new_prev[s.id] = (zone, ei)
                load[e.tid] = load.get(e.tid, 0.0) + s.weight
                assignments.append({"subject": {"kind": s.kind, "id": s.id},
                                    "next_threshold": e.tid, "destination_id": label[e.v],
                                    "eta_s": round(dist.get(zone, 0.0), 1)})
        self._prev = new_prev
        return {"schema_version": SCHEMA_VERSION, "timestamp": state.timestamp, "mode": state.mode,
                "planner": self.name, "assignments": assignments,
                "threshold_flows": [{"threshold_id": t, "flow_pp_s": round(v, 3)}
                                    for t, v in sorted(load.items())],
                "closed_thresholds": sorted(state.closed_thresholds)}


class QueueAwarePlanner(_MacroPlanner):
    """Equilibrium-style assignment: each person's cost on an edge is its travel time plus the time
    to clear the queue and the people planned through it. Successive averages converge to a split
    where alternatives cost about the same."""

    name = "queue-aware"

    def __init__(self, iterations: int = 4, congestion_weight: float = 0.5) -> None:
        super().__init__()
        self.iterations, self.cw = iterations, congestion_weight

    def _solve(self, vg, state, nets, demand):
        keys = sorted(demand)
        base = {sf: [state.edge_queues.get(e.key, 0.0) for e in net.edges] for sf, net in nets.items()}
        flow = {sf: [0.0] * len(net.edges) for sf, net in nets.items()}
        frac: dict[tuple, dict[int, float]] = {}
        trees: dict = {}
        for k in range(1, self.iterations + 1):
            step = 1.0 / k
            aon = {sf: [0.0] * len(net.edges) for sf, net in nets.items()}
            for (cls, sf) in keys:
                net = nets[sf]
                cost = [e.tt + self.cw * (base[sf][i] + flow[sf][i]) / e.cap
                        for i, e in enumerate(net.edges)]
                targets = class_targets(vg, cls)
                dist, nxt, label = reverse_dijkstra(net, cost, targets)
                trees[(cls, sf)] = (dist, nxt, label)
                for ei, f in all_or_nothing(net, dist, nxt, targets, demand[(cls, sf)]).items():
                    aon[sf][ei] += f
                for z in demand[(cls, sf)]:
                    if z in nxt:
                        d = frac.setdefault((cls, sf, z), {})
                        for ei in d:
                            d[ei] *= 1 - step
                        d[nxt[z]] = d.get(nxt[z], 0.0) + step
            for sf in nets:
                flow[sf] = [(1 - step) * f + step * a for f, a in zip(flow[sf], aon[sf])]
        # report free-flow-ish etas from the final tree; labels come from the last iteration
        return frac, trees


class FlowPlanner(_MacroPlanner):
    """Time-expanded min-cost flow for one destination class.

    Finds the shortest horizon T (in steps) at which everyone can reach a target, then the cheapest
    flow at that horizon, and turns first moves out of each zone into split fractions. Zone
    density limits are ignored; people already crossing a threshold count as waiting at its far
    end. Falls back to the queue-aware planner for mixed destinations or step-free needs.
    """

    name = "flow"

    def __init__(self, step_s: float = 10.0, max_steps: int = 400, fallback: _MacroPlanner | None = None):
        super().__init__()
        self.step_s, self.max_steps = step_s, max_steps
        self.fallback = fallback or QueueAwarePlanner()
        self.last_horizon_s: float | None = None

    def plan(self, vg, state):
        co = build_subjects(vg, state)
        if len({(s.cls, s.step_free) for s in co.subjects}) > 1:
            out = self.fallback.plan(vg, state)
            self.last_unroutable = self.fallback.last_unroutable
            return out
        return super().plan(vg, state)

    def _solve(self, vg, state, nets, demand):
        if not demand:
            return {}, {}
        (cls, sf), dem = next(iter(demand.items()))
        net = nets[sf]
        targets = class_targets(vg, cls)
        free = [e.tt for e in net.edges]
        dist, nxt, label = reverse_dijkstra(net, free, targets)
        trees = {(cls, sf): (dist, nxt, label)}
        supply = {z: int(round(n)) for z, n in dem.items() if z in dist and round(n) > 0}
        self.last_horizon_s = None
        if not supply:
            return {}, trees
        dt = self.step_s
        lb = max(1, max(math.ceil(dist[z] / dt) for z in supply))
        T = lb
        res = self._try(net, targets, supply, T)
        while res is None and T < self.max_steps:
            T = min(self.max_steps, T * 2)
            res = self._try(net, targets, supply, T)
        if res is None:                      # too big to solve: let the queue-aware planner cope
            return self.fallback._solve(vg, state, nets, demand)
        lo, hi, best = max(lb, T // 2), T, res
        while lo < hi:                       # smallest feasible horizon in (T/2, T]
            mid = (lo + hi) // 2
            r = self._try(net, targets, supply, mid)
            if r is None:
                lo = mid + 1
            else:
                hi, best = mid, r
        self.last_horizon_s = hi * dt
        acc: dict[str, dict[int, float]] = {}
        for (z, ei), f in best.items():
            d = acc.setdefault(z, {})
            d[ei] = d.get(ei, 0.0) + f
        frac = {}
        for z, d in acc.items():
            tot = sum(d.values())
            frac[(cls, sf, z)] = {ei: f / tot for ei, f in d.items()}
        return frac, trees

    def _try(self, net: Net, targets, supply, T: int):
        """Min-cost flow on T steps; returns {(zone, edge index): flow} or None if infeasible."""
        zones = sorted(net.into)
        zi = {z: i for i, z in enumerate(zones)}
        Z = len(zones)
        sink = (T + 1) * Z
        total = sum(supply.values())
        mcf = min_cost_flow.SimpleMinCostFlow()
        node = lambda z, t: t * Z + zi[z]    # noqa: E731
        moves = []
        for t in range(T + 1):
            for z in zones:
                if t < T:
                    mcf.add_arc_with_capacity_and_unit_cost(node(z, t), node(z, t + 1), total, 1)
                if z in targets:
                    mcf.add_arc_with_capacity_and_unit_cost(node(z, t), sink, total, 0)
        for ei, e in enumerate(net.edges):
            s = max(1, round(e.tt / self.step_s))
            c = max(1, int(e.cap * self.step_s))
            for t in range(T - s + 1):
                a = mcf.add_arc_with_capacity_and_unit_cost(node(e.u, t), node(e.v, t + s), c, s)
                moves.append((a, e.u, ei))
        for z, n in supply.items():
            mcf.set_node_supply(node(z, 0), n)
        mcf.set_node_supply(sink, -total)
        if mcf.solve() != mcf.OPTIMAL:
            return None
        out: dict[tuple[str, int], float] = {}
        for a, u, ei in moves:
            f = mcf.flow(a)
            if f:
                out[(u, ei)] = out.get((u, ei), 0.0) + f
        return out


class AdaptivePlanner:
    """Evacuation: minimise clearance time (flow). Everything else: queue-aware routing."""

    name = "adaptive"

    def __init__(self) -> None:
        self.queue_aware = QueueAwarePlanner()
        self.flow = FlowPlanner(fallback=self.queue_aware)
        self.last_unroutable: list[str] = []

    def plan(self, vg, state):
        p = self.flow if state.mode == "evacuation" else self.queue_aware
        out = p.plan(vg, state)
        self.last_unroutable = p.last_unroutable
        out["planner"] = self.name
        return out
