import time

import pytest
from crowd_server.auth import Throttle, Tokens, Users
from crowd_server.position import PositionFilter

V = {"zones": [
    {"id": "a", "level": "g", "kind": "open_area", "polygon": [[0, 0], [20, 0], [20, 20], [0, 20]]},
    {"id": "b", "level": "g", "kind": "open_area", "polygon": [[20, 0], [40, 0], [40, 20], [20, 20]]},
]}


def test_first_fix_commits_and_moves_need_confirmation():
    f = PositionFilter(V)
    r = f.update(5, 5)
    assert (r.status, r.zone, r.changed) == ("ok", "a", True)
    r = f.update(30, 10)                       # first report in b: not yet
    assert (r.status, r.zone, r.changed) == ("pending", "a", False)
    r = f.update(31, 10)
    assert (r.zone, r.changed) == ("b", True)


def test_jitter_at_the_border_does_not_flip_zones():
    f = PositionFilter(V)
    f.update(15, 10)
    for x in (20.5, 21.0, 19.5, 21.5, 20.2):
        assert f.update(x, 10).zone == "a"


def test_bad_accuracy_and_outside_venue_are_ignored():
    f = PositionFilter(V)
    f.update(5, 5)
    assert f.update(35, 5, accuracy_m=120).status == "low_accuracy" and f.zone == "a"
    r = f.update(500, 500)
    assert r.status == "outside_venue" and r.zone == "a"


def test_users_and_tokens(tmp_path):
    u = Users(tmp_path)
    u.add("Alice", "correct horse", "operator")
    assert u.verify("alice", "correct horse") == "operator"
    assert u.verify("alice", "wrong") is None and u.verify("nobody", "x") is None
    with pytest.raises(ValueError):
        u.add("bob", "short")
    with pytest.raises(ValueError):
        u.add("bad name!", "longenough")
    assert Users(tmp_path).verify("alice", "correct horse") == "operator"   # persisted
    t = Tokens(tmp_path, 60)
    tok, _ = t.issue("alice", "operator")
    assert t.verify(tok)["role"] == "operator"
    assert t.verify(tok[:-2] + "xx") is None and t.verify("garbage") is None and t.verify(None) is None
    assert Tokens(tmp_path, 60).verify(tok) is not None                      # same key reloaded
    expired = Tokens(tmp_path, -5)
    assert expired.verify(expired.issue("alice", "viewer")[0]) is None


def test_throttle():
    th = Throttle(max_fails=3, window_s=1)
    for _ in range(3):
        th.fail("ip")
    assert th.blocked("ip")
    time.sleep(1.1)
    assert not th.blocked("ip")
