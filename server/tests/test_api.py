import time
from pathlib import Path

import pytest
from crowd_server.app import create_app
from crowd_server.catalog import find_root
from crowd_server.settings import Settings
from fastapi.testclient import TestClient

ROOT = find_root()
START = {"venue": "example-minimal-festival", "scenario": "egress-end-of-night", "total": 200, "speed": 20}


def make(tmp_path: Path, auth: bool = False, autostart: bool = False, **kw) -> TestClient:
    st = Settings(root=ROOT, data_dir=tmp_path / "data", auth=auth, autostart=autostart, static_dir=None, **kw)
    return TestClient(create_app(ROOT, st))


@pytest.fixture
def c(tmp_path):
    with make(tmp_path) as cl:
        yield cl


def test_health_and_catalog(c):
    assert c.get("/api/health").json()["ok"]
    assert any(v["id"] == "example-minimal-festival" for v in c.get("/api/venues").json())
    assert "adaptive" in c.get("/api/planners").json()
    assert c.get("/api/scenarios", params={"venue": "example-minimal-festival"}).json()


def test_session_lifecycle(c):
    r = c.post("/api/sessions", json={**START, "code": "ABCD"})
    assert r.status_code == 200 and r.json()["id"] == "ABCD"
    assert [s["id"] for s in c.get("/api/sessions").json()] == ["ABCD"]
    assert c.post("/api/sessions", json={**START, "code": "abcd"}).status_code == 409
    assert c.post("/api/sessions/ABCD/speed", json={"speed": 40}).json()["speed"] == 40
    assert c.post("/api/sessions/ABCD/pause", json={"paused": True}).status_code == 200
    assert c.post("/api/sessions/ABCD/mode", json={"mode": "evacuation"}).status_code == 200
    assert c.post("/api/sessions/ABCD/mode", json={"mode": "evacuation", "destination": "nope"}).status_code == 422
    assert c.post("/api/sessions/ABCD/closure", json={"threshold": "nope", "closed": True}).status_code == 422
    assert c.post("/api/sessions/ABCD/restart").json()["id"] == "ABCD"
    assert c.delete("/api/sessions/ABCD").status_code == 200
    assert c.get("/api/sessions/ABCD").status_code == 404


def test_several_sessions_and_limits(tmp_path):
    with make(tmp_path, max_sessions=2) as c:
        a = c.post("/api/sessions", json=START).json()["id"]
        b = c.post("/api/sessions", json=START).json()["id"]
        assert a != b
        assert c.post("/api/sessions", json=START).status_code == 409
        c.delete(f"/api/sessions/{a}")
        assert c.post("/api/sessions", json=START).status_code == 200
    with make(tmp_path, max_total_people=300) as c:
        assert c.post("/api/sessions", json=START).status_code == 200
        assert c.post("/api/sessions", json=START).status_code == 409


def test_bad_requests(c):
    assert c.post("/api/sessions", json={**START, "venue": "nope"}).status_code == 404
    assert c.post("/api/sessions", json={**START, "scenario": "nope"}).status_code == 404
    assert c.post("/api/sessions", json={**START, "code": "a b!"}).status_code == 422
    assert c.get("/api/join/ZZZZ").status_code == 404


def test_guest_flow(c):
    code = c.post("/api/sessions", json={**START, "code": "JOIN1"}).json()["id"]
    info = c.get(f"/api/join/{code}").json()
    assert info["id"] == code and "demo_people" in info
    venue = c.get(f"/api/join/{code}/venue").json()
    zone = venue["zones"][0]["id"]
    assert c.post(f"/api/join/{code}/guest", json={"zone": "nope"}).status_code == 422
    g = c.post(f"/api/join/{code}/guest", json={"zone": zone}).json()
    pid, tok = g["person_id"], g["token"]
    h = {"X-Guest-Token": tok}
    assert c.get(f"/api/join/{code}/guest/{pid}/guidance").status_code == 403
    gd = c.get(f"/api/join/{code}/guest/{pid}/guidance", headers=h).json()
    assert gd["person_id"] == pid
    assert c.get(f"/api/join/{code}/guest/{pid}/guidance", params={"token": tok}).status_code == 200
    assert c.get(f"/api/join/{code}/guest/{pid}/guidance", headers={"X-Guest-Token": "bad"}).status_code == 403
    assert c.get(f"/api/join/{code}/people").status_code == 403
    r = c.post(f"/api/join/{code}/guest/{pid}/position", headers=h, json={"x": 1.0, "y": 1.0, "accuracy_m": 5})
    assert r.status_code == 200
    assert c.post(f"/api/join/{code}/guest/{pid}/position", headers=h, json={"lat": 1.0}).status_code == 422
    assert c.post(f"/api/join/{code}/guest/{pid}/mode", headers=h, json={"external": True}).status_code == 200
    assert c.delete(f"/api/join/{code}/guest/{pid}", headers=h).status_code == 200
    assert c.get(f"/api/join/{code}/guest/{pid}/guidance", headers=h).status_code in (403, 404)


def test_demo_people_visible(c):
    c.post("/api/sessions", json={**START, "code": "DEMO", "demo_people": True})
    time.sleep(0.8)
    ppl = c.get("/api/join/DEMO/people").json()
    assert ppl
    pid = ppl[0]["person_id"] if "person_id" in ppl[0] else ppl[0]["id"]
    assert c.get(f"/api/join/DEMO/guest/{pid}/guidance").status_code == 200


def test_websockets(c):
    c.post("/api/sessions", json={**START, "code": "WSWS"})
    with c.websocket_connect("/ws/sessions/WSWS") as ws:
        m = ws.receive_json()
        assert "t" in m or "zones" in m
    with c.websocket_connect("/ws/join/WSWS/live") as ws:
        assert ws.receive_json()
    with pytest.raises(Exception):
        with c.websocket_connect("/ws/join/NOPE/live"):
            pass


def test_auth_required(tmp_path):
    st = Settings(root=ROOT, data_dir=tmp_path / "d", auth=True, autostart=False, static_dir=None)
    import os
    os.environ["CROWD_ADMIN_PASSWORD"] = "pw-test-123"
    try:
        with TestClient(create_app(ROOT, st)) as c:
            assert c.get("/api/health").json()["auth"] is True
            assert c.get("/api/sessions").status_code == 401
            assert c.post("/api/sessions", json=START).status_code == 401
            assert c.post("/api/login", json={"username": "admin", "password": "x"}).status_code == 401
            tok = c.post("/api/login", json={"username": "admin", "password": "pw-test-123"}).json()["token"]
            h = {"Authorization": f"Bearer {tok}"}
            assert c.get("/api/me", headers=h).json()["role"] == "operator"
            assert c.post("/api/sessions", json={**START, "code": "AUTH"}, headers=h).status_code == 200
            # public join stays open
            assert c.get("/api/join/AUTH").status_code == 200
            with c.websocket_connect(f"/ws/sessions/AUTH?token={tok}") as ws:
                assert ws.receive_json()
            with pytest.raises(Exception):
                with c.websocket_connect("/ws/sessions/AUTH"):
                    pass
    finally:
        os.environ.pop("CROWD_ADMIN_PASSWORD")


def test_viewer_cannot_operate(tmp_path):
    from crowd_server.auth import Users
    st = Settings(root=ROOT, data_dir=tmp_path / "d", auth=True, autostart=False, static_dir=None)
    Users(st.data_dir).add("op", "operatorpass1", "operator")
    Users(st.data_dir).add("vw", "viewerpass12", "viewer")
    with TestClient(create_app(ROOT, st)) as c:
        t = c.post("/api/login", json={"username": "vw", "password": "viewerpass12"}).json()["token"]
        h = {"Authorization": f"Bearer {t}"}
        assert c.get("/api/sessions", headers=h).status_code == 200
        assert c.post("/api/sessions", json=START, headers=h).status_code == 403


def test_login_throttle(tmp_path):
    st = Settings(root=ROOT, data_dir=tmp_path / "d", auth=True, autostart=False, static_dir=None)
    with TestClient(create_app(ROOT, st)) as c:
        codes = [c.post("/api/login", json={"username": "admin", "password": "bad"}).status_code for _ in range(7)]
        assert codes[0] == 401 and codes[-1] == 429


def test_autostart_demo(tmp_path):
    with make(tmp_path, autostart=True) as c:
        assert c.get("/api/join/DEMO").json()["demo_people"] is True
