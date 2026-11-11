"""Deterministic, LLM-free itinerary constructor (the ShortTrip "planner" stage).

The constructor is deliberately *skeleton-first*: it builds a ChinaTravel
commonsense-valid itinerary from the sandbox without looking at the DSL
constraints, and leaves requirement satisfaction to the bounded repair loop in
`repair.py`. Candidate selection is geography-aware (a candidate is only
considered if `goto` from the current position is short enough) because the
sandbox cities are large and the cheapest POI is frequently two hours away.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .checker import CheckReport, check_plan
from .env import SandboxEnv, hhmm, minutes
from .plan import DayBuilder, ceil_div, itinerary


@dataclass
class PlannerOptions:
    max_attractions_per_day: int = 3
    max_combos: int = 6
    go_window: tuple[int, int] = (6 * 60, 13 * 60)
    meal_minutes: int = 60
    attraction_minutes: int = 90
    max_leg_seconds_attraction: int = 3600
    max_leg_seconds_meal: int = 2700
    day_cutoff_mid: int = 19 * 60 + 30
    day_cutoff_last: int = 21 * 60
    # Amap shows the sandbox `goto` is 1.3-1.7x optimistic, so reserve slack
    # on top of every leg when judging whether an activity still fits.
    route_slack_factor: float = 1.3
    # Candidate-pool generation for the human-preference benchmark (P3). These do not
    # change feasibility logic — every produced plan still goes through the official
    # checker — they only change *which* feasible plans get built, so the pool contains
    # genuinely different itineraries rather than one plan relabelled.
    order_by: str = "distance"          # distance | price | duration
    prefer_mode: str = "metro"          # metro | taxi | walk


@dataclass
class PlanResult:
    plan: dict | None
    report: CheckReport | None
    combos_tried: int = 0
    attempts: list[dict] = field(default_factory=list)
    matching_report: dict | None = None

    @property
    def ok(self) -> bool:
        return bool(self.report and self.report.all_ok and
                    (self.matching_report is None or self.matching_report['all_hard_satisfied']))


class SkeletonPlanner:
    def __init__(self, env: SandboxEnv, options: PlannerOptions | None = None, *, candidate_matcher=None):
        self.env = env
        self.options = options or PlannerOptions()
        self.last_reason: str | None = None
        # Explicit opt-in. The baseline and stored historical plans keep their
        # original behaviour; matching runs before each attraction insertion.
        self.candidate_matcher = candidate_matcher

    # ------------------------------------------------------------------ entry
    def build(self, query: dict, *, deep_check: bool = True) -> PlanResult:
        start_city = query["start_city"]
        target_city = query["target_city"]
        days = int(query["days"])

        gos = self._pick_intercity(start_city, target_city, window=self.options.go_window)
        backs = self._pick_intercity(target_city, start_city, window=None, reverse=True)
        if not gos or not backs:
            self.last_reason = "no intercity option"
            return PlanResult(None, None, 0)

        hotels = self._pick_hotels(target_city) if days > 1 else []

        attempts: list[dict] = []
        tried = 0
        best = PlanResult(None, None, 0)
        pairs = [(go, back) for go in gos for back in backs]
        if days == 1:
            viable = [
                pair
                for pair in pairs
                if minutes(pair[1]["BeginTime"]) - minutes(pair[0]["EndTime"]) >= 150
            ]
            if not viable and pairs:
                viable = [max(pairs, key=lambda p: minutes(p[1]["BeginTime"]) - minutes(p[0]["EndTime"]))]
            pairs = viable
        for go, back in pairs:
            if tried >= self.options.max_combos:
                break
            tried += 1
            self.last_reason = None
            plan = self._construct(query, go, back, hotels)
            if plan is None:
                attempts.append(
                    {"combo": tried, "reason": self.last_reason or "construction failed"}
                )
                continue
            report = check_plan(query, plan) if deep_check else None
            matching_report = self.candidate_matcher.audit_plan(query,plan) if self.candidate_matcher is not None else None
            attempts.append(
                {
                    "combo": tried,
                    "go": go.get("TrainID"),
                    "back": back.get("TrainID"),
                    "commonsense_ok": report.commonsense_ok if report else None,
                    "hard_pass": report.hard_pass_count if report else None,
                    "hard_total": len(report.hard_results) if report else None,
                    "violations": report.commonsense_violations if report else None,
                    "matching_report": matching_report,
                }
            )
            if best.plan is None:
                best = PlanResult(plan, report, tried, attempts, matching_report)
            if report and report.commonsense_ok and report.schema_ok and (matching_report is None or matching_report['all_hard_satisfied']):
                return PlanResult(plan, report, tried, attempts, matching_report)
        best.combos_tried = tried
        best.attempts = attempts
        return best

    # -------------------------------------------------------------- selection
    def _pick_intercity(
        self, frm: str, to: str, window: tuple[int, int] | None = None, reverse: bool = False
    ) -> list[dict]:
        trains = self.env.trains(frm, to)
        if not trains:
            return []
        pool = list(trains)
        if window is not None:
            low, high = window
            filtered = [t for t in pool if low <= minutes(t["BeginTime"]) <= high]
            if filtered:
                pool = filtered
        pool.sort(key=lambda t: (minutes(t["BeginTime"]), float(t["Cost"])))
        if reverse:
            pool = sorted(pool, key=lambda t: -minutes(t["BeginTime"]))
        return pool[:5]

    def _pick_hotels(self, city: str) -> list[dict]:
        table = self.env.accommodation_table(city)
        if table.empty:
            return []
        frame = table.copy()
        frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
        frame = frame.dropna(subset=["price"])
        frame = frame.sort_values("price")
        return frame.head(8).to_dict("records")

    # -------------------------------------------------------------- geography
    def _coords(self, city: str) -> dict[str, tuple[float, float]]:
        raw = self.env.transport.poi_search.data[city]
        points: dict[str, tuple[float, float]] = {}
        if isinstance(raw, dict):
            items = raw.items()
        else:
            items = ((str(row["name"]), row["position"]) for row in raw.to_dict("records"))
        for name, position in items:
            try:
                points[str(name)] = (float(position[0]), float(position[1]))
            except (TypeError, IndexError, ValueError):
                continue
        return points

    def _distance_km(self, city: str, anchor: str, names: list[str]) -> np.ndarray:
        points = self._coords(city)
        origin = points.get(anchor)
        out = np.full(len(names), np.inf)
        if origin is None:
            return out
        lat0, lon0 = origin
        for index, name in enumerate(names):
            target = points.get(name)
            if target is None:
                continue
            lat, lon = target
            dlat = np.radians(lat - lat0)
            dlon = np.radians(lon - lon0)
            a = np.sin(dlat / 2) ** 2 + np.cos(np.radians(lat0)) * np.cos(np.radians(lat)) * np.sin(dlon / 2) ** 2
            out[index] = 2 * 6371.0 * np.arcsin(np.sqrt(min(1.0, a)))
        return out

    def _ranked(self, frame: pd.DataFrame, city: str, anchor: str | None, radius_km: float) -> list[dict]:
        if frame.empty:
            return []
        work = frame.copy()
        work["price"] = pd.to_numeric(work["price"], errors="coerce").fillna(0)
        order_by = getattr(self.options, "order_by", "distance")
        if anchor:
            distances = self._distance_km(city, anchor, [str(x) for x in work["name"]])
            work["dist"] = distances
            nearby = work[work["dist"] <= radius_km]
            if len(nearby) >= 6:
                work = nearby
        # Candidate-pool diversity: the same feasible neighbourhood ordered by a
        # different criterion yields a different itinerary, which is what the pairwise
        # human evaluation needs.
        if order_by == "price":
            work = work.sort_values(["price", "name"])
        elif order_by == "duration":
            work = work.assign(_dur=pd.to_numeric(work.get("recommendmintime"), errors="coerce")) \
                       .sort_values(["_dur", "name"])
        elif anchor and "dist" in work:
            work = work.sort_values(["dist", "price"])
        else:
            work = work.sort_values("price")
        return work.to_dict("records")

    # ----------------------------------------------------------- construction
    def _construct(
        self, query: dict, go: dict, back: dict, hotels: list[dict]
    ) -> dict | None:
        city = query["target_city"]
        people = int(query["people_number"])
        days = int(query["days"])
        used_attractions: set[str] = set()
        used_restaurants: set[str] = set()
        day_plans: list[list[dict]] = []
        hotel: dict | None = None

        for day_index in range(days):
            is_first = day_index == 0
            is_last = day_index == days - 1
            builder = DayBuilder(self.env, city, people, day_index)
            builder.day_cutoff = self.options.day_cutoff_last if is_last else self.options.day_cutoff_mid

            if is_first:
                builder.activities.append(self._intercity_activity(go, "train", people, []))
                builder.time = go["EndTime"]
                builder.position = go["To"]
                anchor = go["To"]
            else:
                start_position = hotel["name"] if hotel is not None else go["To"]
                builder.set_start("08:30", start_position)
                anchor = start_position

            deadline = minutes(back["BeginTime"]) - 25 if is_last else None
            self._fill_day(
                builder,
                query,
                anchor=anchor,
                is_last=is_last,
                deadline=deadline,
                station=back["From"] if is_last else None,
                used_attractions=used_attractions,
                used_restaurants=used_restaurants,
            )

            if is_last:
                transports = builder.close_with_station(back["From"], back["BeginTime"])
                if transports is None:
                    self.last_reason = (
                        f"unreachable station {back['From']} before {back['BeginTime']} "
                        f"from {builder.position} at {builder.time}"
                    )
                    return None
                builder.activities.append(
                    self._intercity_activity(back, "train", people, transports)
                )
            elif hotels:
                if hotel is None:
                    hotel = self._first_reachable_hotel(builder, hotels, anchor)
                    if hotel is None:
                        self.last_reason = (
                            f"no reachable hotel on day {day_index} at {builder.time}"
                        )
                        return None
                rooms = max(1, ceil_div(people, max(1, int(hotel["numbed"]))))
                if not builder.add_hotel(hotel, rooms):
                    self.last_reason = f"add_hotel failed on day {day_index}"
                    return None
            day_plans.append(builder.activities)

        return {
            "people_number": people,
            "start_city": query["start_city"],
            "target_city": city,
            "itinerary": itinerary(day_plans),
        }

    def _first_reachable_hotel(
        self, builder: DayBuilder, hotels: list[dict], anchor: str
    ) -> dict | None:
        origin = builder.position or anchor
        names = [str(h["name"]) for h in hotels]
        distances = self._distance_km(builder.city, origin, names)
        order = np.argsort(distances)
        for index in order[: len(hotels)]:
            candidate = hotels[int(index)]
            name = str(candidate["name"])
            mode = self.env.best_mode(builder.city, origin, name)
            if mode is None:
                continue
            seconds = self.env.trip_seconds(builder.city, origin, name, mode)
            if seconds is None:
                continue
            if minutes(builder.time) + seconds * 60 < 22 * 60 + 40:
                return candidate
        return None

    def _intercity_activity(
        self, record: dict, kind: str, people: int, transports: list[dict]
    ) -> dict:
        price = float(record["Cost"])
        activity = {
            "start": record["From"],
            "end": record["To"],
            "start_time": record["BeginTime"],
            "end_time": record["EndTime"],
            "price": price,
            "cost": price * people,
            "tickets": people,
            "type": kind,
            "transports": transports,
        }
        if kind == "train":
            activity["TrainID"] = record["TrainID"]
        else:
            activity["FlightID"] = record["FlightID"]
        return activity

    # ------------------------------------------------------------------ filling
    def _fill_day(
        self,
        builder: DayBuilder,
        query: dict,
        *,
        anchor: str,
        is_last: bool,
        deadline: int | None,
        station: str | None,
        used_attractions: set[str],
        used_restaurants: set[str],
    ) -> None:
        city = query["target_city"]
        radius = float('inf') if self.candidate_matcher is not None else (12.0 if deadline is None else 9.0)
        attractions = self._ranked(self.env.attraction_table(city), city, anchor, radius)
        restaurants = self._ranked(self.env.restaurant_table(city), city, anchor, 8.0)
        lunch_done = dinner_done = False
        added = 0

        def affordable(duration: int) -> bool:
            if not is_last or deadline is None:
                return True
            mode = self.env.best_mode(city, builder.position, station)
            travel = self.env.trip_seconds(city, builder.position, station, mode) if mode else None
            if travel is None:
                return False
            travel = travel * self.options.route_slack_factor
            return minutes(builder.time) + travel * 60 + duration + 20 <= deadline

        for _ in range(8):
            clock = minutes(builder.time)
            if clock >= builder.day_cutoff:
                break
            if not lunch_done and 11 * 60 <= clock < 14 * 60:
                if self._try_meal(builder, restaurants, "lunch", used_restaurants, affordable):
                    lunch_done = True
                    continue
                lunch_done = True
                continue
            if not dinner_done and 17 * 60 <= clock < 20 * 60:
                if self._try_meal(builder, restaurants, "dinner", used_restaurants, affordable):
                    dinner_done = True
                    continue
                dinner_done = True
                continue
            if added < self.options.max_attractions_per_day and clock < builder.day_cutoff - 60:
                if self._try_attraction(builder, attractions, used_attractions, affordable, query=query):
                    added += 1
                    continue
                break
            break

    def _try_meal(self, builder, restaurants, kind, used, affordable) -> bool:
        for row in restaurants:
            name = str(row["name"])
            if name in used:
                continue
            if builder.position != name:
                seconds = self.env.trip_seconds(
                    builder.city, builder.position, name, builder.mode_preference
                ) or self.env.trip_seconds(builder.city, builder.position, name, "walk")
                if seconds is None or seconds * 60 > self.options.max_leg_seconds_meal:
                    continue
            if not _window_allows(row, minutes(builder.time), self.options.meal_minutes):
                continue
            if not affordable(self.options.meal_minutes):
                continue
            snapshot = (builder.time, builder.position, len(builder.activities))
            if builder.add_meal(kind, row, self.options.meal_minutes):
                if _meal_window_ok(kind, builder.activities[-1]):
                    used.add(name)
                    return True
                _rollback(builder, snapshot)
        return False

    def _try_attraction(self, builder, attractions, used, affordable, *, query=None) -> bool:
        if self.candidate_matcher is not None:
            remaining=[row for row in attractions if str(row['name']) not in used]
            attractions=self.candidate_matcher.rank_rows(remaining, city=builder.city,
                origin=builder.position, env=self.env, query=query or {})
        for row in attractions:
            name = str(row["name"])
            if name in used:
                continue
            old_mode = builder.mode_preference
            if '_tagmatch_mode' in row:
                builder.mode_preference = row['_tagmatch_mode']
            try:
                if self._try_attraction_row(builder,row,used,affordable):
                    return True
            finally:
                builder.mode_preference = old_mode
        return False

    def _try_attraction_row(self,builder,row,used,affordable):
        name = str(row['name'])
        if builder.position != name:
            seconds = self.env.trip_seconds(
                builder.city, builder.position, name, builder.mode_preference
            )
            if seconds is None:
                seconds = self.env.trip_seconds(builder.city, builder.position, name, "taxi")
            if seconds is None or seconds * 60 > self.options.max_leg_seconds_attraction:
                return False
        duration = max(45, int(round(float(row["recommendmintime"]) * 60)))
        if not _window_allows(row, minutes(builder.time), duration):
            return False
        if not affordable(duration):
            return False
        snapshot = (builder.time, builder.position, len(builder.activities))
        if builder.add_attraction(row, duration_min=duration):
            used.add(name)
            return True
        _rollback(builder, snapshot)
        return False


def _rollback(builder: DayBuilder, snapshot) -> None:
    clock, position, count = snapshot
    del builder.activities[count:]
    builder.time = clock
    builder.position = position


def _close_minutes(open_time: str, close_time: str) -> int:
    open_min = minutes(open_time)
    close_min = minutes(close_time)
    if close_min <= open_min:
        close_min += 24 * 60
    return close_min


def _window_allows(row, start_min: int, duration: int) -> bool:
    try:
        open_min = minutes(str(row["opentime"]))
        close_min = _close_minutes(str(row["opentime"]), str(row["endtime"]))
    except Exception:
        return True
    return start_min >= open_min and start_min + duration <= close_min


def _meal_window_ok(kind: str, activity: dict) -> bool:
    start = minutes(activity["start_time"])
    end = minutes(activity["end_time"])
    if kind == "lunch":
        return start < 14 * 60 and end > 11 * 60
    if kind == "dinner":
        return start < 20 * 60 and end > 17 * 60
    if kind == "breakfast":
        return start < 9 * 60 and end > 6 * 60
    return True
