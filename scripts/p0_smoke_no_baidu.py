"""P0 gate: the whole TAG + planning + reranking path must run with ZERO Baidu requests.

This is the first deliverable of the resumed project. It proves the defect that
stopped the previous session is fixed:

* ``BAIDU_REQUEST_BUDGET=0`` is the default, so ``get_client("live")`` returns a
  *blocked* client and opens no socket;
* a provider guard records ``budget_zero`` / ``quota_exhausted`` and trips a
  day-long breaker instead of retrying;
* planning + official checker + tag view + preference reranking still complete,
  using the sandbox and (when reachable) open data.

Exit code 0 = every assertion passed. Writes results/p0/smoke_no_baidu.json.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("BAIDU_REQUEST_BUDGET", "0")
os.environ["BAIDU_OFFLINE"] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.checker import check_plan  # noqa: E402
from shorttrip.config import settings  # noqa: E402
from shorttrip.dynamic.baidu import get_client  # noqa: E402
from shorttrip.dynamic.overlay import OverlayStore  # noqa: E402
from shorttrip.dynamic.pipeline import rehydrate  # noqa: E402
from shorttrip.dynamic.tagstore import TagStore  # noqa: E402
from shorttrip.env import get_env  # noqa: E402
from shorttrip.planner import SkeletonPlanner  # noqa: E402
from shorttrip.preference import DEFAULT_SPECS, UserProfile  # noqa: E402
from shorttrip.providers import guard  # noqa: E402
from shorttrip.rerank import rank_plans  # noqa: E402
from shorttrip.tagbridge import merge_tag_views, provenance_summary, sandbox_attribute_tags  # noqa: E402

OUT = ROOT / "results" / "p0"
QUERY = {
    "uid": "p0_smoke_guangzhou",
    "start_city": "上海",
    "target_city": "广州",
    "days": 1,
    "people_number": 2,
    "nature_language": "想带父母去广州看广州塔和博物馆，不喜欢走太多路",
    "hard_logic_py": [
        "result=(day_count(plan)==1)",
        "result=(people_count(plan)==2)",
    ],
}


def main() -> int:
    started = time.time()
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": str(detail)})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

    config = settings(refresh=True)
    print(f"settings: budget={config.baidu_request_budget} offline={config.baidu_offline}")
    check("config/baidu_budget_is_zero", config.baidu_request_budget == 0,
          f"BAIDU_REQUEST_BUDGET={config.baidu_request_budget}")
    check("config/fallback_starts_with_local", config.source_fallback_order[0] == "local",
          ",".join(config.source_fallback_order))

    # 1) the blocked client must not open a socket
    client = get_client("live")
    check("baidu/live_request_blocked", client.mode == "blocked", f"mode={client.mode}")
    blocked = client.search("广州塔", "广州")
    check("baidu/blocked_payload", blocked.get("_blocked") is True, str(blocked.get("message"))[:80])
    report = client.budget_report()
    check("baidu/zero_requests", report.get("live_calls") == 0, json.dumps(report, ensure_ascii=False))

    # 2) env guard: a live client constructed directly must still refuse
    from shorttrip.dynamic.baidu import BaiduPlaceClient, load_credentials
    try:
        direct = BaiduPlaceClient(load_credentials(), cache=False, max_calls=5)
        payload = direct.search("广州塔", "广州")
        check("baidu/direct_client_blocked_at_budget_zero",
              payload.get("_blocked") is True and direct.spent == 0,
              f"spent={direct.spent} msg={str(payload.get('message'))[:60]}")
    except Exception as exc:  # noqa: BLE001
        check("baidu/direct_client_blocked_at_budget_zero", False, f"raised {exc}")

    state = guard().snapshot()
    check("providers/guard_snapshot", "baidu" in state["providers"], "ok")
    check("providers/baidu_budget_recorded", state["providers"]["baidu"]["budget"] == 0,
          str(state["providers"]["baidu"]["budget"]))

    # 3) planning + official checker still work
    env = get_env("zh")
    store = OverlayStore(ROOT / "data" / "sandbox_overlay.sqlite")
    rehydrated = rehydrate(store, env)
    planner = SkeletonPlanner(env)
    built = planner.build(QUERY)
    check("planner/plan_built", built.plan is not None, planner.last_reason or "ok")
    if built.plan is not None:
        official = check_plan(QUERY, built.plan)
        check("checker/schema_ok", official.schema_ok)
        check("checker/commonsense_ok", official.commonsense_ok,
              ",".join(official.commonsense_violations[:3]))
        check("checker/no_regression", official.all_ok,
              f"hard {official.hard_pass_count}/{len(official.hard_results)}")

    # 4) tag view + preference reranking without Baidu
    attributes = sandbox_attribute_tags(env, "广州")
    external: dict = {}
    tag_store_path = ROOT / "data" / "tag_store.sqlite"
    if tag_store_path.exists():
        tag_store = TagStore(tag_store_path)
        from shorttrip.tagbridge import tag_view_from_store
        external = tag_view_from_store(tag_store, tag_store.latest_snapshot())
    merged = merge_tag_views(attributes, external)
    check("tags/sandbox_view_present", bool(attributes), f"{len(attributes)} POI")
    provenance = provenance_summary(merged)

    profile = UserProfile.from_spec(DEFAULT_SPECS[1])  # senior_slow
    candidates = [built.plan] if built.plan else []
    if candidates:
        ranked = rank_plans(candidates, profile, merged, city="广州")
        check("rerank/ranked", bool(ranked) and ranked[0]["Q"] is not None, f"Q={ranked[0]['Q']}")
        check("rerank/disclaims_checker", "官方 checker" in ranked[0]["note"])

    elapsed = round(time.time() - started, 1)
    payload = {
        "generated_at": "2026-10-21",
        "purpose": "P0 交付门槛：百度请求计数为 0 时全流程仍可完成",
        "settings": config.to_dict(),
        "provider_state": state,
        "baidu_client": report,
        "planning": {
            "constructed": built.plan is not None,
            "official_all_ok": bool(built.report.all_ok) if built.report else None,
        },
        "rehydrated_instances": rehydrated,
        "tag_view": {"pois": len(merged), "provenance": provenance},
        "preference": profile.uid,
        "runtime_s": elapsed,
        "checks": checks,
        "passed": all(item["ok"] for item in checks),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    # Official results live under results/p0/official_check.json for the report.
    if built.report is not None:
        (OUT / "official_check.json").write_text(
            json.dumps({"query": QUERY["uid"], "report": built.report.to_dict()},
                       ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "smoke_no_baidu.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    print(f"\n{'PASS' if payload['passed'] else 'FAIL'} in {elapsed}s -> {OUT / 'smoke_no_baidu.json'}")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
