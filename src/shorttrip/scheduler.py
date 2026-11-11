"""Content -> timed-plan scheduler.

Repair in ShortTrip works on *content* (which POI on which day, plus the two
intercity legs) rather than on raw timestamps: the scheduler re-runs the
transport/time chaining from scratch so that any edit produces a plan whose
legs still match `goto` exactly.
"""
from __future__ import annotations

from .env import SandboxEnv, minutes
from .plan import DayBuilder, ceil_div, itinerary


def find_record(records: list[dict], **fields) -> dict | None:
    for record in records:
        if all(str(record.get(key)) == str(value) for key, value in fields.items()):
            return record
    return None


def extract_content(env: SandboxEnv, plan: dict) -> dict:
    """Split a plan into (intercity legs, per-day POI content, hotel)."""
    days = plan["itinerary"]
    first = days[0]["activities"][0]
    last = days[-1]["activities"][-1]
    go = {
        "TrainID": first.get("TrainID", ""),
        "From": first.get("start", ""),
        "To": first.get("end", ""),
        "BeginTime": first["start_time"],
        "EndTime": first["end_time"],
        "Cost": first.get("price", 0),
        "type": first.get("type", "train"),
    }
    back = {
        "TrainID": last.get("TrainID", ""),
        "From": last.get("start", ""),
        "To": last.get("end", ""),
        "BeginTime": last["start_time"],
        "EndTime": last["end_time"],
        "Cost": last.get("price", 0),
        "type": last.get("type", "train"),
    }
    content: dict[int, list[tuple[str, str]]] = {}
    hotel = None
    for index, day in enumerate(days):
        items: list[tuple[str, str]] = []
        for activity in day["activities"]:
            kind = activity.get("type")
            if kind in ("attraction", "lunch", "dinner", "breakfast"):
                items.append((kind, str(activity.get("position"))))
            elif kind == "accommodation" and hotel is None:
                hotel = str(activity.get("position"))
        content[index] = items
    return {"go": go, "back": back, "content": content, "hotel": hotel}


def lookup_row(table, name: str) -> dict | None:
    if table is None or name is None:
        return None
    match = table[table["name"].astype(str) == str(name)]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def schedule(
    env: SandboxEnv,
    query: dict,
    go: dict,
    back: dict,
    hotel: str | None,
    content: dict[int, list[tuple[str, str]]],
    *,
    day_cutoff_last: int = 21 * 60,
    day_cutoff_mid: int = 19 * 60 + 30,
    route_slack_factor: float = 1.3,
) -> dict | None:
    city = query["target_city"]
    people = int(query["people_number"])
    days = int(query["days"])
    hotel_row = lookup_row(env.accommodation_table(city), hotel) if hotel else None
    day_plans: list[list[dict]] = []

    for day_index in range(days):
        is_first = day_index == 0
        is_last = day_index == days - 1
        builder = DayBuilder(env, city, people, day_index)
        builder.day_cutoff = day_cutoff_last if is_last else day_cutoff_mid
        if is_first:
            builder.activities.append(_intercity(go, people, []))
            builder.time = go["EndTime"]
            builder.position = go["To"]
        else:
            builder.set_start("08:30", hotel or go["To"])

        deadline = minutes(back["BeginTime"]) - 25 if is_last else None

        def fits(duration: int, position: str) -> bool:
            """Can we still reach the departure station after `duration` minutes?"""
            if deadline is None:
                return True
            mode = env.best_mode(city, position, back["From"])
            travel = env.trip_seconds(city, position, back["From"], mode) if mode else None
            if travel is None:
                return False
            travel = travel * route_slack_factor
            return minutes(builder.time) + travel * 60 + duration + 15 <= deadline

        for kind, name in content.get(day_index, []):
            if kind == "attraction":
                row = lookup_row(env.attraction_table(city), name)
                if row is None:
                    continue
                duration = max(45, int(round(float(row["recommendmintime"]) * 60)))
                if not fits(duration, name):
                    continue
                builder.add_attraction(row, duration_min=duration)
            elif kind in ("lunch", "dinner", "breakfast"):
                row = lookup_row(env.restaurant_table(city), name)
                if row is None:
                    if kind == "breakfast":
                        row = lookup_row(env.accommodation_table(city), name)
                    if row is None:
                        continue
                if not fits(60, name):
                    continue
                builder.add_meal(kind, row, 60)

        if is_last:
            transports = builder.close_with_station(back["From"], back["BeginTime"])
            if transports is None:
                return None
            builder.activities.append(_intercity(back, people, transports))
        elif hotel_row is not None:
            rooms = max(1, ceil_div(people, max(1, int(hotel_row["numbed"]))))
            if not builder.add_hotel(hotel_row, rooms):
                return None
        day_plans.append(builder.activities)

    return {
        "people_number": people,
        "start_city": query["start_city"],
        "target_city": city,
        "itinerary": itinerary(day_plans),
    }


def _intercity(record: dict, people: int, transports: list[dict]) -> dict:
    price = float(record["Cost"])
    kind = record.get("type", "train")
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
    if kind == "airplane":
        activity["FlightID"] = record.get("FlightID", "")
    else:
        activity["TrainID"] = record.get("TrainID", "")
    return activity
