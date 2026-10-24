import time

import pytest
from fastapi.testclient import TestClient

from crowd_server.app import create_app


@pytest.fixture()
def client():
    app = create_app(autostart=False, static_dir=None)
    with TestClient(app) as c:
        yield c
        if c.get("/api/health").json()["session"]:
            pass


def start(c, **kw):
    body = {"venue": "example-minimal-festival", "scenario": "egress-end-of-night", "total": 300,
            "speed": 60, "planner": "adaptive", **kw}
    r = c.post("/api/session", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_catalog(client):
    assert any(v["id"] == "example-minimal-festival" for v in client.get("/api/venues").json())
    sc = client.get("/api/scenarios", params={"venue": "example-minimal-festival"}).json()
    assert "egress-end-of-night" in sc and "auto-egress" in sc
    assert "adaptive" in client.get("/api/planners").json()
    assert client.get("/api/venues/../../etc/passwd").status_code in (404, 422)
    assert client.get("/api/venues/nope").status_code == 404


def test_needs_session(client):
    assert client.post("/api/control/mode", json={"mode": "evacuation"}).status_code == 409


def test_session_controls_and_guest(client):
    info = start(client)
    assert info["people"] == 300
    assert client.post("/api/control/mode", json={"mode": "evacuation"}).json()["mode"] == "evacuation"
    r = client.post("/api/control/closure", json={"threshold": "t_field_exit_south", "closed": True}).json()
    assert "t_field_exit_south" in r["closed"]
    assert client.post("/api/control/closure", json={"threshold": "nope", "closed": True}).status_code == 422
    assert client.post("/api/control/mode", json={"mode": "evacuation", "destination": "zzz"}).status_code == 422
    gid = client.post("/api/guest", json={"zone": "main_field"}).json()["person_id"]
    assert client.post("/api/guest", json={"zone": "nowhere"}).status_code == 422
    g = client.get(f"/api/guidance/{gid}").json()
    assert g["zone"] == "main_field"
    assert client.get("/api/guidance/ghost").status_code == 404
    assert client.post("/api/session/pause", json={"paused": True}).json()["paused"] is True
    assert client.post("/api/session/speed", json={"speed": 0}).status_code == 422
    assert len(client.get("/api/people", params={"limit": 4}).json()) >= 1


def test_runs_forward_and_websockets(client):
    start(client, speed=120)
    with client.websocket_connect("/ws/live") as ws:
        m = ws.receive_json()
        assert m["type"] == "state" and "zones" in m
        t0 = m["t_s"]
        for _ in range(8):
            m = ws.receive_json()
            if m["t_s"] > t0:
                break
        assert m["t_s"] > t0
    gid = client.post("/api/guest", json={"zone": "main_field"}).json()["person_id"]
    with client.websocket_connect(f"/ws/guide/{gid}") as ws:
        assert ws.receive_json()["person_id"] == gid


def test_venue_save_and_validate(client, tmp_path):
    import json
    from pathlib import Path
    v = json.loads((Path(__file__).resolve().parents[2] / "venues/example-minimal-festival.json").read_text())
    assert client.post("/api/venues/validate", json=v).json()["errors"] == []
    bad = dict(v, id="Bad Id!")
    assert client.post("/api/venues", json=bad).status_code == 422
    v["thresholds"][0]["from_zone"] = "missing"
    assert client.post("/api/venues/validate", json=v).json()["errors"]


def test_guest_changes_destination(client):
    start(client)
    gid = client.post("/api/guest", json={"zone": "main_field"}).json()["person_id"]
    r = client.post(f"/api/guidance/{gid}/destination", json={"destination": "food"})
    assert r.status_code == 200 and r.json()["destination"] == "food"
    assert client.post(f"/api/guidance/{gid}/destination", json={"destination": "zzz"}).status_code == 422
    assert client.post("/api/guidance/p00001/destination", json={"destination": "food"}).status_code == 403


def test_restart_resets_the_clock(client):
    assert client.post("/api/session/restart").status_code == 409
    start(client, speed=120)
    client.post("/api/control/mode", json={"mode": "evacuation"})
    info = client.post("/api/session/restart").json()
    assert info["mode"] == "egress" and info["people"] == 300
