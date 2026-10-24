import math

import pytest
from crowd_core.geo import to_latlon, to_local

A = {"lat": -33.85, "lon": 151.07}


def test_origin_and_roundtrip():
    assert to_local(A, A["lat"], A["lon"]) == pytest.approx((0, 0), abs=1e-6)
    for x, y in [(10, 0), (0, 25), (-40, 60), (123.4, -77.7)]:
        for rot in (0, 33, 90, 180, -45):
            a = {**A, "rotation_deg": rot}
            lat, lon = to_latlon(a, x, y)
            assert to_local(a, lat, lon) == pytest.approx((x, y), abs=1e-6)


def test_scale_is_about_111km_per_degree_north():
    x, y = to_local(A, A["lat"] + 0.001, A["lon"])
    assert x == pytest.approx(0, abs=1e-6) and y == pytest.approx(111.19, abs=0.3)


def test_east_shrinks_with_latitude():
    x, _ = to_local(A, A["lat"], A["lon"] + 0.001)
    assert x == pytest.approx(111.19 * math.cos(math.radians(33.85)), abs=0.3)


def test_rotation_turns_axes():
    a = {**A, "rotation_deg": 90}      # +y points east
    lat, lon = to_latlon(a, 0, 100)
    x, y = to_local({**A}, lat, lon)   # same point, unrotated frame: 100 m east
    assert x == pytest.approx(100, abs=0.05) and y == pytest.approx(0, abs=0.05)
