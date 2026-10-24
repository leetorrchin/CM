"""One live simulation, stepped in the background at an adjustable speed."""
from __future__ import annotations

import threading
import time
from typing import Any

from crowd_core.graph import compile_venue
from crowd_sim.clock import SimClock
from crowd_sim.engine import Simulation
from crowd_sim.eventlog import EventLog
from crowd_sim.run import PLANNERS

TICK_S = 0.1          # wall-clock step of the runner
PUBLISH_S = 0.5       # how often a new state is made available to clients


class LiveSession:
    def __init__(self, venue: dict, scenario: dict, planner: str, speed: float = 5.0,
                 app_adoption: float | None = None) -> None:
        self.venue, self.scenario, self.planner_name = venue, scenario, planner
        clock = SimClock(scenario["start_time"])
        self.sim = Simulation(compile_venue(venue), scenario, PLANNERS[planner](),
                              log=EventLog(None, "live", clock), clock=clock,
                              app_adoption=app_adoption, log_every_s=1.0)
        self.sim.begin()
        self.lock = threading.RLock()
        self.speed = speed
        self.paused = False
        self.version = 0
        self.latest: dict[str, Any] = {}
        self._stop = threading.Event()
        self._sim_t = 0.0
        self._publish()
        self._thread = threading.Thread(target=self._run, daemon=True, name="crowd-session")
        self._thread.start()

    # ---- background loop
    def _run(self) -> None:
        last = time.monotonic()
        next_pub = 0.0
        while not self._stop.wait(TICK_S):
            now = time.monotonic()
            wall, last = now - last, now
            with self.lock:
                if not self.paused:
                    self._sim_t += wall * self.speed
                    self.sim.advance(self._sim_t)
                if now >= next_pub:
                    self._publish()
                    next_pub = now + PUBLISH_S

    def _publish(self) -> None:
        s = self.sim
        st = s.state_dict(s._t)
        st.update(type="state", planner=s.planner.name, speed=self.speed, paused=self.paused,
                  people=len(s.people), scenario=self.scenario["id"], venue=self.venue["id"],
                  queue_switches=s.queue_switches, redirected=s.redirected)
        self.latest = st
        self.version += 1

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    # ---- controls
    def info(self) -> dict[str, Any]:
        with self.lock:
            return {k: v for k, v in self.latest.items() if k not in ("zones", "transit", "queues")}

    def set_speed(self, speed: float) -> None:
        with self.lock:
            self.speed = speed
            self._publish()

    def set_paused(self, paused: bool) -> None:
        with self.lock:
            self.paused = paused
            self._publish()

    def set_mode(self, mode: str, destination: str | None) -> None:
        with self.lock:
            ev = {"type": "mode_change", "mode": mode}
            if destination:
                ev["destination"] = destination
            self.sim.inject(ev)
            self.sim.advance(self.sim._t + self.sim.dt)  # apply immediately so the UI sees it
            self._sim_t = max(self._sim_t, self.sim._t)
            self._publish()

    def set_closure(self, threshold: str, closed: bool) -> None:
        with self.lock:
            self.sim.inject({"type": "closure" if closed else "reopen", "threshold": threshold})
            self.sim.advance(self.sim._t + self.sim.dt)
            self._sim_t = max(self._sim_t, self.sim._t)
            self._publish()

    def add_guest(self, zone: str, destination: str) -> str:
        with self.lock:
            return self.sim.add_guest(zone, destination)

    def set_destination(self, person_id: str, destination: str) -> bool:
        with self.lock:
            return self.sim.set_destination(person_id, destination)

    def guidance(self, person_id: str) -> dict[str, Any] | None:
        with self.lock:
            return self.sim.guidance(person_id)

    def sample_people(self, n: int) -> list[dict[str, Any]]:
        """App users a demo phone can watch: a mix of people in groups and on their own."""
        with self.lock:
            groups, solo = [], []
            for u in self.sim.units:
                if u.has_app and u.guide_id and u.state not in ("gone", "done"):
                    (groups if u.size > 1 else solo).append({"id": u.guide_id, "group_size": u.size, "zone": u.zone})
                if len(groups) >= n and len(solo) >= n:
                    break
            return (groups[: n // 2] + solo)[:n]
