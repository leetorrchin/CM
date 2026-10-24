"""Emulated people: spawn a crowd with groups, destinations, app ownership and walking speed."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(eq=False)
class Person:
    id: str
    group: str | None
    zone: str
    dest: str
    has_app: bool
    u: float            # fixed draw in [0,1); follows guidance if u < compliance of the mode
    speed: float        # walking speed multiplier
    state: str = "wait"  # wait | undecided | stuck | queued | transit | done | gone
    t_goal: float = 0.0  # when the current destination was set
    t_arrive: float | None = None
    edge: str | None = None
    next_zone: str | None = None


def _apportion(total: int, shares: list[float]) -> list[int]:
    """Largest-remainder rounding so counts sum to total."""
    raw = [total * s for s in shares]
    counts = [int(math.floor(r)) for r in raw]
    order = sorted(range(len(raw)), key=lambda i: raw[i] - counts[i], reverse=True)
    for i in order[: total - sum(counts)]:
        counts[i] += 1
    return counts


def _poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def spawn(scenario: dict, adoption: float, rng: random.Random) -> list[Person]:
    crowd = scenario["crowd"]
    spawns = crowd["spawn"]
    dest_ids = [d["id"] for d in crowd["destinations"]]
    dest_w = [d["share"] for d in crowd["destinations"]]
    s, m = scenario["groups"]["share_in_groups"], scenario["groups"]["mean_size"]
    # Probability a unit (solo or group) is a group, so that a share s of people are in groups.
    q = s / (m * (1 - s) + s) if s < 1 else 1.0

    people: list[Person] = []
    n_group = 0
    counts = _apportion(crowd["total"], [z["share"] for z in spawns])
    for zone_cfg, n in zip(spawns, counts):
        left = n
        while left > 0:
            size = 1
            if left >= 2 and rng.random() < q:
                size = max(2, min(8, 2 + _poisson(rng, m - 2)))
                size = min(size, left)
            dest = rng.choices(dest_ids, dest_w)[0]
            gid = None
            if size >= 2:
                n_group += 1
                gid = f"g{n_group:05d}"
            for _ in range(size):
                people.append(Person(
                    id=f"p{len(people):05d}", group=gid, zone=zone_cfg["zone"], dest=dest,
                    has_app=rng.random() < adoption, u=rng.random(),
                    speed=rng.uniform(0.8, 1.2)))
            left -= size
    return people
