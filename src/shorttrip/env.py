"""Sandbox access layer for the ShortTrip experiments.

Wraps the official ChinaTravel sandbox tables and reproduces the exact arithmetic
of `Transportation.goto` (distance/cost/station lookup are start-time independent,
so each leg pair is fetched once and re-timed locally with the official
`add_time` helper). This keeps planning fast while remaining bit-identical to
what the ChinaTravel checker recomputes.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass

import pandas as pd

from chinatravel.environment.tools.accommodations.apis import Accommodations
from chinatravel.environment.tools.attractions.apis import Attractions
from chinatravel.environment.tools.intercity_transport.apis import IntercityTransport
from chinatravel.environment.tools.restaurants.apis import Restaurants
from chinatravel.environment.tools.transportation.apis import Transportation, add_time


def minutes(hhmm: str) -> int:
    text = str(hhmm)
    if text.startswith("次日"):
        text = text[2:]
    hour, minute = text.split(":")[:2]
    return int(hour) * 60 + int(minute)


def hhmm(total_minutes: int) -> str:
    total_minutes = max(0, min(int(total_minutes), 24 * 60 + 59))
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


@dataclass(frozen=True)
class LegTemplate:
    start: str
    end: str
    mode: str
    seconds: float  # travel hours, kept exact so add_time truncation matches
    cost: float
    distance: float


class SandboxEnv:
    """Cached, language-fixed view of the ChinaTravel sandbox."""

    def __init__(self, lang: str = "zh"):
        self.lang = lang
        self.attractions = Attractions(lang=lang)
        self.restaurants = Restaurants(lang=lang)
        self.accommodations = Accommodations(lang=lang)
        self.intercity = IntercityTransport(lang=lang)
        self.transport = Transportation(lang=lang)
        self._leg_cache: dict[tuple[str, str, str, str], object] = {}
        self._place_cache: dict[str, set[str]] = {}

    # ---------------------------------------------------------------- tables
    def attraction_table(self, city: str) -> pd.DataFrame:
        return self.attractions.data[city]

    def restaurant_table(self, city: str) -> pd.DataFrame:
        return self.restaurants.data[city]

    def accommodation_table(self, city: str) -> pd.DataFrame:
        return self.accommodations.data[city]

    def places(self, city: str) -> set[str]:
        """All names that the `goto` tool can resolve in this city."""
        if city not in self._place_cache:
            names: set[str] = set()
            for table in (
                self.attraction_table(city),
                self.restaurant_table(city),
                self.accommodation_table(city),
            ):
                names |= set(table["name"].astype(str))
            names |= set(self.transport.poi_search.data[city]["name"].astype(str))
            self._place_cache[city] = names
        return self._place_cache[city]

    def invalidate(self) -> None:
        """Drop derived caches after the sandbox has been updated in place.

        Without this, a leg lookup that failed *before* the update stays cached as
        `None`, and neither the planner nor the checker will ever see the new POI.
        """
        self._leg_cache.clear()
        self._place_cache.clear()

    def trains(self, start_city: str, end_city: str) -> list[dict]:
        try:
            table = self.intercity.select(start_city, end_city, "train")
        except Exception:
            return []
        if not isinstance(table, pd.DataFrame) or table.empty:
            return []
        return table.to_dict("records")

    def flights(self, start_city: str, end_city: str) -> list[dict]:
        try:
            table = self.intercity.select(start_city, end_city, "airplane")
        except Exception:
            return []
        if not isinstance(table, pd.DataFrame) or table.empty:
            return []
        return table.to_dict("records")

    # ------------------------------------------------------------- inner city
    def legs(self, city: str, src: str, dst: str, mode: str) -> list[LegTemplate] | None:
        """Leg templates for one inner-city trip; None when unusable."""
        key = (city, src, dst, mode)
        if key in self._leg_cache:
            return self._leg_cache[key]
        raw = self.transport.goto(city, src, dst, "00:00", mode)
        if not isinstance(raw, list) or not raw:
            self._leg_cache[key] = None
            return None
        templates: list[LegTemplate] = []
        for leg in raw:
            seconds = (minutes(leg["end_time"]) - minutes(leg["start_time"])) / 60.0
            templates.append(
                LegTemplate(
                    start=leg["start"],
                    end=leg["end"],
                    mode=leg["mode"],
                    seconds=seconds,
                    cost=float(leg["cost"]),
                    distance=float(leg["distance"]),
                )
            )
        self._leg_cache[key] = templates
        return templates

    def leg_templates(self, city: str, src: str, dst: str, mode: str) -> list[LegTemplate] | None:
        """Leg templates with *exact* fractional durations.

        `goto` truncates to whole minutes at every hop, so we re-derive the raw
        durations by asking the tool for the untruncated numbers instead of
        differencing the returned clock times.
        """
        key = (city, src, dst, mode, "raw")
        if key in self._leg_cache:
            return self._leg_cache[key]  # type: ignore[return-value]
        templates = self._raw_legs(city, src, dst, mode)
        self._leg_cache[key] = templates
        return templates

    def _raw_legs(self, city: str, src: str, dst: str, mode: str) -> list[LegTemplate] | None:
        transport = self.transport
        coord_a = transport.poi_search.search(city, src)
        coord_b = transport.poi_search.search(city, dst)
        if isinstance(coord_a, str) or isinstance(coord_b, str):
            return None
        from geopy.distance import geodesic

        if mode == "walk":
            distance = geodesic(coord_a, coord_b).kilometers
            return [
                LegTemplate(src, dst, "walk", distance / 5.0, 0.0, distance)
            ]
        if mode == "taxi":
            distance = geodesic(coord_a, coord_b).kilometers
            cost = 11.0 if distance <= 1.8 else (
                11.0 + (distance - 1.8) * 3.5 if distance <= 10
                else 11.0 + (10 - 1.8) * 3.5 + (distance - 10) * 4.5
            )
            return [
                LegTemplate(src, dst, "taxi", distance / 40.0, round(cost, 2), round(distance, 2))
            ]
        if mode != "metro":
            return None
        slug = (
            transport.city_list[transport.city_list_chinese.index(city)]
            if city in transport.city_list_chinese
            else str(city).lower()
        )
        station_a, dist_a = transport._find_nearest_station(slug, src, coord_a)
        station_b, dist_b = transport._find_nearest_station(slug, dst, coord_b)
        if station_a == station_b:
            return None
        between = geodesic(station_a["position"], station_b["position"]).kilometers
        suffix = transport._metro_station_suffix()
        if between <= 4:
            fare = 2
        elif between <= 9:
            fare = 3
        elif between <= 14:
            fare = 4
        elif between <= 21:
            fare = 5
        elif between <= 28:
            fare = 6
        elif between <= 37:
            fare = 7
        elif between <= 48:
            fare = 8
        elif between <= 61:
            fare = 9
        else:
            fare = 9 + int((between - 61 + 14) // 15)
        return [
            LegTemplate(src, station_a["name"] + suffix, "walk", dist_a / 5.0, 0.0, round(dist_a, 2)),
            LegTemplate(
                station_a["name"] + suffix,
                station_b["name"] + suffix,
                "metro",
                between / 30.0,
                float(fare),
                round(between, 2),
            ),
            LegTemplate(station_b["name"] + suffix, dst, "walk", dist_b / 5.0, 0.0, round(dist_b, 2)),
        ]

    def leg_plan(self, city: str, src: str, dst: str, mode: str, depart: str) -> list[dict] | None:
        """Plan-ready transport legs, timed exactly like the official tool."""
        templates = self.leg_templates(city, src, dst, mode)
        if not templates:
            return None
        legs: list[dict] = []
        clock = depart
        for template in templates:
            arrive = add_time(clock, template.seconds)
            legs.append(
                {
                    "start": template.start,
                    "end": template.end,
                    "mode": template.mode,
                    "start_time": clock,
                    "end_time": arrive,
                    "cost": template.cost,
                    "distance": template.distance,
                }
            )
            clock = arrive
        return legs

    def trip_seconds(self, city: str, src: str, dst: str, mode: str) -> float | None:
        templates = self.leg_templates(city, src, dst, mode)
        if not templates:
            return None
        return sum(t.seconds for t in templates)

    def best_mode(self, city: str, src: str, dst: str, prefer: str = "metro") -> str | None:
        """Cheapest sensible mode that the tool can actually resolve."""
        for mode in (prefer, "metro", "walk", "taxi"):
            if self.leg_templates(city, src, dst, mode):
                return mode
        return None


@functools.lru_cache(maxsize=4)
def get_env(lang: str = "zh") -> SandboxEnv:
    return SandboxEnv(lang=lang)
