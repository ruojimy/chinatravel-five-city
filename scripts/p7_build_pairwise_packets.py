"""P3 step 2: build blinded pairwise evaluation packets.

What a rater sees
-----------------
`packets.csv` / `packets.html` contain, per pair: the user's original request, two
itineraries (A/B), cost, transit minutes, walking/attraction list — and **nothing
else**. No model score, no group label, no indication which one the system prefers.

What the rater never sees
-------------------------
`pairs_private.json` keeps the A/B -> candidate mapping and the model scores, so the
analysis script can compute model-vs-human agreement afterwards. Blinding the file a
human opens is the whole point; keeping the mapping separately is what makes the
comparison possible.

A/B order is randomised per pair from a fixed seed so the packet is reproducible while
not systematically favouring one side.

Outputs
  datasets/human_preference/packets.csv      (3 rater columns, 4-way choice)
  datasets/human_preference/packets.html     (fill-in form)
  datasets/human_preference/pairs_private.json
  results/p7_human_evaluation/packets_report.json
"""
from __future__ import annotations

import csv
import html
import json
import random
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POOLS = ROOT / "results" / "p7_human_evaluation" / "pools.json"
OUT_DATA = ROOT / "datasets" / "human_preference"
OUT_RES = ROOT / "results" / "p7_human_evaluation"
SEED = 20261022
RATERS = 3


def minutes(hhmm: str) -> int:
    try:
        hour, minute = str(hhmm).split(":")[:2]
        return int(hour) * 60 + int(minute)
    except (TypeError, ValueError):
        return 0


def humanise(plan: dict) -> dict:
    """Turn a plan into what a traveller would read on a booking site."""
    days = []
    for day in plan.get("itinerary", []):
        rows = []
        for activity in day.get("activities", []):
            kind = activity.get("type", "?")
            position = activity.get("position") or f'{activity.get("start")}→{activity.get("end")}'
            start, end = activity.get("start_time", ""), activity.get("end_time", "")
            detail = f"{start}–{end}　{position}"
            if kind == "attraction":
                detail = f"{start}–{end}　景点：{position}（门票 {activity.get('price', 0)} 元/人）"
            elif kind in ("lunch", "dinner", "breakfast"):
                label = {"lunch": "午餐", "dinner": "晚餐", "breakfast": "早餐"}[kind]
                detail = f"{start}–{end}　{label}：{position}"
            elif kind == "accommodation":
                detail = f"{start}–{end}　住宿：{position}"
            elif kind in ("train", "airplane"):
                detail = (f"{start}–{end}　{activity.get('start')}→{activity.get('end')}"
                          f"（{kind}，{activity.get('price', 0)} 元/人）")
            transports = activity.get("transports") or []
            if transports:
                legs = "；".join(
                    f'{leg.get("start")}→{leg.get("end")} {leg.get("mode")} '
                    f'{minutes(leg.get("end_time")) - minutes(leg.get("start_time"))}分钟'
                    for leg in transports)
                detail += f"　[交通 {legs}]"
            rows.append(detail)
        days.append({"day": day.get("day"), "rows": rows})
    return {"days": days}


def main() -> int:
    payload = json.loads(POOLS.read_text(encoding="utf-8"))
    rng = random.Random(SEED)
    per_query = int(sys.argv[1]) if len(sys.argv) > 1 else 10

    packets: list[dict] = []
    private: list[dict] = []
    for pool in payload["pools"]:
        candidates = pool["candidates"]
        if len(candidates) < 2:
            continue
        all_pairs = list(combinations(range(len(candidates)), 2))
        # Prefer pairs that differ in at least one visible dimension, then sample.
        def contrast(pair: tuple[int, int]) -> float:
            left, right = candidates[pair[0]]["stats"], candidates[pair[1]]["stats"]
            return (abs(left["cost"] - right["cost"]) / 100.0
                    + abs(left["n_attractions"] - right["n_attractions"])
                    + abs(left["transit_minutes"] - right["transit_minutes"]) / 30.0)
        all_pairs.sort(key=lambda pair: -contrast(pair))
        shortlist = all_pairs[: max(per_query * 2, per_query)]
        rng.shuffle(shortlist)
        chosen = shortlist[:per_query]
        for index, (left, right) in enumerate(chosen):
            a, b = (left, right) if rng.random() < 0.5 else (right, left)
            pair_id = f'{pool["uid"]}__p{index + 1:02d}'
            pack = {
                "pair_id": pair_id,
                "query_uid": pool["uid"],
                "city": pool["city"],
                "days": pool["days"],
                "people": pool["people"],
                "request": pool.get("nature_language") or "",
                "A_id": a, "B_id": b,
                "A": humanise(candidates[a]["plan"]),
                "B": humanise(candidates[b]["plan"]),
                "A_cost": candidates[a]["stats"]["cost"],
                "B_cost": candidates[b]["stats"]["cost"],
                "A_transit_min": candidates[a]["stats"]["transit_minutes"],
                "B_transit_min": candidates[b]["stats"]["transit_minutes"],
                "A_attractions": "、".join(candidates[a]["stats"]["attractions"]),
                "B_attractions": "、".join(candidates[b]["stats"]["attractions"]),
            }
            packets.append(pack)
            private.append({"pair_id": pair_id, "candidate_A": a, "candidate_B": b,
                            "signature_A": candidates[a]["signature"],
                            "signature_B": candidates[b]["signature"],
                            "config_A": candidates[a]["config"], "config_B": candidates[b]["config"]})

    # ---- CSV (rater-facing, no scores)
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    fields = ["pair_id", "query_uid", "city", "days", "people", "request",
              "A_cost", "B_cost", "A_transit_min", "B_transit_min",
              "A_attractions", "B_attractions", "A_text", "B_text"]
    for rater in range(1, RATERS + 1):
        fields += [f"r{rater}_choice", f"r{rater}_reason"]
    with (OUT_DATA / "packets.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for pack in packets:
            row = {key: pack[key] for key in fields[:12]}
            row["A_text"] = " / ".join(f'第{d["day"]}天：' + "；".join(d["rows"]) for d in pack["A"]["days"])
            row["B_text"] = " / ".join(f'第{d["day"]}天：' + "；".join(d["rows"]) for d in pack["B"]["days"])
            for rater in range(1, RATERS + 1):
                row[f"r{rater}_choice"] = ""
                row[f"r{rater}_reason"] = ""
            writer.writerow(row)

    # ---- HTML form
    style = ("body{font-family:'Microsoft YaHei',sans-serif;max-width:1100px;margin:24px auto;"
             "line-height:1.5;color:#16302b}h2{border-bottom:2px solid #2f668c;padding-bottom:4px}"
             ".meta{color:#6b827c;font-size:13px}.plan{border:1px solid #d7e3de;border-radius:8px;"
             "padding:10px 14px;margin:8px 0;background:#fff}.opt{display:flex;gap:12px;flex-wrap:wrap;"
             "margin:8px 0}.opt label{background:#e7eff5;padding:6px 10px;border-radius:6px;cursor:pointer}"
             ".ask{background:#f8ece4;padding:8px 12px;border-radius:6px}")
    parts = ["<!doctype html><html lang='zh'><meta charset='utf-8'>",
             f"<title>行程成对偏好评价（{len(packets)} 对）</title><style>{style}</style><body>",
             "<h1>行程成对偏好评价</h1>",
             "<p class='ask'>请只依据“用户要求”和两套行程本身判断：<b>哪一套更适合这位用户</b>。"
             "两侧的模型分数与来源已被隐藏，A/B 顺序是随机的。可选：A 更好 / B 更好 / 差不多 / 无法判断；"
             "并请写一句理由。请勿参考价格以外未给出的信息。</p>"]
    for pack in packets:
        parts.append(f"<h2>{html.escape(pack['pair_id'])}</h2>")
        parts.append(f"<p class='meta'>{html.escape(pack['city'])} · {pack['days']} 天 · "
                     f"{pack['people']} 人　｜　用户要求：{html.escape(pack['request'])}</p>")
        for side in ("A", "B"):
            parts.append(f"<div class='plan'><b>行程 {side}</b>"
                         f"<span class='meta'>　总费用约 {pack[side + '_cost']} 元，"
                         f"市内交通 {pack[side + '_transit_min']} 分钟</span><br>")
            for day in pack[side]["days"]:
                parts.append(f"<b>第{day['day']}天</b><br>")
                parts.extend(f"<div>· {html.escape(row)}</div>" for row in day["rows"])
            parts.append("</div>")
        choices = ["A 更好", "B 更好", "差不多", "无法判断"]
        parts.append("<div class='opt'>" + "".join(
            f"<label><input type='radio' name='{pack['pair_id']}' value='{value}'> {value}</label>"
            for value in choices) + "</div>")
        parts.append("<p class='ask'>理由（必填一句）：<input type='text' style='width:70%'></p>")
    parts.append("</body></html>")
    (OUT_DATA / "packets.html").write_text("\n".join(parts), encoding="utf-8")

    (OUT_DATA / "pairs_private.json").write_text(json.dumps({
        "generated_at": "2026-10-22", "seed": SEED,
        "note": "A/B -> 候选映射与配置，仅用于事后计算模型-人一致率；不要给评价者看",
        "pairs": private}, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "generated_at": "2026-10-22",
        "stage": "P3 packet generation",
        "queries": len(payload["pools"]),
        "pool_sizes": [pool["pool_size"] for pool in payload["pools"]],
        "pairs_generated": len(packets),
        "pairs_per_query": per_query,
        "raters_per_pair": RATERS,
        "ratings_collected": 0,
        "blinding": {"model_scores_in_packet": False, "group_labels_in_packet": False,
                     "ab_order_randomised": True, "seed": SEED,
                     "private_mapping": "datasets/human_preference/pairs_private.json"},
        "protocol": {
            "choice": ["A 更好", "B 更好", "差不多", "无法判断"],
            "reason_required": True,
            "target_pairs": 30,
            "target_raters": 3,
            "independent_of_model": "评价者只看行程与用户要求；模型分数不在材料中",
        },
        "status": "材料已就绪，尚无人工评分（0 条），因此不报告任何一致性指标",
    }
    OUT_RES.mkdir(parents=True, exist_ok=True)
    (OUT_RES / "packets_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                                 encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("queries", "pool_sizes", "pairs_generated",
                                             "raters_per_pair", "ratings_collected")},
                     ensure_ascii=False))
    print("wrote", OUT_DATA / "packets.csv", "|", OUT_DATA / "packets.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
