"""Planner interface and the baseline shortest-path planner."""
from __future__ import annotations

from typing import Iterable, Protocol

import networkx as nx

from .graph import VenueGraph
from .scenario import NEAREST_SAFE
from .state import EntityState, LiveState

SCHEMA_VERSION = "0.1.0"


class Planner(Protocol):
    """Anything that turns a venue and a live state into a plan (see schemas/plan.schema.json)."""

    name: str

    def plan(self, venue: VenueGraph, state: LiveState) -> dict: ...


class BaselinePlanner:
    """Every entity takes the fastest open route to its destination. Ignores congestion.

    This is the benchmark every other planner has to beat. Entities with no open route are left
    out of the plan and listed in `last_unroutable`.
    """

    name = "baseline-shortest-path"

    def __init__(self) -> None:
        self.last_unroutable: list[str] = []

    def plan(self, venue: VenueGraph, state: LiveState) -> dict:
        self.last_unroutable = []
        fields: dict[tuple[str, bool], dict] = {}
        resolved: dict[str, tuple[str, str | None, float] | None] = {}

        def route(e: EntityState):
            key = (e.destination_id, e.needs_step_free)
            if key not in fields:
                fields[key] = shortest_path_field(
                    venue, state.closed_thresholds, e.destination_id, e.needs_step_free)
            return fields[key].get(e.zone)

        for e in state.entities:
            resolved[e.id] = route(e)

        groups = {g.id: g for g in state.groups}
        assignments: list[dict] = []
        done: set[str] = set()
        for e in state.entities:
            if e.id in done:
                continue
            r = resolved[e.id]
            if r is None:
                self.last_unroutable.append(e.id)
                continue
            dest_id, threshold, eta = r
            subject = {"kind": "entity", "id": e.id}
            g = groups.get(e.group_id) if e.group_id else None
            if g is not None:
                members = [m for m in state.entities if m.id in set(g.member_ids)]
                same = len(members) == len(g.member_ids) and all(
                    m.zone == e.zone and m.destination_id == e.destination_id
                    and m.needs_step_free == e.needs_step_free for m in members)
                if same:
                    subject = {"kind": "group", "id": g.id}
                    done.update(m.id for m in members)
            a: dict = {"subject": subject, "destination_id": dest_id, "eta_s": round(eta, 1)}
            if threshold is not None:
                a["next_threshold"] = threshold
            assignments.append(a)

        return {
            "schema_version": SCHEMA_VERSION,
            "timestamp": state.timestamp,
            "mode": state.mode,
            "planner": self.name,
            "assignments": assignments,
            "closed_thresholds": sorted(state.closed_thresholds),
        }


def shortest_path_field(
    venue: VenueGraph, closed: Iterable[str], destination_id: str, step_free: bool = False
) -> dict[str, tuple[str, str | None, float]]:
    """For every zone with a route: (resolved destination id, next threshold or None, eta in s).

    `destination_id` may be 'nearest_safe'. Zones with no open route are absent.
    """
    view = venue.routing_view(closed, step_free)
    if destination_id == NEAREST_SAFE:
        targets = [d for d in venue.destinations.values() if d.get("safe")]
    else:
        targets = [venue.destinations[destination_id]]
    sources = {d["zone"] for d in targets}
    dist, paths = nx.multi_source_dijkstra(view.reverse(copy=False), sources,
                                           weight="travel_time_s")
    out: dict = {}
    for zone, path in paths.items():
        reached = path[0]  # reverse path starts at the target zone
        dest = next(d["id"] for d in targets if d["zone"] == reached)
        if len(path) == 1:
            out[zone] = (dest, None, 0.0)
        else:
            nxt = path[-2]  # next zone on the forward route
            out[zone] = (dest, view[zone][nxt]["threshold_id"], dist[zone])
    return out
