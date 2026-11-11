"""Bounded requirement repair: the ShortTrip "check-feedback revision" stage.

Given a commonsense-valid seed plan and the query's DSL constraints, the engine
extracts requirement *hints* from the constraint text, edits the plan content
(which POI on which day, which intercity mode, which numeric fields), and
re-schedules + re-checks. Every candidate is scored with the official checker,
which is what makes the loop self-verifying.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .checker import CheckReport, check_plan, hard_vector
from .env import SandboxEnv, minutes
from .scheduler import extract_content, find_record, lookup_row, schedule

NAME_RE = re.compile(r'activity_position\(activity\)\s*==\s*"([^"]+)"')
SET_RE = re.compile(r'\{([^{}]*)\}\s*<=\s*(\w+)')
QUOTED_RE = re.compile(r'"([^"]+)"')
TYPE_RE = re.compile(r"(attraction|restaurant|accommodation)_type\(activity,\s*target_city\(plan\)\)")
COUNT_RE = re.compile(r"(attraction|day)_count\s*==\s*(\d+)")
TICKETS_RE = re.compile(r"activity_tickets\(activity\)\s*!=\s*(\d+)")
ROOMS_RE = re.compile(r"room_count\(activity\)\s*!=\s*(\d+)")
ROOMTYPE_RE = re.compile(r"room_type\(activity\)\s*!=\s*(\d+)")
CARS_RE = re.compile(r"taxi_cars\(activity_transports\(activity\)\)\s*!=\s*(\d+)")
MEALDAY_RE = re.compile(r'dayactivities\(plan,\s*(\d+)\)')
BUDGET_RE = re.compile(
    r"(total_cost|attraction_cost|accommodation_cost|restaurant_cost|inner_city_transportation_cost)\s*<=\s*([0-9.]+)"
)
RETURN_WINDOW_RE = re.compile(r"return_start_time\s*(>=|<=)\s*'([0-9:]+)'")
GO_WINDOW_RE = re.compile(r"go_start_time\s*(>=|<=)\s*'([0-9:]+)'")
FORBIDDEN_RE = re.compile(r"not\(\{([^{}]*)\}&(\w+)\)")


@dataclass
class Requirements:
    names: dict[str, set[str]] = field(default_factory=lambda: {"attraction": set(), "restaurant": set(), "accommodation": set()})
    types: dict[str, set[str]] = field(default_factory=lambda: {"attraction": set(), "restaurant": set(), "accommodation": set()})
    tickets: int | None = None
    rooms: int | None = None
    room_type: int | None = None
    cars: int | None = None
    intercity: set[str] = field(default_factory=set)
    budgets: dict[str, float] = field(default_factory=dict)
    attraction_count: int | None = None
    day_attraction_counts: dict[int, int] = field(default_factory=dict)
    forbidden: dict[str, set[str]] = field(default_factory=lambda: {"attraction": set(), "restaurant": set(), "accommodation": set()})
    return_window: tuple[str, str] | None = None
    go_window: tuple[str, str] | None = None

    @property
    def empty(self) -> bool:
        return not any(
            [
                self.names["attraction"],
                self.names["restaurant"],
                self.names["accommodation"],
                self.types["attraction"],
                self.types["restaurant"],
                self.types["accommodation"],
                self.tickets,
                self.intercity,
                self.budgets,
                self.attraction_count,
                self.day_attraction_counts,
                self.forbidden["attraction"],
            ]
        )


def _kind_of(constraint: str) -> str | None:
    if "'attraction'" in constraint or '"attraction"' in constraint:
        return "attraction"
    if "['breakfast', 'lunch', 'dinner']" in constraint:
        return "restaurant"
    if "'accommodation'" in constraint or '"accommodation"' in constraint:
        return "accommodation"
    return None


def parse_requirements(query: dict) -> Requirements:
    req = Requirements()
    for constraint in query.get("hard_logic_py") or []:
        forbidden = FORBIDDEN_RE.search(constraint)
        if forbidden:
            variable = forbidden.group(2)
            kind = (
                "attraction"
                if variable.startswith("attraction")
                else "restaurant"
                if variable.startswith("restaurant")
                else "accommodation"
            )
            req.forbidden[kind] |= set(QUOTED_RE.findall(forbidden.group(1)))
        window = RETURN_WINDOW_RE.search(constraint)
        if window:
            req.return_window = (window.group(1), window.group(2))
        window = GO_WINDOW_RE.search(constraint)
        if window:
            req.go_window = (window.group(1), window.group(2))
        for name in NAME_RE.findall(constraint):
            kind = _kind_of(constraint)
            if kind:
                req.names[kind].add(name)
        for body, target in SET_RE.findall(constraint):
            values = set(QUOTED_RE.findall(body))
            if not values:
                continue
            if target.startswith("attraction"):
                req.names["attraction"] |= values if "name_set" in target else set()
                req.types["attraction"] |= values if "type_set" in target else set()
            elif target.startswith("restaurant"):
                req.names["restaurant"] |= values if "name_set" in target else set()
                req.types["restaurant"] |= values if "type_set" in target else set()
            elif target.startswith("accommodation"):
                req.names["accommodation"] |= values if "name_set" in target else set()
                req.types["accommodation"] |= values if "type_set" in target else set()
        match = TICKETS_RE.search(constraint)
        if match:
            req.tickets = int(match.group(1))
        match = ROOMTYPE_RE.search(constraint)
        if match:
            req.room_type = int(match.group(1))
        match = ROOMS_RE.search(constraint)
        if match:
            req.rooms = int(match.group(1))
        match = CARS_RE.search(constraint)
        if match:
            req.cars = int(match.group(1))
        if "intercity_transport_set" in constraint:
            types = set(re.findall(r'"(train|airplane)"', constraint)) | set(re.findall(r"'(train|airplane)'", constraint))
            if types and "airplane" not in types:
                req.intercity = {"train"}
            elif types and "train" not in types:
                req.intercity = {"airplane"}
        for key, limit in BUDGET_RE.findall(constraint):
            req.budgets[key] = min(req.budgets.get(key, float("inf")), float(limit))
        if "attraction_count==0" in constraint or "attraction_count == 0" in constraint:
            req.attraction_count = 0
        match = re.search(r"attraction_count\s*==\s*(\d+)", constraint)
        if match and "day_attraction_count" not in constraint:
            req.attraction_count = int(match.group(1))
        if "day_attraction_count" in constraint:
            days = [int(x) for x in MEALDAY_RE.findall(constraint)] or [1]
            match = re.search(r"day_attraction_count\s*==\s*(\d+)", constraint)
            if match:
                for day in days:
                    req.day_attraction_counts[day] = int(match.group(1))
    return req


@dataclass
class RepairResult:
    plan: dict
    report: CheckReport
    edits: list[str] = field(default_factory=list)
    evaluations: int = 0
    improved: bool = False


class RepairEngine:
    def __init__(self, env: SandboxEnv, *, max_evaluations: int = 40,
                 room_type_fix: bool = False):
        self.env = env
        self.max_evaluations = max_evaluations
        # Opt-in: the legacy planner relabelled `room_type` without swapping the
        # hotel, which fails the official hotel check.  The flag keeps the old
        # behaviour reproducible while allowing the fixed run.
        self.room_type_fix = room_type_fix

    # ---------------------------------------------------------------- helpers
    def _tables(self, city: str):
        return (
            self.env.attraction_table(city),
            self.env.restaurant_table(city),
            self.env.accommodation_table(city),
        )

    def _best_candidate(self, kind: str, city: str, *, type_value: str | None, exclude: set[str], cheapest: bool = True) -> str | None:
        attractions, restaurants, accommodations = self._tables(city)
        if kind == "attraction":
            table, column = attractions, "type"
        elif kind == "restaurant":
            table, column = restaurants, "cuisine"
        else:
            table, column = accommodations, "featurehoteltype"
        frame = table.copy()
        if type_value:
            frame = frame[frame[column].astype(str) == str(type_value)]
        frame = frame[~frame["name"].astype(str).isin(exclude)]
        if frame.empty:
            return None
        frame["price"] = frame["price"].astype(float)
        frame = frame.sort_values("price") if cheapest else frame.sort_values("price", ascending=False)
        return str(frame.iloc[0]["name"])

    def _cheapest_of_kind(self, kind: str, city: str, exclude: set[str], lo: float, hi: float) -> str | None:
        """Cheapest item of `kind` whose price lies inside [lo, hi]."""
        attractions, restaurants, accommodations = self._tables(city)
        table = {"attraction": attractions, "restaurant": restaurants, "accommodation": accommodations}[kind]
        frame = table.copy()
        frame["price"] = frame["price"].astype(float)
        frame = frame[(frame["price"] >= lo) & (frame["price"] <= hi)]
        frame = frame[~frame["name"].astype(str).isin(exclude)]
        if frame.empty:
            return None
        return str(frame.sort_values("price").iloc[0]["name"])

    # ------------------------------------------------------------------ repair
    def repair(self, query: dict, plan: dict, report: CheckReport | None = None) -> RepairResult:
        if report is None:
            report = check_plan(query, plan)
        edits: list[str] = []
        evaluations = 1
        if report.hard_ok:
            return RepairResult(plan, report, edits, evaluations, False)

        requirements = parse_requirements(query)
        best_plan, best_report = plan, report

        def score(rep: CheckReport) -> tuple:
            return (rep.hard_pass_count, rep.commonsense_ok, rep.schema_ok)

        current = plan
        for stage in (
            "names",
            "types",
            "forbidden",
            "intercity",
            "go_time",
            "return_time",
            "counts",
            "room_type",
            "budget",
        ):
            if stage == "room_type" and not self.room_type_fix:
                continue
            if evaluations >= self.max_evaluations:
                break
            candidate = self._apply_stage(current, query, requirements, stage, edits)
            if candidate is None:
                continue
            self._fix_numeric(candidate, query, requirements)
            rep = check_plan(query, candidate)
            evaluations += 1
            if score(rep) > score(best_report):
                best_plan, best_report = candidate, rep
            current = candidate
            if rep.hard_ok and rep.commonsense_ok:
                return RepairResult(best_plan, best_report, edits, evaluations, True)

        self._fix_numeric(best_plan, query, requirements)
        best_report = check_plan(query, best_plan)
        evaluations += 1
        return RepairResult(best_plan, best_report, edits, evaluations, best_report.hard_pass_count > report.hard_pass_count)

    # ----------------------------------------------------------------- staging
    def _apply_stage(
        self, plan: dict, query: dict, requirements: Requirements, stage: str, edits: list[str]
    ) -> dict | None:
        city = query["target_city"]
        extracted = extract_content(self.env, plan)
        content = {day: list(items) for day, items in extracted["content"].items()}
        go, back, hotel = extracted["go"], extracted["back"], extracted["hotel"]
        days = int(query["days"])
        changed = False

        present_attractions = {name for items in content.values() for kind, name in items if kind == "attraction"}
        present_restaurants = {name for items in content.values() for kind, name in items if kind in ("lunch", "dinner", "breakfast")}

        if stage == "names":
            for name in sorted(requirements.names["attraction"]):
                if name in present_attractions:
                    continue
                if lookup_row(self.env.attraction_table(city), name) is None:
                    continue
                placed = self._best_placement(
                    query, go, back, hotel, content, "attraction", name, days
                )
                if placed is not None:
                    return placed
                present_attractions.add(name)
                edits.append(f"insert attraction {name} (no viable slot)")
                changed = True
            for name in sorted(requirements.names["restaurant"]):
                if name in present_restaurants:
                    continue
                if lookup_row(self.env.restaurant_table(city), name) is None:
                    continue
                slots = [day for day in range(days) if not any(k in ("lunch", "dinner") and n == name for k, n in content.get(day, []))]
                target = slots[0] if slots else 0
                content.setdefault(target, []).append(("lunch", name))
                present_restaurants.add(name)
                edits.append(f"insert restaurant {name} on day {target + 1}")
                changed = True
            if requirements.names["accommodation"]:
                wanted = sorted(requirements.names["accommodation"])[0]
                if hotel != wanted and lookup_row(self.env.accommodation_table(city), wanted) is not None:
                    hotel = wanted
                    edits.append(f"hotel -> {wanted}")
                    changed = True

        elif stage == "types":
            for kind, values in requirements.types.items():
                present = self._present_types(city, content, kind)
                for value in sorted(values - present):
                    name = self._best_candidate(kind, city, type_value=value, exclude=present_attractions | present_restaurants)
                    if name is None:
                        continue
                    if kind == "accommodation":
                        hotel = name
                    elif kind == "attraction":
                        content.setdefault(0, []).append(("attraction", name))
                        present_attractions.add(name)
                    else:
                        content.setdefault(0, []).append(("dinner", name))
                        present_restaurants.add(name)
                    edits.append(f"insert {kind} type {value}: {name}")
                    changed = True

        elif stage == "counts":
            total = sum(1 for items in content.values() for kind, _ in items if kind == "attraction")
            if requirements.attraction_count is not None and total > requirements.attraction_count:
                surplus = total - requirements.attraction_count
                for day in sorted(content, reverse=True):
                    keep = []
                    for item in content[day]:
                        if surplus > 0 and item[0] == "attraction" and item[1] not in requirements.names["attraction"]:
                            surplus -= 1
                            edits.append(f"drop attraction {item[1]}")
                            continue
                        keep.append(item)
                    content[day] = keep
                changed = True
            elif requirements.attraction_count is not None and total < requirements.attraction_count:
                missing = requirements.attraction_count - total
                for _ in range(missing):
                    name = self._best_candidate("attraction", city, type_value=None, exclude=present_attractions)
                    if name is None:
                        break
                    content.setdefault(0, []).append(("attraction", name))
                    present_attractions.add(name)
                    edits.append(f"add attraction {name}")
                    changed = True
            for day, wanted in requirements.day_attraction_counts.items():
                key = day - 1
                items = content.get(key, [])
                have = sum(1 for kind, _ in items if kind == "attraction")
                if have > wanted:
                    kept = []
                    dropped = 0
                    for item in items:
                        if item[0] == "attraction" and dropped < have - wanted and item[1] not in requirements.names["attraction"]:
                            dropped += 1
                            continue
                        kept.append(item)
                    content[key] = kept
                    changed = True
                elif have < wanted:
                    for _ in range(wanted - have):
                        name = self._best_candidate("attraction", city, type_value=None, exclude=present_attractions)
                        if name is None:
                            break
                        content.setdefault(key, []).append(("attraction", name))
                        present_attractions.add(name)
                        edits.append(f"day {day} add attraction {name}")
                        changed = True

        elif stage == "intercity":
            if requirements.intercity == {"airplane"}:
                flights_go = self.env.flights(query["start_city"], city)
                flights_back = self.env.flights(city, query["start_city"])
                if flights_go and flights_back:
                    go_rec = dict(flights_go[0])
                    back_rec = dict(flights_back[-1])
                    go, back = go_rec, back_rec
                    updates = {"type": "airplane"}
                    go.update(updates)
                    back.update(updates)
                    edits.append("intercity -> airplane")
                    changed = True
            elif requirements.intercity == {"train"}:
                trains_go = self.env.trains(query["start_city"], city)
                trains_back = self.env.trains(city, query["start_city"])
                if trains_go and trains_back:
                    go_rec = trains_go[0]
                    back_rec = trains_back[-1]
                    if go.get("type") != "train" or back.get("type") != "train":
                        go = dict(go_rec)
                        back = dict(back_rec)
                        edits.append("intercity -> train")
                        changed = True

        elif stage == "forbidden":
            unavailable = requirements.forbidden
            for day in sorted(content):
                kept = []
                for kind, name in content[day]:
                    if name in unavailable.get("attraction", set()) | unavailable.get("restaurant", set()):
                        edits.append(f"drop unavailable {name}")
                        changed = True
                        continue
                    kept.append((kind, name))
                content[day] = kept
            if hotel and hotel in unavailable.get("accommodation", set()):
                replacement = self._cheapest_of_kind("accommodation", city, {hotel}, 0, 1e9)
                if replacement:
                    hotel = replacement
                    edits.append(f"hotel -> {replacement} (closed)")
                    changed = True

        elif stage == "go_time":
            if not requirements.go_window:
                return None
            op, clock = requirements.go_window
            pool = self.env.trains(query["start_city"], city)
            if not pool:
                return None
            if op == ">=":
                candidates = [t for t in pool if minutes(t["BeginTime"]) >= minutes(clock)]
                candidates.sort(key=lambda t: minutes(t["BeginTime"]))
            else:
                candidates = [t for t in pool if minutes(t["BeginTime"]) <= minutes(clock)]
                candidates.sort(key=lambda t: -minutes(t["BeginTime"]))
            trimmed = {day: list(items) for day, items in content.items()}
            variants = [content]
            if days > 1 and trimmed.get(0):
                shortened = {day: list(items) for day, items in trimmed.items()}
                shortened[0] = shortened[0][:1]
                variants.append(shortened)
                variants.append({**shortened, 0: []})
            for candidate in candidates[:6]:
                for variant in variants:
                    trial = schedule(self.env, query, candidate, back, hotel, variant)
                    if trial is not None:
                        edits.append(
                            f"outbound train -> {candidate.get('TrainID')} {candidate['BeginTime']}"
                        )
                        return trial
            return None

        elif stage == "return_time":
            if not requirements.return_window:
                return None
            op, clock = requirements.return_window
            pool = self.env.trains(city, query["start_city"])
            if not pool:
                return None
            if op == ">=":
                candidates = [t for t in pool if minutes(t["BeginTime"]) >= minutes(clock)]
                candidates.sort(key=lambda t: minutes(t["BeginTime"]))
            else:
                candidates = [t for t in pool if minutes(t["BeginTime"]) <= minutes(clock)]
                candidates.sort(key=lambda t: -minutes(t["BeginTime"]))
            if not candidates:
                return None
            trimmed = {day: list(items) for day, items in content.items()}
            last_day = days - 1
            if op == "<=" and minutes(clock) < 16 * 60:
                items = trimmed.get(last_day, [])
                trimmed[last_day] = items[:1]
            for candidate in candidates[:3]:
                trial = schedule(self.env, query, go, candidate, hotel, trimmed)
                if trial is not None:
                    edits.append(f"return train -> {candidate.get('TrainID')} {candidate['BeginTime']}")
                    return trial
            return None

        elif stage == "room_type":
            # The official checker equates `room_type` with the hotel's `numbed`
            # column, so a query that asks for a given room type must be answered
            # with a hotel that actually has it.  Relabelling the field alone
            # passes the DSL but fails the commonsense hotel check.
            if requirements.room_type is None:
                return None
            table = self.env.accommodation_table(city)
            rows = table[table["numbed"].astype(int) == int(requirements.room_type)]
            if rows.empty:
                return None
            rows = rows.sort_values("price")
            current = lookup_row(table, hotel) if hotel else None
            if current is not None and int(current["numbed"]) == int(requirements.room_type):
                return None
            for _, row in rows.head(3).iterrows():
                name = str(row["name"])
                if name == hotel:
                    continue
                hotel = name
                edits.append(f"hotel -> {name} (room_type {requirements.room_type})")
                changed = True
                break

        elif stage == "budget":
            limits = requirements.budgets
            if not limits:
                return None
            for day in sorted(content):
                new_items = []
                for kind, name in content[day]:
                    if kind == "attraction":
                        limit = limits.get("attraction_cost")
                        if limit is not None:
                            row = lookup_row(self.env.attraction_table(city), name)
                            if row and float(row["price"]) * int(query["people_number"]) > limit / max(1, days):
                                cheap = self._cheapest_of_kind("attraction", city, present_attractions, 0, 1e9)
                                if cheap and cheap != name:
                                    new_items.append(("attraction", cheap))
                                    present_attractions.add(cheap)
                                    edits.append(f"cheapen attraction {name} -> {cheap}")
                                    changed = True
                                    continue
                    new_items.append((kind, name))
                content[day] = new_items
            if "accommodation_cost" in limits and hotel:
                row = lookup_row(self.env.accommodation_table(city), hotel)
                if row is not None and float(row["price"]) > limits["accommodation_cost"]:
                    cheap = self._cheapest_of_kind("accommodation", city, {hotel}, 0, limits["accommodation_cost"])
                    if cheap:
                        hotel = cheap
                        edits.append(f"cheapen hotel -> {cheap}")
                        changed = True

        if not changed:
            return None
        return schedule(self.env, query, go, back, hotel, content)

    def _best_placement(
        self,
        query: dict,
        go: dict,
        back: dict,
        hotel: str | None,
        content: dict,
        kind: str,
        name: str,
        days: int,
    ) -> dict | None:
        """Try inserting an item at several slots/days and keep the best-scoring plan.

        Appending to the end of a day usually fails because the day is already full;
        the item has to be placed right after arrival (or before the return leg).
        """
        candidates: list[dict] = []
        for day in range(days):
            for position in (0, 1):
                trial = {key: list(value) for key, value in content.items()}
                items = trial.setdefault(day, [])
                items.insert(min(position, len(items)), (kind, name))
                candidates.append(trial)
            trial = {key: list(value) for key, value in content.items()}
            trial.setdefault(day, []).append((kind, name))
            candidates.append(trial)

        best_plan: dict | None = None
        best_score = -1
        for trial in candidates:
            plan = schedule(self.env, query, go, back, hotel, trial)
            if plan is None:
                continue
            score = sum(1 for flag in hard_vector(query, plan) if flag)
            if score > best_score:
                best_plan, best_score = plan, score
        return best_plan

    def _present_types(self, city: str, content: dict, kind: str) -> set[str]:
        values: set[str] = set()
        for items in content.values():
            for item_kind, name in items:
                if item_kind not in ("attraction", "lunch", "dinner", "breakfast", "accommodation"):
                    continue
                if kind == "attraction" and item_kind != "attraction":
                    continue
                if kind == "restaurant" and item_kind == "attraction":
                    continue
                if kind == "accommodation":
                    continue
                row = lookup_row(self.env.attraction_table(city), name) if item_kind == "attraction" else lookup_row(self.env.restaurant_table(city), name)
                if row is None:
                    continue
                values.add(str(row.get("type") if kind == "attraction" else row.get("cuisine")))
        return values

    # ---------------------------------------------------------------- numeric
    def _fix_numeric(self, plan: dict, query: dict, requirements: Requirements) -> None:
        people = int(query["people_number"])
        for day in plan.get("itinerary", []):
            for activity in day["activities"]:
                kind = activity.get("type")
                if requirements.tickets is not None and kind in ("attraction", "train", "airplane"):
                    activity["tickets"] = requirements.tickets
                if requirements.rooms is not None and kind == "accommodation":
                    activity["rooms"] = requirements.rooms
                if requirements.room_type is not None and kind == "accommodation":
                    activity["room_type"] = requirements.room_type
                if kind == "accommodation":
                    activity["cost"] = float(activity.get("price", 0)) * float(activity.get("rooms", 1))
                if kind in ("attraction", "train", "airplane"):
                    activity["cost"] = float(activity.get("price", 0)) * float(activity.get("tickets", 1))
                if kind in ("lunch", "dinner", "breakfast"):
                    activity["cost"] = float(activity.get("price", 0)) * people
                for transport in activity.get("transports", []):
                    if transport.get("mode") == "metro":
                        if requirements.tickets is not None:
                            transport["tickets"] = requirements.tickets
                        transport["cost"] = float(transport.get("price", 0)) * float(transport.get("tickets", 1))
                    elif transport.get("mode") == "taxi":
                        if requirements.cars is not None:
                            transport["cars"] = requirements.cars
                        transport["cost"] = float(transport.get("price", 0)) * float(transport.get("cars", 1))
