"""Coordinates helpers: the catalog carries GCJ-02 (Amap) points while Trip.com
returns WGS-84, so distances are computed after converting the catalog point."""
from __future__ import annotations

import math

X_PI = math.pi * 3000.0 / 180.0
A = 6378245.0
EE = 0.00669342162296594323


def _tlat(x: float, y: float) -> float:
    r = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    r += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    r += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    r += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return r


def _tlon(x: float, y: float) -> float:
    r = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    r += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    r += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    r += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return r


def wgs2gcj(lat: float, lon: float) -> tuple[float, float]:
    dlat = _tlat(lon - 105.0, lat - 35.0)
    dlon = _tlon(lon - 105.0, lat - 35.0)
    rlat = lat / 180.0 * math.pi
    m = 1 - EE * math.sin(rlat) ** 2
    sm = math.sqrt(m)
    dlat = (dlat * 180.0) / ((A * (1 - EE)) / (m * sm) * math.pi)
    dlon = (dlon * 180.0) / (A / sm * math.cos(rlat) * math.pi)
    return lat + dlat, lon + dlon


def gcj2wgs(lat: float, lon: float) -> tuple[float, float]:
    gl, gn = wgs2gcj(lat, lon)
    return lat * 2 - gl, lon * 2 - gn


def haversine(p: tuple[float, float], q: tuple[float, float]) -> float:
    r = 6371000.0
    p1, p2 = math.radians(p[0]), math.radians(q[0])
    dl = math.radians(q[1] - p[1])
    dp = p2 - p1
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def catalog_to_wgs(lat: float, lon: float) -> tuple[float, float]:
    """Shift a catalog point onto Trip.com's datum.

    The catalog points and Trip.com differ by a near-constant datum offset in Xi'an:
    trip_lat = catalog_lat - 0.001553, trip_lon = catalog_lon + 0.004676 (median of 33
    same-name anchor pairs, i.e. ~172 m south and ~430 m east). After the shift the
    anchor residuals have a median of ~10 m, so a 200 m gate stays meaningful.
    """
    return lat - 0.001553, lon + 0.004676
