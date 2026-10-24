"""Shared pieces for the congestion-aware planners: edges, destination classes, routing trees,
and turning per-zone split fractions into stable per-subject assignments."""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

from .graph import VenueGraph
from .scenario import NEAREST_SAFE
from .state import LiveState

# Destinations of these kinds are interchangeable within the kind: someone heading for one exit
# can be sent to another. Anything else (a stage, first aid) is a fixed place.
FLEXIBLE_KINDS = ("exit", "food", "toilets", "assembly_point")
MIN_FRACTION = 0.05      # drop split fractions below this and renormalise


@dataclass(frozen=True)
class Edge:
    tid: str
    u: str
    v: str
    tt: float
    cap: float
    key: str                 # "tid:u->v", matches the keys in LiveState.edge_queues


class Net:
    """Open directed edges of the venue for one (closed set, step-free) combination."""

    def __init__(self, vg: VenueGraph, closed, step_free: bool) -> None:
        self.edges: list[Edge] = []
        self.into: dict[str, list[int]] = {z: [] for z in vg.zones}
        for u, v, tid, d in vg.graph.edges(keys=True, data=True):
            if tid in closed or (step_free and not (
                    d["step_free"] and vg.zones[u].get("step_free", True)
                    and vg.zones[v].get("step_free", True))):
                continue
            self.into[v].append(len(self.edges))
            self.edges.append(Edge(tid, u, v, d["travel_time_s"], d["capacity_pp_s"], f"{tid}:{u}->{v}"))
        self.edge_of = {(e.tid, e.u): i for i, e in enumerate(self.edges)}


def dest_class(vg: VenueGraph, dest_id: str) -> str:
    if dest_id == NEAREST_SAFE:
        return NEAREST_SAFE
    kind = vg.destinations[dest_id]["kind"]
    return f"kind:{kind}" if kind in FLEXIBLE_KINDS else dest_id


def class_targets(vg: VenueGraph, cls: str) -> dict[str, str]:
    """zone -> destination id that serves the class (first by id when a zone has several)."""
    if cls == NEAREST_SAFE:
        ds = [d for d in vg.destinations.values() if d.get("safe")]
    elif cls.startswith("kind:"):
        ds = [d for d in vg.destinations.values() if d["kind"] == cls[5:]]
    else:
        ds = [vg.destinations[cls]]
    out: dict[str, str] = {}
    for d in sorted(ds, key=lambda d: d["id"]):
        out.setdefault(d["zone"], d["id"])
    return out


def reverse_dijkstra(net: Net, cost: list[float], targets: dict[str, str]):
    """Cheapest route from every zone to any target. Returns dist, next edge index, label (the
    destination reached)."""
    dist = {z: 0.0 for z in targets}
    label = dict(targets)
    nxt: dict[str, int] = {}
    heap = [(0.0, z) for z in sorted(targets)]
    heapq.heapify(heap)
    while heap:
        d, z = heapq.heappop(heap)
        if d > dist[z]:
            continue
        for ei in net.into[z]:
            u = net.edges[ei].u
            nd = d + cost[ei]
            if nd < dist.get(u, math.inf) - 1e-9:
                dist[u], nxt[u], label[u] = nd, ei, label[z]
                heapq.heappush(heap, (nd, u))
    return dist, nxt, label


def all_or_nothing(net: Net, dist, nxt, targets, demand: dict[str, float]) -> dict[int, float]:
    """Push demand along the tree; returns load per edge index."""
    load: dict[int, float] = {}
    inflow = dict(demand)
    order = sorted(dist, key=lambda z: -dist[z])
    for z in order:
        f = inflow.get(z, 0.0)
        if f <= 0 or z in targets or z not in nxt:
            continue
        ei = nxt[z]
        load[ei] = load.get(ei, 0.0) + f
        v = net.edges[ei].v
        inflow[v] = inflow.get(v, 0.0) + f
    return load


@dataclass
class Subject:
    kind: str                # "entity" | "group"
    id: str
    weight: int              # people the planner can see in it
    zone: str
    cls: str
    step_free: bool


@dataclass
class Cohorts:
    subjects: list[Subject] = field(default_factory=list)
    scale: dict[str, float] = field(default_factory=dict)   # zone -> true people / visible people


def build_subjects(vg: VenueGraph, state: LiveState) -> Cohorts:
    """Groups that are together (same zone, destination, step-free need) become one subject."""
    groups = {g.id: g for g in state.groups}
    by_id = {e.id: e for e in state.entities}
    out = Cohorts()
    done: set[str] = set()
    seen_w: dict[str, int] = {}
    for e in state.entities:
        if e.id in done:
            continue
        g = groups.get(e.group_id) if e.group_id else None
        subj = Subject("entity", e.id, 1, e.zone, dest_class(vg, e.destination_id), e.needs_step_free)
        if g is not None:
            members = [by_id[m] for m in g.member_ids if m in by_id]
            if len(members) == len(g.member_ids) and len(members) >= 2 and all(
                    (m.zone, m.destination_id, m.needs_step_free) ==
                    (e.zone, e.destination_id, e.needs_step_free) for m in members):
                subj = Subject("group", g.id, len(members), e.zone, subj.cls, e.needs_step_free)
                done.update(m.id for m in members)
        out.subjects.append(subj)
        seen_w[subj.zone] = seen_w.get(subj.zone, 0) + subj.weight
    # the planner only sees app users; zone counts tell us how many people are really there
    for z, w in seen_w.items():
        total = state.zone_counts.get(z, 0.0)
        out.scale[z] = max(1.0, total / w) if w else 1.0
    return out


def assign(subjects: list[Subject], fractions: dict[int, float], prev: dict[str, int | None],
           edges: list[Edge]) -> dict[str, int | None]:
    """Split one cohort (same zone, class) across first-hop edges to match `fractions`.

    Keeps a subject on its previous edge while that edge still has a share and quota left; the
    rest go to the edge with the biggest deficit. Deterministic.
    """
    if not fractions:
        return {s.id: None for s in subjects}
    fr = {e: p for e, p in fractions.items() if p >= MIN_FRACTION}
    tot = sum(fr.values()) or 1.0
    fr = {e: p / tot for e, p in fr.items()}
    W = sum(s.weight for s in subjects)
    quota = {e: p * W for e, p in fr.items()}
    got = {e: 0.0 for e in fr}
    out: dict[str, int | None] = {}
    rest = []
    for s in sorted(subjects, key=lambda s: s.id):
        p = prev.get(s.id)
        if p in fr and got[p] + s.weight <= quota[p] + 0.5 * s.weight + 1e-9:
            out[s.id] = p
            got[p] += s.weight
        else:
            rest.append(s)
    for s in rest:
        e = max(sorted(fr), key=lambda e: quota[e] - got[e])
        out[s.id] = e
        got[e] += s.weight
    return out
