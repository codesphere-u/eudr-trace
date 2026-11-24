"""Pure-Python spherical geodesy and 2D computational geometry for EUDR plot validation."""

from __future__ import annotations

import math
from decimal import Decimal

# WGS84 mean authalic Earth radius in meters (IUGG / NASA)
WGS84_EARTH_RADIUS_M = 6_371_008.7714

Point2D = tuple[float, float]  # (longitude, latitude)
Ring = list[Point2D]


def decimal_places(value: float | int | str) -> int:
    """Count fractional decimal digits on a coordinate without float representation artifacts."""
    d = Decimal(str(value)).normalize()
    exp = d.as_tuple().exponent
    if not isinstance(exp, int):
        return 0
    return max(0, -exp)


def ring_signed_area_2d(ring: Ring) -> float:
    """Compute signed shoelace area in lon/lat degrees (>0 means counter-clockwise / RFC 7946)."""
    if len(ring) < 4:
        return 0.0
    total = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        total += (x1 * y2) - (x2 * y1)
    return 0.5 * total


def ring_geodesic_area_sq_m(ring: Ring) -> float:
    """Compute exact spherical excess geodesic area in square meters (Chamberlain & Duquette, 2007)."""
    n = len(ring)
    if n < 4:
        return 0.0
    # Use unique vertices (drop closing vertex if repeated)
    pts = ring[:-1] if ring[0] == ring[-1] else ring
    m = len(pts)
    if m < 3:
        return 0.0

    total = 0.0
    for i in range(m):
        lon1, _lat1 = pts[i]
        _lon2, lat2 = pts[(i + 1) % m]
        lon3, _lat3 = pts[(i + 2) % m]
        total += (math.radians(lon3) - math.radians(lon1)) * math.sin(math.radians(lat2))

    area = abs(total) * (WGS84_EARTH_RADIUS_M**2) / 2.0
    return area


def polygon_geodesic_area_hectares(rings: list[Ring]) -> float:
    """Compute polygon area in hectares (outer ring minus any interior holes)."""
    if not rings:
        return 0.0
    outer_sq_m = ring_geodesic_area_sq_m(rings[0])
    holes_sq_m = sum(ring_geodesic_area_sq_m(hole) for hole in rings[1:])
    return max(0.0, outer_sq_m - holes_sq_m) / 10_000.0


def _orientation(a: Point2D, b: Point2D, c: Point2D) -> int:
    val = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
    if abs(val) < 1e-12:
        return 0
    return 1 if val > 0 else 2


def _on_segment(a: Point2D, b: Point2D, c: Point2D) -> bool:
    return (
        min(a[0], c[0]) - 1e-12 <= b[0] <= max(a[0], c[0]) + 1e-12
        and min(a[1], c[1]) - 1e-12 <= b[1] <= max(a[1], c[1]) + 1e-12
    )


def segments_intersect(p1: Point2D, q1: Point2D, p2: Point2D, q2: Point2D) -> bool:
    """Return True if closed 2D segments (p1, q1) and (p2, q2) intersect."""
    o1 = _orientation(p1, q1, p2)
    o2 = _orientation(p1, q1, q2)
    o3 = _orientation(p2, q2, p1)
    o4 = _orientation(p2, q2, q1)

    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and _on_segment(p1, p2, q1):
        return True
    if o2 == 0 and _on_segment(p1, q2, q1):
        return True
    if o3 == 0 and _on_segment(p2, p1, q2):
        return True
    return bool(o4 == 0 and _on_segment(p2, q1, q2))


def ring_has_self_intersection(ring: Ring) -> bool:
    """Detect figure-8 / bowtie self-intersections between non-adjacent edges of a ring."""
    if len(ring) < 4:
        return False
    edge_count = len(ring) - 1
    for i in range(edge_count):
        a1, a2 = ring[i], ring[i + 1]
        for j in range(i + 2, edge_count):
            # First and last edges share the ring's start/end vertex
            if i == 0 and j == edge_count - 1:
                continue
            b1, b2 = ring[j], ring[j + 1]
            if segments_intersect(a1, a2, b1, b2):
                return True
    return False


def bounding_box(ring: Ring) -> tuple[float, float, float, float]:
    """Return (min_lon, min_lat, max_lon, max_lat) for fast spatial pre-filtering."""
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def bboxes_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def point_in_ring(point: Point2D, ring: Ring) -> bool:
    """Ray-casting point-in-polygon test (inclusive of boundary)."""
    px, py = point
    inside = False
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        if _orientation((x1, y1), point, (x2, y2)) == 0 and _on_segment((x1, y1), point, (x2, y2)):
            return True
        intersects = ((y1 > py) != (y2 > py)) and (
            px < (x2 - x1) * (py - y1) / ((y2 - y1) if (y2 - y1) != 0 else 1e-18) + x1
        )
        if intersects:
            inside = not inside
    return inside


def rings_overlap(ring_a: Ring, ring_b: Ring) -> bool:
    """Return True if two exterior polygon rings intersect or one contains the other."""
    if len(ring_a) < 4 or len(ring_b) < 4:
        return False
    if not bboxes_overlap(bounding_box(ring_a), bounding_box(ring_b)):
        return False

    # Check if any vertex of A lies strictly inside B (or vice versa)
    for pt in ring_a[:-1]:
        if point_in_ring(pt, ring_b):
            return True
    for pt in ring_b[:-1]:
        if point_in_ring(pt, ring_a):
            return True

    # Check if any edge of A crosses any edge of B
    for i in range(len(ring_a) - 1):
        for j in range(len(ring_b) - 1):
            if segments_intersect(ring_a[i], ring_a[i + 1], ring_b[j], ring_b[j + 1]):
                return True
    return False
