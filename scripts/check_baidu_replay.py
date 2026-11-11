"""Verify the Baidu adapter works fully offline by replaying captured responses.

No network. This is the mode the rest of the project uses while the account's
daily quota recovers.
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "reproduction/src")
sys.path.insert(0, "reproduction/ChinaTravel")

from shorttrip.dynamic.baidu import (  # noqa: E402
    BaiduFixtureClient,
    BaiduSource,
    get_client,
    self_test,
)


def main() -> int:
    print("signature self_test:", self_test()["ok"])
    client = get_client("auto")
    print("client mode:", getattr(client, "mode", "live"))
    source = BaiduSource(client)
    cases = [
        ("广州", "广州塔"),
        ("广州", "南越王博物院"),
        ("北京", "故宫博物院"),
        ("上海", "上海博物馆东馆"),
        ("广州", "ShortTrip 不存在的博物馆"),
        ("成都", "武侯祠"),  # deliberately not captured -> must say so
    ]
    out = []
    for city, name in cases:
        evidence = source.fetch(name, city)
        data = evidence.structured or {}
        row = {"city": city, "name": name, "ok": evidence.ok, "error": evidence.error}
        if evidence.ok:
            row.update({
                "chosen": data.get("name"),
                "identity_rule": data.get("identity_rule"),
                "score": data.get("candidate_score"),
                "hours": f"{data.get('open_time')}-{data.get('close_time')}",
                "price": data.get("price"),
                "rating": data.get("overall_rating"),
                "comment_bucket": data.get("comment_bucket"),
                "n_content_tags": len(data.get("content_tags") or []),
                "replayed": data.get("cached"),
            })
        out.append(row)
        print(json.dumps(row, ensure_ascii=False))
    print()
    print(json.dumps(client.budget_report(), ensure_ascii=False, indent=2))
    (source_dir := __import__("pathlib").Path("reproduction/results")).mkdir(parents=True, exist_ok=True)
    (source_dir / "baidu_replay_check.json").write_text(
        json.dumps({"mode": "replay", "signature_self_test": self_test()["ok"], "rows": out,
                    "budget": client.budget_report()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("wrote reproduction/results/baidu_replay_check.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
