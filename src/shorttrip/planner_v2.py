"""V2 rule planner: constraint-directed construction on top of the skeleton seed.

Motivation (P33 @ 报告/28): the skeleton seed plus the legacy staged repair left
200/300 easy queries failing exactly *one* constraint, and the failures clustered
by constraint family — i.e. the repairer lacked a capability, not luck.  P31's
independent rule planner showed the same lesson from the other side: a rule
planner is only as good as its move library.

V2 therefore keeps the deterministic seed and adds *constraint-directed* stages.
Every stage proposes content-level edits, the scheduler rebuilds the timeline,
and the official checker decides whether the edit helped.  No LLM, no randomness:
the same query always yields the same plan.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from .checker import check_plan
from .env import SandboxEnv, minutes
from .planner import PlannerOptions, SkeletonPlanner
from .repair import RepairEngine
from .scheduler import extract_content, lookup_row, schedule

MEAL_WINDOWS = {"breakfast": (7 * 60, 10 * 60), "lunch": (11 * 60, 14 * 60), "dinner": (17 * 60, 21 * 60)}

QUOTED = re.compile(r"'([^']+)'|\"([^\"]+)\"")


def _quoted(text: str) -> set[str]:
    return {a or b for a, b in QUOTED.findall(text) if (a or b)}


@dataclass
class Spec:
    """Requirements extracted from the executable DSL (result lines included)."""

    names: dict[str, set[str]] = field(
        default_factory=lambda: {"attraction": set(), "restaurant": set(), "accommodation": set()})
    types: dict[str, set[str]] = field(
        default_factory=lambda: {"attraction": set(), "restaurant": set(), "accommodation": set()})
    intercity: set[str] = field(default_factory=set)
    innercity: set[str] = field(default_factory=set)
    budgets: dict[str, float] = field(default_factory=dict)
    room_type: int | None = None
    tickets: int | None = None
    rooms: int | None = None
    cars: int | None = None
    go_window: tuple[str, str] | None = None
    return_window: tuple[str, str] | None = None
    forbidden: dict[str, set[str]] = field(
        default_factory=lambda: {"attraction": set(), "restaurant": set(), "accommodation": set()})

    @property
    def empty(self) -> bool:
        return not any([self.names["attraction"], self.names["restaurant"], self.names["accommodation"],
                        self.types["attraction"], self.types["restaurant"], self.types["accommodation"],
                        self.intercity, self.budgets])


def parse_spec(query: dict) -> Spec:
    """Read the DSL directly: type sets live in `result=(...)`, not in assignments."""
    spec = Spec()
    for constraint in query.get("hard_logic_py") or []:
        text = str(constraint)
        result = text.split("result=", 1)[-1]
        kinds = [
            ("accommodation", "accommodation_type_set"),
            ("attraction", "attraction_type_set"),
            ("restaurant", "restaurant_type_set"),
        ]
        for kind, marker in kinds:
            if marker in text:
                spec.types[kind] |= _quoted(result)
        for kind, marker in (("attraction", "attraction_name_set"), ("restaurant", "restaurant_name_set"),
                             ("accommodation", "accommodation_name_set")):
            for name in _quoted(result):
                if f"in {marker}" in result or f"in {marker} " in result:
                    spec.names[kind].add(name)
        if "intercity_transport_set" in text:
            spec.intercity |= _quoted(result)
        if "innercity_transport_set" in text:
            spec.innercity |= _quoted(result)
        if "forbidden" in text.lower():
            for kind in ("attraction", "restaurant", "accommodation"):
                marker = f"{kind}_name_set"
                if marker in text and "not in" in text:
                    spec.forbidden[kind] |= _quoted(result)
        for key, limit in re.findall(r"(total_cost|food_cost|hotel_cost|attraction_cost|"
                                     r"transportation_cost|food_cost/food_count/people_count)"
                                     r"\s*<=\s*(\d+(?:\.\d+)?)", text):
            spec.budgets[key] = min(spec.budgets.get(key, float("inf")), float(limit))
        match = re.search(r"room_type\s*==\s*(\d+)", text)
        if match:
            spec.room_type = int(match.group(1))
        match = re.search(r"tickets\s*==\s*(\d+)", text)
        if match:
            spec.tickets = int(match.group(1))
        match = re.search(r"room_count\s*==\s*(\d+)", text)
        if match:
            spec.rooms = int(match.group(1))
        match = re.search(r"(?:BeginTime|begin_time)[^\"]*\"(\d{2}:\d{2})\"[^\"]*\"(\d{2}:\d{2})\"", text)
        if match and spec.go_window is None and "intercity" in text:
            spec.go_window = (match.group(1), match.group(2))
    return spec


@dataclass
class V2Result:
    plan: dict | None
    report: object | None
    evaluations: int = 0
    moves: list[str] = field(default_factory=list)
    seed_all_ok: bool = False
    reason: str | None = None

    @property
    def improved(self) -> bool:
        return bool(self.report is not None and self.report.hard_pass_count > 0)


def _hhmm(text: str) -> int | None:
    try:
        hour, minute = str(text).split(":")[:2]
        return int(hour) * 60 + int(minute)
    except (ValueError, AttributeError):
        return None


def _price(row: dict | None) -> float:
    try:
        return float((row or {}).get("price", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


class ConstraintPlannerV2:
    def __init__(self, env: SandboxEnv, *, max_evaluations: int = 60,
                 slack: float = 1.3, verbose: bool = False):
        self.env = env
        self.max_evaluations = max_evaluations
        self.slack = slack
        self.verbose = verbose

    # ------------------------------------------------------------------ public
    def plan(self, query: dict) -> V2Result:
        seed = SkeletonPlanner(self.env, PlannerOptions()).build(query)
        if seed.plan is None:
            return V2Result(None, None, 0, [], False, getattr(seed, "last_reason", "no seed"))
        report = seed.report
        plan = seed.plan
        # The legacy staged repair is a strong baseline: keep its wins, then improve.
        legacy = RepairEngine(self.env, max_evaluations=25, room_type_fix=True).repair(query, plan, report)
        if legacy.report is not None and legacy.report.hard_pass_count >= (report.hard_pass_count if report else 0):
            plan, report = legacy.plan, legacy.report
        result = V2Result(plan, report, 0, [], bool(report and report.all_ok))
        if report is not None and report.all_ok:
            return result

        req = parse_spec(query)
        state = extract_content(self.env, plan)
        state = {"go": state["go"], "back": state["back"], "hotel": state["hotel"],
                 "content": {day: list(items) for day, items in state["content"].items()}}
        best_plan, best_report = plan, report
        evaluations = 0

        def score(rep) -> tuple:
            if rep is None:
                return (-1, 0, 0, 0.0)
            cost = -float(rep.total_cost) if getattr(rep, "total_cost", None) is not None else 0.0
            return (rep.hard_pass_count, int(bool(rep.commonsense_ok)), int(bool(rep.schema_ok)), cost)

        def try_state(candidate_state, label: str):
            """Rebuild + check one candidate; keep it if it scores better."""
            nonlocal best_plan, best_report, state, evaluations
            if evaluations >= self.max_evaluations:
                return False
            plan = schedule(self.env, query, candidate_state["go"], candidate_state["back"],
                            candidate_state["hotel"], candidate_state["content"],
                            route_slack_factor=self.slack)
            evaluations += 1
            if plan is None:
                return False
            rep = check_plan(query, plan)
            if score(rep) > score(best_report):
                best_plan, best_report, state = plan, rep, candidate_state
                result.moves.append(label)
                if self.verbose:
                    print(f"    + {label} -> hard {rep.hard_pass_count}")
                return True
            return False

        stages = (
            ("intercity", self._stage_intercity),
            ("hotel", self._stage_hotel),
            ("must_attraction", self._stage_must_attraction),
            ("must_restaurant", self._stage_must_restaurant),
            ("attraction_type", self._stage_attraction_type),
            ("restaurant_type", self._stage_restaurant_type),
            ("per_meal", self._stage_per_meal),
            ("budget", self._stage_budget),
        )
        for name, stage in stages:
            if evaluations >= self.max_evaluations:
                break
            for candidate_state, label in stage(query, req, state):
                if best_report is not None and best_report.all_ok:
                    break
                try_state(candidate_state, f"{name}:{label}")
            if best_report is not None and best_report.all_ok:
                break

        result.plan, result.report, result.evaluations = best_plan, best_report, evaluations
        return result

    # ------------------------------------------------------------------ helpers
    def _table(self, kind: str, city: str) -> pd.DataFrame:
        table = {"attraction": self.env.attraction_table,
                 "restaurant": self.env.restaurant_table,
                 "accommodation": self.env.accommodation_table}[kind](city)
        if table is None or table.empty:
            return pd.DataFrame()
        frame = table.copy()
        frame["price"] = pd.to_numeric(frame["price"], errors="coerce").fillna(0)
        return frame

    def _meal_kind(self, city: str, name: str) -> str:
        """Pick the meal slot whose window overlaps the restaurant's opening hours."""
        row = lookup_row(self.env.restaurant_table(city), name)
        if row is None:
            return "lunch"
        open_min = _hhmm(row.get("opentime")) or 0
        close_min = _hhmm(row.get("endtime")) or 24 * 60
        if close_min <= open_min:  # overnight venues
            close_min = 24 * 60
        best_kind, best_overlap = "lunch", -1
        for kind, (lo, hi) in MEAL_WINDOWS.items():
            overlap = min(hi, close_min) - max(lo, open_min)
            if overlap > best_overlap:
                best_kind, best_overlap = kind, overlap
        return best_kind

    def _leg(self, frm: str, to: str, mode: str, *, reverse: bool = False,
             window: tuple[int, int] | None = None) -> dict | None:
        pool = self.env.flights(frm, to) if mode == "airplane" else self.env.trains(frm, to)
        if not pool:
            return None
        rows = [r for r in pool if str(r.get("type", mode)) in (mode, "train" if mode == "train" else mode)]
        rows = rows or list(pool)
        if window is not None:
            low, high = window
            filtered = [r for r in rows if low <= (minutes(r["BeginTime"]) or 0) <= high]
            rows = filtered or rows
        if reverse:
            rows.sort(key=lambda r: -(minutes(r["BeginTime"]) or 0))
        else:
            rows.sort(key=lambda r: (minutes(r["BeginTime"]) or 0, float(r.get("Cost", 0))))
        pick = rows[0]
        leg = {key: pick.get(key) for key in ("From", "To", "BeginTime", "EndTime", "Cost")}
        leg["Cost"] = float(pick.get("Cost", 0))
        # The plan schema keys the leg by TrainID for trains and FlightID for flights;
        # an empty id makes the official checker reject the whole intercity event.
        if mode == "airplane":
            leg["FlightID"] = pick.get("FlightID", "")
        else:
            leg["TrainID"] = pick.get("TrainID", "")
        leg["type"] = mode
        return leg

    def _copy(self, state: dict) -> dict:
        return {"go": dict(state["go"]), "back": dict(state["back"]), "hotel": state["hotel"],
                "content": {day: list(items) for day, items in state["content"].items()}}

    # ------------------------------------------------------------------- stages
    def _stage_intercity(self, query, req: Spec, state):
        city, start = query["target_city"], query["start_city"]
        current = {str(state["go"].get("type")), str(state["back"].get("type"))}
        wanted = req.intercity or set()
        if not wanted or current <= wanted:
            return []
        out = []
        for mode in sorted(wanted):
            go_window = None
            if req.go_window:
                go_window = (minutes(req.go_window[0]) or 0, minutes(req.go_window[1]) or 24 * 60)
            go = self._leg(start, city, mode, window=go_window)
            back = self._leg(city, start, mode, reverse=True)
            if go is None or back is None:
                continue
            candidate = self._copy(state)
            candidate["go"], candidate["back"] = go, back
            out.append((candidate, mode))
        return out

    def _stage_hotel(self, query, req: Spec, state):
        city = query["target_city"]
        table = self._table("accommodation", city)
        if table.empty:
            return []
        wanted_names = set(req.names["accommodation"])
        wanted_features = set(req.types["accommodation"])
        room_type = req.room_type
        candidates: list[str] = []
        if wanted_names:
            candidates += [n for n in table["name"].astype(str) if n in wanted_names]
        mask = pd.Series(True, index=table.index)
        if wanted_features:
            mask &= table["featurehoteltype"].astype(str).isin(wanted_features)
        if room_type is not None and "numbed" in table.columns:
            mask &= pd.to_numeric(table["numbed"], errors="coerce") == room_type
        filtered = table[mask] if wanted_features or room_type is not None else table
        candidates += list(filtered.sort_values("price")["name"].astype(str).head(5))
        candidates += list(table.sort_values("price")["name"].astype(str).head(2))
        seen, out = {state["hotel"]}, []
        for name in candidates:
            if name in seen:
                continue
            seen.add(name)
            candidate = self._copy(state)
            candidate["hotel"] = name
            out.append((candidate, name))
            # A far-away hotel gets dropped by the scheduler, which silently loses the
            # accommodation activity (and with it the feature constraint).  Offer a
            # variant that frees the end of the last day so the hotel stays reachable.
            last_day = max(state["content"]) if state["content"] else 0
            items = candidate["content"].get(last_day, [])
            for index in range(len(items) - 1, -1, -1):
                if items[index][0] == "attraction":
                    trimmed = self._copy(state)
                    trimmed["hotel"] = name
                    del trimmed["content"][last_day][index]
                    out.append((trimmed, f"{name}+drop {items[index][1]}"))
                    break
        return out

    def _stage_must_attraction(self, query, req: Spec, state):
        city, days = query["target_city"], int(query["days"])
        table = self._table("attraction", city)
        present = {name for items in state["content"].values() for kind, name in items if kind == "attraction"}
        required = [n for n in sorted(req.names["attraction"]) if n not in present and n in set(table["name"].astype(str))]
        out = []
        for name in required:
            for day in range(days):
                items = state["content"].get(day, [])
                for pos in range(len(items) + 1):
                    candidate = self._copy(state)
                    candidate["content"].setdefault(day, []).insert(pos, ("attraction", name))
                    out.append((candidate, f"insert {name} d{day}@{pos}"))
                # swap out a non-required attraction of the same day
                for index, (kind, existing) in enumerate(items):
                    if kind != "attraction" or existing in req.names["attraction"]:
                        continue
                    candidate = self._copy(state)
                    candidate["content"][day][index] = ("attraction", name)
                    out.append((candidate, f"swap {existing}->{name} d{day}"))
        return out[:24]

    def _stage_must_restaurant(self, query, req: Spec, state):
        city, days = query["target_city"], int(query["days"])
        table = self._table("restaurant", city)
        present = {name for items in state["content"].values() for kind, name in items if kind in MEAL_WINDOWS}
        required = [n for n in sorted(req.names["restaurant"]) if n not in present and n in set(table["name"].astype(str))]
        out = []
        for name in required:
            kind = self._meal_kind(city, name)
            for day in range(days):
                items = state["content"].get(day, [])
                # Prefer replacing an existing meal of the same slot: appending a third
                # meal pushes the day later and trips "Inappropriate Meal Times".
                for index, (existing_kind, existing) in enumerate(items):
                    if existing_kind != kind or existing in req.names["restaurant"]:
                        continue
                    candidate = self._copy(state)
                    candidate["content"][day][index] = (kind, name)
                    out.append((candidate, f"swap-slot {existing}->{name} d{day}"))
                for index, (existing_kind, existing) in enumerate(items):
                    if existing_kind not in MEAL_WINDOWS:
                        continue
                    if existing in req.names["restaurant"]:
                        continue
                    candidate = self._copy(state)
                    candidate["content"][day][index] = (kind, name)
                    out.append((candidate, f"swap {existing}->{name} d{day}"))
                # Last resort: append only when the day still has room for a third meal.
                if len([1 for k, _ in items if k in MEAL_WINDOWS]) < 3:
                    candidate = self._copy(state)
                    candidate["content"].setdefault(day, []).append((kind, name))
                    out.append((candidate, f"add {kind} {name} d{day}"))
        return out[:20]

    def _stage_attraction_type(self, query, req: Spec, state):
        wanted = set(req.types["attraction"])
        if not wanted:
            return []
        city = query["target_city"]
        table = self._table("attraction", city)
        required = set(req.names["attraction"])
        pool = table[table["type"].astype(str).isin(wanted)].sort_values("price")["name"].astype(str).tolist()
        if not pool:
            return []
        out = []
        for day, items in state["content"].items():
            for index, (kind, name) in enumerate(items):
                if kind != "attraction" or name in required:
                    continue
                row = lookup_row(self.env.attraction_table(city), name)
                if row is not None and str(row.get("type")) in wanted:
                    continue
                for replacement in pool[:4]:
                    candidate = self._copy(state)
                    candidate["content"][day][index] = ("attraction", replacement)
                    out.append((candidate, f"{name}->{replacement} d{day}"))
        return out[:20]

    def _stage_restaurant_type(self, query, req: Spec, state):
        wanted = set(req.types["restaurant"])
        if not wanted:
            return []
        city = query["target_city"]
        table = self._table("restaurant", city)
        required = set(req.names["restaurant"])
        pool = table[table["cuisine"].astype(str).isin(wanted)].sort_values("price")["name"].astype(str).tolist()
        if not pool:
            return []
        out = []
        for day, items in state["content"].items():
            for index, (kind, name) in enumerate(items):
                if kind not in MEAL_WINDOWS or name in required:
                    continue
                row = lookup_row(self.env.restaurant_table(city), name)
                if row is not None and str(row.get("cusisine", row.get("cuisine"))) in wanted:
                    continue
                for replacement in pool[:4]:
                    candidate = self._copy(state)
                    candidate["content"][day][index] = (kind, replacement)
                    out.append((candidate, f"{name}->{replacement} d{day}"))
        return out[:20]

    def _stage_per_meal(self, query, req: Spec, state):
        cap = req.budgets.get("food_cost/food_count/people_count")
        if not cap:
            return []
        city = query["target_city"]
        table = self._table("restaurant", city)
        required = set(req.names["restaurant"])
        cheap = table.sort_values("price")["name"].astype(str).head(5).tolist()
        out = []
        for day, items in state["content"].items():
            for index, (kind, name) in enumerate(items):
                if kind not in MEAL_WINDOWS or name in required:
                    continue
                for replacement in cheap:
                    if replacement == name:
                        continue
                    candidate = self._copy(state)
                    candidate["content"][day][index] = (kind, replacement)
                    out.append((candidate, f"cheaper {name}->{replacement} d{day}"))
        return out[:12]

    def _stage_budget(self, query, req: Spec, state):
        if not req.budgets:
            return []
        city = query["target_city"]
        out = []
        hotels = self._table("accommodation", city)
        if state["hotel"] and not req.names["accommodation"]:
            cheaper = [n for n in hotels.sort_values("price")["name"].astype(str).head(3)
                       if n != state["hotel"]]
            for name in cheaper:
                candidate = self._copy(state)
                candidate["hotel"] = name
                out.append((candidate, f"cheaper hotel {name}"))
        required_attractions = set(req.names["attraction"])
        for day, items in state["content"].items():
            for index, (kind, name) in enumerate(items):
                if kind != "attraction" or name in required_attractions:
                    continue
                candidate = self._copy(state)
                del candidate["content"][day][index]
                out.append((candidate, f"drop {name} d{day}"))
        return out[:12]
