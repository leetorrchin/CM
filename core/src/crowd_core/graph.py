"""Compile a venue into a graph the planners work on.

Nodes are zones. Each threshold becomes a directed edge (two if it is not one-way). Several
thresholds between the same pair of zones stay as parallel edges, keyed by threshold id, so an
optimiser can split flow across them. Baseline routing uses `routing_view`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import networkx as nx

from . import config
from .geometry import dist, midpoint, polygon_area, polygon_centroid


@dataclass
class VenueGraph:
    venue: dict[str, Any]
    graph: nx.MultiDiGraph
    zones: dict[str, dict[str, Any]]
    thresholds: dict[str, dict[str, Any]]
    destinations: dict[str, dict[str, Any]]
    zone_capacity: dict[str, float] = field(default_factory=dict)

    def routing_view(
        self, closed: Iterable[str] = (), step_free_only: bool = False
    ) -> nx.DiGraph:
        """Simple digraph keeping the fastest open edge between each pair of zones."""
        closed = set(closed)
        view = nx.DiGraph()
        view.add_nodes_from(self.graph.nodes)
        for u, v, key, d in self.graph.edges(keys=True, data=True):
            if key in closed:
                continue
            if step_free_only and not d["step_free"]:
                continue
            if step_free_only and not (self.zones[u].get("step_free", True)
                                       and self.zones[v].get("step_free", True)):
                continue
            if not view.has_edge(u, v) or d["travel_time_s"] < view[u][v]["travel_time_s"]:
                view.add_edge(u, v, threshold_id=key, travel_time_s=d["travel_time_s"],
                              length_m=d["length_m"])
        return view

    def safe_zones(self) -> set[str]:
        return {d["zone"] for d in self.destinations.values() if d.get("safe")}


def compile_venue(venue: dict[str, Any]) -> VenueGraph:
    """Build the graph. Assumes the venue passed validation."""
    zones = {z["id"]: z for z in venue["zones"]}
    thresholds = {t["id"]: t for t in venue["thresholds"]}
    destinations = {d["id"]: d for d in venue["destinations"]}
    centroid = {zid: polygon_centroid(z["polygon"]) for zid, z in zones.items()}

    g = nx.MultiDiGraph()
    capacity: dict[str, float] = {}
    for zid, z in zones.items():
        cap = z.get("capacity", {})
        area = polygon_area(z["polygon"])
        if "max_people" in cap:
            people = float(cap["max_people"])
        else:
            people = area * cap.get("max_density_pp_m2", config.DEFAULT_MAX_DENSITY_PP_M2)
        capacity[zid] = people
        g.add_node(zid, level=z["level"], area_m2=area, centroid=centroid[zid],
                   capacity_people=people, kind=z["kind"])

    for tid, t in thresholds.items():
        mid = midpoint(t["segment"])
        speed = config.WALK_SPEED_MS * config.SPEED_FACTOR.get(t["kind"], 1.0)
        flow = t.get("max_flow_pp_s",
                     t["width_m"] * config.FLOW_PP_S_PER_M * config.FLOW_FACTOR.get(t["kind"], 1.0))
        length = dist(centroid[t["from_zone"]], mid) + dist(mid, centroid[t["to_zone"]])
        attrs = dict(kind=t["kind"], length_m=length, travel_time_s=length / speed,
                     width_m=t["width_m"], capacity_pp_s=flow,
                     step_free=t.get("step_free", True), closable=t.get("closable", True))
        g.add_edge(t["from_zone"], t["to_zone"], key=tid, **attrs)
        if not t.get("one_way", False):
            g.add_edge(t["to_zone"], t["from_zone"], key=tid, **attrs)

    return VenueGraph(venue, g, zones, thresholds, destinations, capacity)
