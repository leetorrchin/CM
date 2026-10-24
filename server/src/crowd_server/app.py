"""crowD realtime server: REST controls, WebSocket feeds, and the web apps."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from crowd_sim.run import PLANNERS

from .catalog import Catalog
from .session import LiveSession

MODES = ("normal", "egress", "evacuation")


class StartReq(BaseModel):
    venue: str
    scenario: str = "auto-egress"
    planner: Literal["baseline", "queue-aware", "flow", "adaptive"] = "adaptive"
    total: int | None = Field(None, ge=10, le=60000)
    speed: float = Field(5.0, gt=0, le=120)
    app_adoption: float | None = Field(None, ge=0, le=1)


class SpeedReq(BaseModel):
    speed: float = Field(gt=0, le=120)


class PauseReq(BaseModel):
    paused: bool


class ModeReq(BaseModel):
    mode: Literal["normal", "egress", "evacuation"]
    destination: str | None = None


class ClosureReq(BaseModel):
    threshold: str
    closed: bool


class GuestReq(BaseModel):
    zone: str
    destination: str = "nearest_safe"


class DestReq(BaseModel):
    destination: str


class App:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self.session: LiveSession | None = None
        self.last_req: StartReq | None = None

    def need(self) -> LiveSession:
        if self.session is None:
            raise HTTPException(409, "no session running; start one first")
        return self.session

    def start(self, req: StartReq) -> LiveSession:
        try:
            venue = self.catalog.get_venue(req.venue)
        except KeyError:
            raise HTTPException(404, f"unknown venue '{req.venue}'")
        try:
            sc = self.catalog.get_scenario(venue, req.scenario, req.total)
        except KeyError:
            raise HTTPException(404, f"unknown scenario '{req.scenario}'")
        except ValueError as e:
            raise HTTPException(422, str(e))
        new = LiveSession(venue, sc, req.planner, req.speed, req.app_adoption)
        self.last_req = req
        old, self.session = self.session, new
        if old:
            old.stop()
        return new


def create_app(root: Path | None = None, static_dir: Path | None = None, autostart: bool | None = None) -> FastAPI:
    cat = Catalog(root)
    state = App(cat)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        if state.session:
            state.session.stop()

    api = FastAPI(title="crowD server", version="0.1.0", lifespan=lifespan)

    @api.get("/api/health")
    def health():
        return {"ok": True, "session": state.session.info() if state.session else None}

    # ---- catalog
    @api.get("/api/venues")
    def venues():
        return cat.list_venues()

    @api.get("/api/venues/{vid}")
    def venue(vid: str):
        try:
            return cat.get_venue(vid)
        except KeyError:
            raise HTTPException(404, "unknown venue")

    @api.post("/api/venues")
    def save_venue(venue: dict):
        errs = cat.save_user_venue(venue)
        if errs:
            raise HTTPException(422, {"errors": errs})
        return {"ok": True, "id": venue["id"]}

    @api.post("/api/venues/validate")
    def validate_venue_api(venue: dict):
        from crowd_core.venue import validate_venue
        return {"errors": validate_venue(venue)}

    @api.get("/api/scenarios")
    def scenarios(venue: str):
        return cat.list_scenarios(venue)

    @api.get("/api/planners")
    def planners():
        return sorted(PLANNERS)

    # ---- session
    @api.post("/api/session")
    def start(req: StartReq):
        return state.start(req).info()

    @api.post("/api/session/restart")
    def restart():
        if state.last_req is None:
            raise HTTPException(409, "no session to restart")
        req = state.last_req.model_copy(update={"speed": state.session.speed if state.session else state.last_req.speed})
        return state.start(req).info()

    @api.get("/api/session")
    def session_info():
        return state.need().info()

    @api.post("/api/session/speed")
    def speed(req: SpeedReq):
        state.need().set_speed(req.speed)
        return state.need().info()

    @api.post("/api/session/pause")
    def pause(req: PauseReq):
        state.need().set_paused(req.paused)
        return state.need().info()

    @api.post("/api/control/mode")
    def mode(req: ModeReq):
        s = state.need()
        dest = req.destination or ("nearest_safe" if req.mode == "evacuation" else None)
        if dest and dest != "nearest_safe" and dest not in {d["id"] for d in s.venue["destinations"]}:
            raise HTTPException(422, f"unknown destination '{dest}'")
        s.set_mode(req.mode, dest)
        return s.info()

    @api.post("/api/control/closure")
    def closure(req: ClosureReq):
        s = state.need()
        th = next((t for t in s.venue["thresholds"] if t["id"] == req.threshold), None)
        if th is None:
            raise HTTPException(422, f"unknown threshold '{req.threshold}'")
        if req.closed and not th.get("closable", True):
            raise HTTPException(422, f"threshold '{req.threshold}' cannot be closed")
        s.set_closure(req.threshold, req.closed)
        return s.info()

    # ---- attendees
    @api.get("/api/people")
    def people(limit: int = 8):
        return state.need().sample_people(max(1, min(limit, 50)))

    @api.post("/api/guest")
    def guest(req: GuestReq):
        s = state.need()
        if req.zone not in {z["id"] for z in s.venue["zones"]}:
            raise HTTPException(422, f"unknown zone '{req.zone}'")
        if req.destination != "nearest_safe" and req.destination not in {d["id"] for d in s.venue["destinations"]}:
            raise HTTPException(422, f"unknown destination '{req.destination}'")
        return {"person_id": s.add_guest(req.zone, req.destination)}

    @api.post("/api/guidance/{pid}/destination")
    def set_destination(pid: str, req: DestReq):
        s = state.need()
        if not pid.startswith("guest-"):
            raise HTTPException(403, "only guests can change destination")
        if not s.set_destination(pid, req.destination):
            raise HTTPException(422, "cannot change destination")
        return s.guidance(pid)

    @api.get("/api/guidance/{pid}")
    def guidance(pid: str):
        g = state.need().guidance(pid)
        if g is None:
            raise HTTPException(404, "unknown person")
        return g

    # ---- websockets
    @api.websocket("/ws/live")
    async def ws_live(ws: WebSocket):
        await ws.accept()
        s = state.session
        if s is None:
            await ws.send_json({"type": "idle"})
        last, cur = -1, s
        try:
            while True:
                s = state.session
                if s is not cur:
                    cur, last = s, -1
                if s is not None and s.version != last:
                    last = s.version
                    await ws.send_json(s.latest)
                await asyncio.sleep(0.25)
        except (WebSocketDisconnect, RuntimeError):
            return

    @api.websocket("/ws/guide/{pid}")
    async def ws_guide(ws: WebSocket, pid: str):
        await ws.accept()
        try:
            while True:
                s = state.session
                g = s.guidance(pid) if s else None
                await ws.send_json(g if g else {"person_id": pid, "error": "unknown person or no session"})
                await asyncio.sleep(1.0)
        except (WebSocketDisconnect, RuntimeError):
            return

    if autostart is None:
        autostart = os.environ.get("CROWD_AUTOSTART", "1") != "0"
    if autostart:
        try:
            state.start(StartReq(venue=os.environ.get("CROWD_VENUE", "example-minimal-festival"),
                                 scenario=os.environ.get("CROWD_SCENARIO", "egress-end-of-night"),
                                 total=int(os.environ.get("CROWD_TOTAL", "3000")),
                                 speed=float(os.environ.get("CROWD_SPEED", "5"))))
        except HTTPException:
            pass

    static = static_dir or Path(os.environ.get("CROWD_STATIC", cat.root / "viz" / "dist"))
    if static.is_dir():
        api.mount("/", StaticFiles(directory=static, html=True), name="web")
    else:
        @api.get("/")
        def no_web():
            return {"message": "web apps not built; run `npm run build` in viz/ (see README)"}
    return api


def app_factory() -> FastAPI:
    return create_app()
