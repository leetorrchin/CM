from __future__ import annotations

from math import hypot

Point = list[float] | tuple[float, float]


def polygon_area(poly: list[Point]) -> float:
    """Shoelace formula, absolute value."""
    s = 0.0
    for i, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def polygon_centroid(poly: list[Point]) -> tuple[float, float]:
    """Area-weighted centroid. Falls back to the vertex mean for degenerate polygons."""
    a = cx = cy = 0.0
    for i, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(i + 1) % len(poly)]
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-12:
        return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))
    return (cx / (3 * a), cy / (3 * a))


def midpoint(seg: list[Point]) -> tuple[float, float]:
    (x1, y1), (x2, y2) = seg
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def dist(a: Point, b: Point) -> float:
    return hypot(a[0] - b[0], a[1] - b[1])


def point_in_polygon(x: float, y: float, poly: list[Point]) -> bool:
    inside = False
    j = len(poly) - 1
    for i, (xi, yi) in enumerate(poly):
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _point_segment_distance(px: float, py: float, a: Point, b: Point) -> float:
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return hypot(px - ax, py - ay)
    f = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return hypot(px - (ax + f * dx), py - (ay + f * dy))


def polygon_distance(x: float, y: float, poly: list[Point]) -> float:
    """0 if inside, otherwise distance to the nearest edge."""
    if point_in_polygon(x, y, poly):
        return 0.0
    return min(_point_segment_distance(x, y, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def random_point_in_polygon(poly: list[Point], rng) -> tuple[float, float]:
    """Uniform point inside a polygon by rejection sampling in its bounding box."""
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    for _ in range(1000):
        x, y = rng.uniform(min(xs), max(xs)), rng.uniform(min(ys), max(ys))
        if point_in_polygon(x, y, poly):
            return (x, y)
    return polygon_centroid(poly)
