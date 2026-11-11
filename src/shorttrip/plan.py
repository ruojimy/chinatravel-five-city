"""Plan JSON construction helpers (ChinaTravel activity schema).

The ChinaTravel checker recomputes every transport leg with `goto` and compares
`start/end/start_time/end_time` by exact string equality and `price/distance`
within 0.1, so legs are always produced by `SandboxEnv.leg_plan` and only the
multiplicities (tickets / cars) are filled in here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .env import SandboxEnv, hhmm, minutes


def ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def materialise_legs(legs: list[dict], people: int) -> list[dict]:
    """Attach the price/tickets/cars fields the checker expects."""
    out = []
    for leg in legs:
        leg = dict(leg)
        tool_cost = leg["cost"]
        if leg["mode"] == "metro":
            leg["price"] = tool_cost
            leg["tickets"] = people
            leg["cost"] = tool_cost * people
        elif leg["mode"] == "taxi":
            cars = ceil_div(people, 4)
            leg["price"] = tool_cost
            leg["cars"] = cars
            leg["cost"] = tool_cost * cars
        else:
            leg["price"] = 0
            leg["cost"] = 0
        out.append(leg)
    return out


@dataclass
class Activity:
    payload: dict


class DayBuilder:
    """Appends activities to one day, chaining clock time and position."""

    def __init__(self, env: SandboxEnv, city: str, people: int, day_index: int):
        self.env = env
        self.city = city
        self.people = people
        self.day_index = day_index
        self.activities: list[dict] = []
        self.time: str = "08:30"
        self.position: str | None = None
        self.mode_preference: str = "metro"
        self.day_cutoff: int = 22 * 60

    # ------------------------------------------------------------------ util
    def set_start(self, clock: str, position: str) -> None:
        self.time = clock
        self.position = position

    def can_move(self, target: str) -> str | None:
        if self.position == target:
            return "same"
        return self.env.best_mode(self.city, self.position, target, self.mode_preference)

    def move(self, target: str, mode: str | None = None) -> list[dict] | None:
        """Transport legs from the current position, or [] when already there."""
        if self.position == target:
            return []
        mode = mode or self.can_move(target)
        if mode in (None, "same"):
            return None
        legs = self.env.leg_plan(self.city, self.position, target, mode, self.time)
        if legs is None:
            return None
        legs = materialise_legs(legs, self.people)
        return legs

    def _append(self, activity: dict, transports: list[dict]) -> None:
        activity["transports"] = transports
        self.activities.append(activity)
        self.time = activity["end_time"]
        self.position = activity.get("position", activity.get("end"))

    # ------------------------------------------------------------ activities
    def add_intercity(self, record: dict, kind: str, transports: list[dict] | None = None) -> None:
        price = float(record["Cost"])
        activity = {
            "start": record["From"],
            "end": record["To"],
            "start_time": record["BeginTime"],
            "end_time": record["EndTime"],
            "price": price,
            "cost": price * self.people,
            "tickets": self.people,
            "type": kind,
            "transports": transports or [],
        }
        if kind == "train":
            activity["TrainID"] = record["TrainID"]
        else:
            activity["FlightID"] = record["FlightID"]
        self.activities.append(activity)
        if transports:
            self.time = activity["end_time"]
        else:
            self.time = activity["end_time"]
        self.position = activity["end"]

    def add_attraction(self, row, start: str | None = None, duration_min: int | None = None) -> bool:
        name = str(row["name"])
        legs = self.move(name)
        if legs is None:
            return False
        arrive = legs[-1]["end_time"] if legs else self.time
        duration = duration_min or int(round(float(row["recommendmintime"]) * 60)) or 90
        start_time = max(minutes(arrive), minutes(str(row["opentime"])))
        end_time = start_time + duration
        close = _close_minutes(str(row["opentime"]), str(row["endtime"]))
        if end_time > close:
            end_time = close
        end_time = min(end_time, self.day_cutoff)
        if end_time - start_time < 30:
            return False
        price = float(row["price"])
        activity = {
            "position": name,
            "type": "attraction",
            "price": price,
            "cost": price * self.people,
            "tickets": self.people,
            "start_time": hhmm(start_time),
            "end_time": hhmm(end_time),
        }
        self._append(activity, legs)
        return True

    def add_meal(self, kind: str, row, duration_min: int = 60) -> bool:
        name = str(row["name"])
        legs = self.move(name)
        if legs is None:
            return False
        arrive = legs[-1]["end_time"] if legs else self.time
        start_time = max(minutes(arrive), minutes(str(row["opentime"])))
        end_time = start_time + duration_min
        close = _close_minutes(str(row["opentime"]), str(row["endtime"]))
        if end_time > close:
            end_time = close
        end_time = min(end_time, self.day_cutoff)
        if end_time - start_time < 30:
            return False
        price = float(row["price"])
        activity = {
            "position": name,
            "type": kind,
            "price": price,
            "cost": price * self.people,
            "start_time": hhmm(start_time),
            "end_time": hhmm(end_time),
        }
        self._append(activity, legs)
        return True

    def add_hotel(self, row, rooms: int) -> bool:
        name = str(row["name"])
        legs = self.move(name)
        if legs is None:
            return False
        arrive = legs[-1]["end_time"] if legs else self.time
        if minutes(arrive) >= 23 * 60 + 40:
            return False
        start_time = max(minutes(arrive), minutes(str(row["opentime"])) if "opentime" in row else 0)
        end_time = 24 * 60
        if end_time - start_time < 30:
            start_time = end_time - 30
        price = float(row["price"])
        activity = {
            "position": name,
            "type": "accommodation",
            "room_type": int(row["numbed"]),
            "price": price,
            "cost": price * rooms,
            "rooms": rooms,
            "start_time": hhmm(start_time),
            "end_time": "24:00",
        }
        self._append(activity, legs)
        return True

    def close_with_station(self, station: str, depart: str) -> list[dict] | None:
        """Travel to the departure station, arriving before `depart`."""
        if station == self.position:
            return []
        mode = self.env.best_mode(self.city, self.position, station, self.mode_preference)
        if mode is None:
            return None
        for attempt in (mode, "taxi", "metro", "walk"):
            legs = self.env.leg_plan(self.city, self.position, station, attempt, self.time)
            if not legs:
                continue
            if minutes(legs[-1]["end_time"]) <= minutes(depart):
                return materialise_legs(legs, self.people)
            # try to leave earlier only if the gap allows a different mode
        return None


def _close_minutes(open_time: str, close_time: str) -> int:
    open_min = minutes(open_time)
    close_min = minutes(close_time)
    if close_min <= open_min:
        close_min += 24 * 60
    return close_min


def itinerary(activities_by_day: list[list[dict]]) -> list[dict]:
    return [
        {"day": index + 1, "activities": activities}
        for index, activities in enumerate(activities_by_day)
    ]


def plan_cost(plan: dict) -> float:
    total = 0.0
    for day in plan.get("itinerary", []):
        for activity in day["activities"]:
            total += float(activity.get("cost") or 0)
            for transport in activity.get("transports", []):
                total += float(transport.get("cost") or 0)
    return round(total, 2)


def plan_summary(plan: dict) -> dict:
    counts: dict[str, int] = {}
    for day in plan.get("itinerary", []):
        for activity in day["activities"]:
            counts[activity.get("type", "?")] = counts.get(activity.get("type", "?"), 0) + 1
    return {
        "days": len(plan.get("itinerary", [])),
        "activities": sum(counts.values()),
        "types": counts,
        "cost": plan_cost(plan),
        "positions": [
            a.get("position", a.get("start"))
            for day in plan.get("itinerary", [])
            for a in day["activities"]
        ],
    }
