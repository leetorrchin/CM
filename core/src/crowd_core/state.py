"""Live state handed to a planner."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EntityState:
    id: str
    zone: str
    destination_id: str
    group_id: str | None = None
    needs_step_free: bool = False


@dataclass
class GroupState:
    id: str
    member_ids: list[str]
    cohesion_weight: float = 1.0


@dataclass
class LiveState:
    timestamp: str
    mode: str = "normal"
    entities: list[EntityState] = field(default_factory=list)
    groups: list[GroupState] = field(default_factory=list)
    closed_thresholds: set[str] = field(default_factory=set)
    # Estimated people per zone from fusion. Unused by the baseline planner.
    zone_counts: dict[str, float] = field(default_factory=dict)
