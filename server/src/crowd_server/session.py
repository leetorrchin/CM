"""Live simulation sessions: one stepped in a background thread each, plus guests and a manager."""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crowd_core.geo import to_local
from crowd_core.graph import compile_venue
from crowd_sim.clock import SimClock
from crowd_sim.engine import Simulation
from crowd_sim.eventlog import EventLog
from crowd_sim.run import PLANNERS

from .position import PositionFilter

TICK_S = 0.1          # wall-clock step of the runner
PUBLISH_S = 0.5       # how often a new state is made available to clients
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
MAX_GUESTS = 300


class LimitError(Exception):
    """Too many sessions, people or guests."""


@dataclass
class Guest:
    token: str
    filter: PositionFilter
    external: bool = False
    last: dict[str, Any] = field(default_factory=dict)


class LiveSession:
    def __init__(self, venue: dict, scenario: dict, planner: str, *, sid: str, name: str = "",
                 speed: float = 5.0, app_adoption: float | None = None, demo_people: bool = False,
                 record_path: Path | None = None, owner: str = "") -> None:
        self.id, self.name, self.owner = sid, name or scenario["id"], owner
        self.venue, self.scenario, self.planner_name = venue, scenario, planner
        self.demo_people, self.record_path = demo_people, record_path
        self.created = time.time()
        clock = SimClock(scenario["start_time"])
        log = EventLog(record_path, sid, clock) if record_path else EventLog(None, sid, clock)
        self.sim = Simulation(compile_venue(venue), scenario, PLANNERS[planner](), log=log, clock=clock,
                              app_adoption=app_adoption, log_every_s=1.0 if not record_path else 5.0)
        self.sim.begin()
        self.lock = threading.RLock()
        self.speed = speed
        self.paused = False
        self.version = 0
        self.latest: dict[str, Any] = {}
        self.guests: dict[str, Guest] = {}
        self._stop = threading.Event()
        self._sim_t = 0.0
        self._publish()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"crowd-session-{sid}")
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
        st.update(type="state", id=self.id, name=self.name, planner=s.planner.name, speed=self.speed,
                  paused=self.paused, people=len(s.people), scenario=self.scenario["id"],
                  venue=self.venue["id"], queue_switches=s.queue_switches, redirected=s.redirected,
                  guests=len(self.guests), demo_people=self.demo_people, recording=bool(self.record_path))
        self.latest = st
        self.version += 1

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        try:
            self.sim.log.close()
        except Exception:  # noqa: BLE001 - closing a log must never block shutdown
            pass

    # ---- information
    def info(self) -> dict[str, Any]:
        with self.lock:
            return {k: v for k, v in self.latest.items() if k not in ("zones", "transit", "queues")}

    def public_info(self) -> dict[str, Any]:
        v = self.venue
        with self.lock:
            return {
                "id": self.id, "name": self.name, "venue": v["id"], "venue_name": v.get("name", v["id"]),
                "mode": self.sim.mode, "demo_people": self.demo_people, "has_anchor": "anchor" in v,
                "zones": [{"id": z["id"], "name": z.get("name", z["id"]), "kind": z["kind"], "level": z["level"]}
                          for z in v["zones"] if z["kind"] != "restricted"],
                "destinations": [{"id": d["id"], "name": d.get("name", d["id"]), "kind": d["kind"]}
                                 for d in v["destinations"] if d["kind"] != "entry"]}

    # ---- operator controls
    def set_speed(self, speed: float) -> None:
        with self.lock:
            self.speed = speed
            self._publish()

    def set_paused(self, paused: bool) -> None:
        with self.lock:
            self.paused = paused
            self._publish()

    def _apply_now(self, ev: dict) -> None:
        self.sim.inject(ev)
        self.sim.advance(self.sim._t + self.sim.dt)  # apply immediately so the UI sees it
        self._sim_t = max(self._sim_t, self.sim._t)
        self._publish()

    def set_mode(self, mode: str, destination: str | None) -> None:
        with self.lock:
            ev: dict[str, Any] = {"type": "mode_change", "mode": mode}
            if destination:
                ev["destination"] = destination
            self._apply_now(ev)

    def set_closure(self, threshold: str, closed: bool) -> None:
        with self.lock:
            self._apply_now({"type": "closure" if closed else "reopen", "threshold": threshold})

    # ---- guests
    def join_guest(self, zone: str, destination: str, external: bool = False) -> tuple[str, str]:
        with self.lock:
            if len(self.guests) >= MAX_GUESTS:
                raise LimitError("too many guests in this session")
            pid = self.sim.add_guest(zone, destination, external=external)
            g = Guest(secrets.token_urlsafe(16), PositionFilter(self.venue), external)
            if external:
                g.filter.zone = zone
            self.guests[pid] = g
            return pid, g.token

    def guest_ok(self, pid: str, token: str | None) -> bool:
        g = self.guests.get(pid)
        return bool(g and token and secrets.compare_digest(g.token, token))

    def leave(self, pid: str) -> None:
        with self.lock:
            self.sim.remove_guest(pid)
            self.guests.pop(pid, None)

    def set_destination(self, pid: str, destination: str) -> bool:
        with self.lock:
            return self.sim.set_destination(pid, destination)

    def set_guest_external(self, pid: str, external: bool) -> bool:
        with self.lock:
            g = self.guests.get(pid)
            if g is None or not self.sim.set_external(pid, external):
                return False
            g.external = external
            if external:
                un = self.sim.unit_of[pid]
                g.filter.zone = un.zone
            return True

    def report_position(self, pid: str, *, lat: float | None = None, lon: float | None = None,
                        x: float | None = None, y: float | None = None,
                        accuracy_m: float | None = None, level: str | None = None) -> dict[str, Any]:
        """A phone reports where it is, as GPS or as venue coordinates. Returns what the server made of it."""
        with self.lock:
            g = self.guests.get(pid)
            if g is None:
                raise KeyError(pid)
            if lat is not None and lon is not None:
                anchor = self.venue.get("anchor")
                if not anchor:
                    raise ValueError("this venue has no GPS anchor; report x and y instead")
                x, y = to_local(anchor, lat, lon)
            if x is None or y is None:
                raise ValueError("give lat and lon, or x and y")
            if not g.external:
                self.set_guest_external(pid, True)
            fix = g.filter.update(x, y, accuracy_m, level)
            if fix.zone and fix.status in ("ok", "pending"):
                self.sim.set_external_zone(pid, fix.zone)
            g.last = {"status": fix.status, "zone": fix.zone, "x": round(x, 1), "y": round(y, 1),
                      "off_venue_m": round(fix.off_venue_m, 1), "t": time.time()}
            return {k: v for k, v in g.last.items() if k != "t"}

    def guidance(self, pid: str) -> dict[str, Any] | None:
        with self.lock:
            out = self.sim.guidance(pid)
            g = self.guests.get(pid)
            if out is not None and g is not None:
                out["external"] = g.external
                out["fix"] = g.last.get("status")
            return out

    def guest_list(self) -> list[dict[str, Any]]:
        with self.lock:
            return [{"id": pid, "external": g.external, "zone": self.sim.unit_of[pid].zone,
                     "state": self.sim.unit_of[pid].state, "fix": g.last.get("status")}
                    for pid, g in self.guests.items()]

    def sample_people(self, n: int) -> list[dict[str, Any]]:
        """App users a demo phone can watch: a mix of people in groups and on their own."""
        with self.lock:
            groups, solo = [], []
            for u in self.sim.units:
                if u.has_app and u.guide_id and u.state not in ("gone", "done") and not u.id.startswith("guest-"):
                    (groups if u.size > 1 else solo).append({"id": u.guide_id, "group_size": u.size, "zone": u.zone})
                if len(groups) >= n and len(solo) >= n:
                    break
            return (groups[: n // 2] + solo)[:n]


class SessionManager:
    def __init__(self, max_sessions: int, max_people: int) -> None:
        self.max_sessions, self.max_people = max_sessions, max_people
        self._sessions: dict[str, LiveSession] = {}
        self._lock = threading.Lock()

    def new_code(self) -> str:
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
            if code not in self._sessions:
                return code

    @staticmethod
    def norm(code: str) -> str:
        return code.strip().upper()

    def create(self, venue: dict, scenario: dict, planner: str, *, code: str | None = None, **kw) -> LiveSession:
        with self._lock:
            if len(self._sessions) >= self.max_sessions:
                raise LimitError(f"at most {self.max_sessions} sessions can run at once; stop one first")
            people = sum(len(s.sim.people) for s in self._sessions.values())
            if people + scenario["crowd"]["total"] > self.max_people:
                raise LimitError(f"too many simulated people in total (limit {self.max_people:,})")
            code = self.norm(code) if code else self.new_code()
            if code in self._sessions:
                raise LimitError(f"code {code} is already in use")
            s = LiveSession(venue, scenario, planner, sid=code, **kw)
            self._sessions[code] = s
            return s

    def get(self, code: str) -> LiveSession | None:
        return self._sessions.get(self.norm(code))

    def list(self) -> list[LiveSession]:
        return sorted(self._sessions.values(), key=lambda s: s.created)

    def delete(self, code: str) -> bool:
        with self._lock:
            s = self._sessions.pop(self.norm(code), None)
        if s:
            s.stop()
        return s is not None

    def stop_all(self) -> None:
        for code in list(self._sessions):
            self.delete(code)
