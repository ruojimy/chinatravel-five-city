"""Install the release-local preview hooks into the pinned upstream workbench."""

import argparse
from pathlib import Path


def edit(path, before, after, marker):
    source = path.read_text(encoding="utf-8-sig")
    if marker in source:
        return
    if source.count(before) != 1:
        raise ValueError(f"Unexpected 8795 source in {path}")
    path.write_text(source.replace(before, after), encoding="utf-8")


def apply(release):
    planner = release / "combined version_personalized/chinatravel"
    runtime = release / "shorttrip_cloud/planner_preview.py"
    (planner.parent / "shorttrip_planner_preview.py").write_bytes(runtime.read_bytes())

    edit(planner / "environment/planning_access.py",
         "    return Sandbox('G3')",
         "    if _PROFILE == 'expanded12':\n"
         "        from shorttrip_planner_preview import sandbox_for\n"
         "        return sandbox_for(Sandbox)\n"
         "    return Sandbox('G3')", "from shorttrip_planner_preview import sandbox_for")
    edit(planner / "personalization/city_scope.py",
         "FROZEN_CITIES = frozenset(('西安', '厦门'))",
         "from shorttrip_planner_preview import policy\n\n"
         "FROZEN_CITIES = frozenset(('西安', '厦门')) - frozenset(policy()['cities'])",
         "from shorttrip_planner_preview import policy")
    edit(planner / "environment/sandbox/__main__.py",
         '"CT_SANDBOX_ENGINE_ROOT": str(v20 / "engine"),',
         '"CT_SANDBOX_ENGINE_ROOT": os.environ.get("SHORTTRIP_REFERENCE_ENGINE") or str(v20 / "engine"),',
         'os.environ.get("SHORTTRIP_REFERENCE_ENGINE")')
    path = planner / "personalization/world_facts.py"
    edit(path, "from functools import lru_cache",
         "from functools import lru_cache\n"
         "from shorttrip_planner_preview import policy, trial_price",
         "import policy, trial_price")
    transport = planner / "environment/tools/intercity_transport/apis.py"
    edit(transport, "            if travel_date and seat_code:",
         "            from shorttrip_planner_preview import apply_rail_fares\n"
         "            filtered_trains = apply_rail_fares(filtered_trains, start_city, end_city, self.lang)\n"
         "            if travel_date and seat_code:", "import apply_rail_fares")
    edit(path, "            published = data.get('CostSource')",
         "            published = data.get('CostSource')\n"
         "            if published == 'shorttrip_historical_trial':\n"
         "                freshness = 'trial_historical_schedule'", "freshness = 'trial_historical_schedule'")
    edit(path, "                                     and freshness == 'static_benchmark_snapshot', 'verified_for_date': False}",
         "                                     and freshness in ('static_benchmark_snapshot', 'trial_historical_schedule'),\n"
         "                                     'verified_for_date': False}", "and freshness in ('static_benchmark_snapshot'")
    edit(path, "def price(data, access, unit):\n    value",
         "def price(data, access, unit):\n"
         "    trial = trial_price(data, access, unit)\n"
         "    if trial is not None:\n"
         "        return trial\n"
         "    value", "trial = trial_price(data, access, unit)")
    edit(path, "        self._route_accepts_party =",
         "        if policy()['id']:\n"
         "            self.version['reference_preview'] = policy()['id']\n"
         "        self._route_accepts_party =", "self.version['reference_preview']")
    js = release / "shorttrip-webui/shorttrip-webui/webui/app.js"
    change = '''      const city = [t.targetCity, t.city, t.title].filter(Boolean).join(" ");
      const trialPlan = window.SHORTTRIP_TRIAL_CITIES?.some(name => city.includes(name));
      $("#reviewCount").textContent = trialPlan ? "已试排 · 历史票价、酒店估价供参考" : "已按旅行快照核验 · 价格为参考";
      if (trialPlan) $("#reviewCount").title = "厦门大床房默认每间 2 人试排，实际房型与报价以预订为准。";'''
    edit(js, '      $("#reviewCount").textContent = "已按旅行快照核验 · 价格为参考";',
         change, "const trialPlan = window.SHORTTRIP_TRIAL_CITIES")
    survey = '''      const button = $("#fbSend");
      button.disabled = true;
      try {
        await API.submitFeedback({ score, text: $("#fbText").value, tripId: trip() && trip().id });
        closeModal(); toast("感谢反馈！");
      } catch (error) {
        toast(error.message || "暂时未保存，请重试。");
      } finally {
        button.disabled = false;
      }'''
    edit(js, '''      await API.submitFeedback({ score, text: $("#fbText").value, tripId: trip() && trip().id });
      closeModal(); toast("感谢反馈！");''', survey, 'const button = $("#fbSend");')


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("release", type=Path)
    args = parser.parse_args()
    apply(args.release)
