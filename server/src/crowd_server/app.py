"""crowD realtime server: sessions, logins, public join API for phones, WebSocket feeds, web apps."""
from __future__ import annotations

import asyncio
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from crowd_sim.run import PLANNERS
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import Throttle, Tokens, Users
from .catalog import Catalog
from .session import LimitError, LiveSession, SessionManager
from .settings import Settings

VERSION = "0.2.0"
CODE_RE = re.compile(r"^[A-Za-z0-9]{4,12}$")
Planner = Literal["baseline", "queue-aware", "flow", "adaptive"]


class StartReq(BaseModel):
    venue: str
    scenario: str = "auto-egress"
    planner: Planner = "adaptive"
    total: int | None = Field(None, ge=10, le=60000)
    speed: float = Field(5.0, gt=0, le=120)
    app_adoption: float | None = Field(None, ge=0, le=1)
    name: str = Field("", max_length=60)
    code: str | None = None
    demo_people: bool = False
    record: bool = False


class LoginReq(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=200)


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
    external: bool = False


class DestReq(BaseModel):
    destination: str


class ExternalReq(BaseModel):
    external: bool


class PositionReq(BaseModel):
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    x: float | None = Field(None, ge=-100000, le=100000)
    y: float | None = Field(None, ge=-100000, le=100000)
    accuracy_m: float | None = Field(None, ge=0, le=100000)
    level: str | None = None


def create_app(root: Path | None = None, settings: Settings | None = None, *, autostart: bool | None = None,
               static_dir: Path | None = None, auth: bool | None = None) -> FastAPI:
    cat = Catalog(root)
    st = settings or Settings.from_env(cat.root)
    if auth is not None:
        st.auth = auth
    if autostart is not None:
        st.autostart = autostart
    if static_dir is not None:
        st.static_dir = static_dir
    users, tokens, throttle = Users(st.data_dir), Tokens(st.data_dir, st.token_ttl_s), Throttle()
    mgr = SessionManager(st.max_sessions, st.max_total_people)
    params: dict[str, StartReq] = {}
    bootstrap: dict[str, str] = {}

    def start_session(req: StartReq, owner: str = "") -> LiveSession:
        try:
            venue = cat.get_venue(req.venue)
        except KeyError:
            raise HTTPException(404, f"unknown venue '{req.venue}'")
        try:
            sc = cat.get_scenario(venue, req.scenario, req.total)
        except KeyError:
            raise HTTPException(404, f"unknown scenario '{req.scenario}'")
        except ValueError as e:
            raise HTTPException(422, str(e))
        if req.code and not CODE_RE.match(req.code):
            raise HTTPException(422, "code must be 4 to 12 letters or digits")
        rec = None
        if req.record:
            code_hint = (req.code or "live").upper()
            rec = cat.root / "runs" / f"live-{code_hint}-{int(__import__('time').time())}.jsonl"
            rec.parent.mkdir(parents=True, exist_ok=True)
        try:
            s = mgr.create(venue, sc, req.planner, code=req.code, name=req.name, speed=req.speed,
                           app_adoption=req.app_adoption, demo_people=req.demo_people, record_path=rec, owner=owner)
        except LimitError as e:
            raise HTTPException(409, str(e))
        params[s.id] = req
        return s

    @asynccontextmanager
    async def lifespan(_app):
        yield
        mgr.stop_all()

    api = FastAPI(title="crowD server", version=VERSION, lifespan=lifespan)

    # ------------------------------------------------------------------ auth
    def who(authorization: str | None, token: str | None = None) -> dict | None:
        if not st.auth:
            return {"user": "local", "role": "operator", "exp": 0}
        tok = token
        if authorization and authorization.lower().startswith("bearer "):
            tok = authorization[7:].strip()
        return tokens.verify(tok)

    def need(role: str):
        def dep(authorization: str | None = Header(None), token: str | None = Query(None)) -> dict:
            p = who(authorization, token)
            if p is None:
                raise HTTPException(401, "login required")
            if role == "operator" and p["role"] != "operator":
                raise HTTPException(403, "operator role required")
            return p
        return dep

    viewer, operator = need("viewer"), need("operator")

    @api.get("/api/health")
    def health():
        return {"ok": True, "version": VERSION, "auth": st.auth, "sessions": len(mgr.list()),
                "needs_setup": st.auth and len(users) == 0}

    @api.post("/api/login")
    def login(req: LoginReq, request: Request):
        if not st.auth:
            return {"token": "", "user": "local", "role": "operator", "exp": 0}
        ip = request.client.host if request.client else "?"
        if throttle.blocked(ip):
            raise HTTPException(429, "too many failed logins; wait a few minutes")
        role = users.verify(req.username, req.password)
        if role is None:
            throttle.fail(ip)
            raise HTTPException(401, "wrong username or password")
        throttle.ok(ip)
        token, exp = tokens.issue(req.username.strip().lower(), role)
        return {"token": token, "user": req.username.strip().lower(), "role": role, "exp": exp}

    @api.get("/api/me")
    def me(p: dict = Depends(viewer)):
        return {"user": p["user"], "role": p["role"]}

    # ------------------------------------------------------------------ catalog
    @api.get("/api/venues")
    def venues(_: dict = Depends(viewer)):
        return cat.list_venues()

    @api.get("/api/venues/{vid}")
    def venue(vid: str, _: dict = Depends(viewer)):
        try:
            return cat.get_venue(vid)
        except KeyError:
            raise HTTPException(404, "unknown venue")

    @api.post("/api/venues")
    def save_venue(venue: dict, _: dict = Depends(operator)):
        errs = cat.save_user_venue(venue)
        if errs:
            raise HTTPException(422, {"errors": errs})
        return {"ok": True, "id": venue["id"]}

    @api.post("/api/venues/validate")
    def validate_venue_api(venue: dict, _: dict = Depends(operator)):
        from crowd_core.venue import validate_venue
        return {"errors": validate_venue(venue)}

    @api.get("/api/scenarios")
    def scenarios(venue: str, _: dict = Depends(viewer)):
        return cat.list_scenarios(venue)

    @api.get("/api/planners")
    def planners(_: dict = Depends(viewer)):
        return sorted(PLANNERS)

    # ------------------------------------------------------------------ sessions (organisers)
    def sess(sid: str) -> LiveSession:
        s = mgr.get(sid)
        if s is None:
            raise HTTPException(404, "unknown session")
        return s

    @api.get("/api/sessions")
    def list_sessions(_: dict = Depends(viewer)):
        return [s.info() for s in mgr.list()]

    @api.post("/api/sessions")
    def create_session(req: StartReq, p: dict = Depends(operator)):
        return start_session(req, p["user"]).info()

    @api.get("/api/sessions/{sid}")
    def get_session(sid: str, _: dict = Depends(viewer)):
        return sess(sid).info()

    @api.delete("/api/sessions/{sid}")
    def delete_session(sid: str, _: dict = Depends(operator)):
        sess(sid)
        mgr.delete(sid)
        params.pop(sid.upper(), None)
        return {"ok": True}

    @api.post("/api/sessions/{sid}/restart")
    def restart(sid: str, _: dict = Depends(operator)):
        s = sess(sid)
        req = params[s.id].model_copy(update={"speed": s.speed, "code": s.id})
        mgr.delete(sid)
        return start_session(req, s.owner).info()

    @api.post("/api/sessions/{sid}/speed")
    def speed(sid: str, req: SpeedReq, _: dict = Depends(operator)):
        s = sess(sid)
        s.set_speed(req.speed)
        return s.info()

    @api.post("/api/sessions/{sid}/pause")
    def pause(sid: str, req: PauseReq, _: dict = Depends(operator)):
        s = sess(sid)
        s.set_paused(req.paused)
        return s.info()

    @api.post("/api/sessions/{sid}/mode")
    def mode(sid: str, req: ModeReq, _: dict = Depends(operator)):
        s = sess(sid)
        dest = req.destination or ("nearest_safe" if req.mode == "evacuation" else None)
        if dest and dest != "nearest_safe" and dest not in {d["id"] for d in s.venue["destinations"]}:
            raise HTTPException(422, f"unknown destination '{dest}'")
        s.set_mode(req.mode, dest)
        return s.info()

    @api.post("/api/sessions/{sid}/closure")
    def closure(sid: str, req: ClosureReq, _: dict = Depends(operator)):
        s = sess(sid)
        th = next((t for t in s.venue["thresholds"] if t["id"] == req.threshold), None)
        if th is None:
            raise HTTPException(422, f"unknown threshold '{req.threshold}'")
        if req.closed and not th.get("closable", True):
            raise HTTPException(422, f"threshold '{req.threshold}' cannot be closed")
        s.set_closure(req.threshold, req.closed)
        return s.info()

    @api.get("/api/sessions/{sid}/venue")
    def session_venue(sid: str, _: dict = Depends(viewer)):
        return sess(sid).venue

    @api.get("/api/sessions/{sid}/guests")
    def guests(sid: str, _: dict = Depends(viewer)):
        return sess(sid).guest_list()

    @api.websocket("/ws/sessions/{sid}")
    async def ws_session(ws: WebSocket, sid: str, token: str | None = None):
        if who(None, token) is None:
            await ws.close(code=4401)
            return
        s = mgr.get(sid)
        if s is None:
            await ws.close(code=4404)
            return
        await ws.accept()
        await _pump(ws, lambda: mgr.get(sid))

    async def _pump(ws: WebSocket, getter) -> None:
        last, cur = -1, None
        try:
            while True:
                s = getter()
                if s is None:
                    await ws.send_json({"type": "ended"})
                    await ws.close()
                    return
                if s is not cur:
                    cur, last = s, -1
                if s.version != last:
                    last = s.version
                    await ws.send_json(s.latest)
                await asyncio.sleep(0.25)
        except (WebSocketDisconnect, RuntimeError):
            return

    # ------------------------------------------------------------------ public join API (phones)
    def pub(code: str) -> LiveSession:
        s = mgr.get(code) if CODE_RE.match(code) else None
        if s is None:
            raise HTTPException(404, "no event with that code")
        return s

    def guest_s(code: str, pid: str, x_guest_token: str | None, token: str | None) -> LiveSession:
        s = pub(code)
        if pid.startswith("guest-"):
            if not s.guest_ok(pid, x_guest_token or token):
                raise HTTPException(403, "bad guest token")
        elif not s.demo_people:
            raise HTTPException(403, "this event does not allow watching simulated people")
        return s

    @api.get("/api/join/{code}")
    def join_info(code: str):
        return pub(code).public_info()

    @api.get("/api/join/{code}/venue")
    def join_venue(code: str):
        return pub(code).venue

    @api.get("/api/join/{code}/people")
    def join_people(code: str, limit: int = 8):
        s = pub(code)
        if not s.demo_people:
            raise HTTPException(403, "this event does not allow watching simulated people")
        return s.sample_people(max(1, min(limit, 50)))

    @api.post("/api/join/{code}/guest")
    def join_guest(code: str, req: GuestReq):
        s = pub(code)
        if req.zone not in {z["id"] for z in s.venue["zones"]}:
            raise HTTPException(422, f"unknown zone '{req.zone}'")
        if req.destination != "nearest_safe" and req.destination not in {d["id"] for d in s.venue["destinations"]}:
            raise HTTPException(422, f"unknown destination '{req.destination}'")
        try:
            pid, tok = s.join_guest(req.zone, req.destination, req.external)
        except LimitError as e:
            raise HTTPException(429, str(e))
        return {"person_id": pid, "token": tok}

    @api.get("/api/join/{code}/guest/{pid}/guidance")
    def join_guidance(code: str, pid: str, x_guest_token: str | None = Header(None), token: str | None = None):
        s = guest_s(code, pid, x_guest_token, token)
        g = s.guidance(pid)
        if g is None:
            raise HTTPException(404, "unknown person")
        return g

    @api.post("/api/join/{code}/guest/{pid}/destination")
    def join_destination(code: str, pid: str, req: DestReq, x_guest_token: str | None = Header(None)):
        s = guest_s(code, pid, x_guest_token, None)
        if not pid.startswith("guest-"):
            raise HTTPException(403, "only guests can change destination")
        if not s.set_destination(pid, req.destination):
            raise HTTPException(422, "cannot change destination")
        return s.guidance(pid)

    @api.post("/api/join/{code}/guest/{pid}/position")
    def join_position(code: str, pid: str, req: PositionReq, x_guest_token: str | None = Header(None)):
        s = guest_s(code, pid, x_guest_token, None)
        if not pid.startswith("guest-"):
            raise HTTPException(403, "only guests can report a position")
        try:
            return s.report_position(pid, lat=req.lat, lon=req.lon, x=req.x, y=req.y,
                                     accuracy_m=req.accuracy_m, level=req.level)
        except ValueError as e:
            raise HTTPException(422, str(e))

    @api.post("/api/join/{code}/guest/{pid}/mode")
    def join_mode(code: str, pid: str, req: ExternalReq, x_guest_token: str | None = Header(None)):
        s = guest_s(code, pid, x_guest_token, None)
        if not s.set_guest_external(pid, req.external):
            raise HTTPException(422, "cannot change mode")
        return s.guidance(pid)

    @api.delete("/api/join/{code}/guest/{pid}")
    def join_leave(code: str, pid: str, x_guest_token: str | None = Header(None)):
        s = guest_s(code, pid, x_guest_token, None)
        s.leave(pid)
        return {"ok": True}

    @api.websocket("/ws/join/{code}/live")
    async def ws_join_live(ws: WebSocket, code: str):
        if not CODE_RE.match(code) or mgr.get(code) is None:
            await ws.close(code=4404)
            return
        await ws.accept()
        await _pump(ws, lambda: mgr.get(code))

    @api.websocket("/ws/join/{code}/guide/{pid}")
    async def ws_join_guide(ws: WebSocket, code: str, pid: str, token: str | None = None):
        s = mgr.get(code) if CODE_RE.match(code) else None
        ok = s is not None and ((pid.startswith("guest-") and s.guest_ok(pid, token)) or
                                (not pid.startswith("guest-") and s.demo_people))
        if not ok:
            await ws.close(code=4403)
            return
        await ws.accept()
        try:
            while True:
                s = mgr.get(code)
                g = s.guidance(pid) if s else None
                await ws.send_json(g if g else {"person_id": pid, "error": "unknown person or session ended"})
                await asyncio.sleep(1.0)
        except (WebSocketDisconnect, RuntimeError):
            return

    # ------------------------------------------------------------------ boot
    if st.auth and len(users) == 0:
        env_pw = os.environ.get("CROWD_ADMIN_PASSWORD")
        pw = env_pw or secrets.token_urlsafe(9)
        name = os.environ.get("CROWD_ADMIN_USER", "admin")
        users.add(name, pw, "operator")
        bootstrap.update(user=name, password=pw, generated=str(not env_pw))
        print(f"\n  First start: created operator account '{name}'"
              + (f" with password: {pw}" if not env_pw else " (password from CROWD_ADMIN_PASSWORD)") + "\n", flush=True)
    api.state.bootstrap = bootstrap
    api.state.manager = mgr

    if st.autostart:
        try:
            demo = start_session(StartReq(
                venue=os.environ.get("CROWD_VENUE", "example-minimal-festival"),
                scenario=os.environ.get("CROWD_SCENARIO", "egress-end-of-night"),
                total=int(os.environ.get("CROWD_TOTAL", "3000")), speed=float(os.environ.get("CROWD_SPEED", "5")),
                name="Demo", code=os.environ.get("CROWD_DEMO_CODE", "DEMO"), demo_people=True), "system")
            print(f"  Demo event running. Phones join with code {demo.id}: /app.html?s={demo.id}\n", flush=True)
        except HTTPException:
            pass

    if st.static_dir and st.static_dir.is_dir():
        api.mount("/", StaticFiles(directory=st.static_dir, html=True), name="web")
    else:
        @api.get("/")
        def no_web():
            return {"message": "web apps not built; run `npm run build` in viz/ (see README)"}
    return api


def app_factory() -> FastAPI:
    return create_app()
