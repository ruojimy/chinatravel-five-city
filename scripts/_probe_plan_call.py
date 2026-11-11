# -*- coding: utf-8 -*-
"""Throw-away probe 2: inspect finish_reason / usage for the plan() call."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ChinaTravel"))

from chinatravel.agent.llms import create_llm  # noqa: E402
from chinatravel.agent.pure_neuro_agent.prompts import DIRECT_PROMPT  # noqa: E402

NOTEBOOK = """Intercity transport 上海→杭州
去程：G1321 高铁，上海虹桥站06:10→杭州东站06:56，历时约46分钟，票价107.17元。返程：G1510 高铁，杭州东站18:01→上海虹桥站19:00，历时约59分钟，票价107.17元。
杭州一日游行程规划
【去程】G1321高铁，上海虹桥站06:10→杭州东站06:56，历时46分钟，票价107.17元。【返程】G1388高铁，杭州东站18:49→上海虹桥站19:41，历时约52分钟，票价107.17元。

【上午-灵隐寺】06:56抵达杭州东站，07:10乘地铁(07:10-08:02，4元)到灵隐寺。08:02-09:15游览灵隐寺(06:30-17:45开放，免费)。
【上午-雷峰塔】09:30乘地铁(09:30-10:17，3元)到雷峰塔。10:17-11:00游览雷峰塔(08:00-20:00开放，免费)。
【午餐】11:00-12:00在柳莺湖上·湖景餐厅·江南菜(西湖店)用餐，人均约226元。
【下午-西湖】12:00-14:00游览西湖风景名胜区，游船55元。
【晚餐】17:00-18:00在浙江西子宾馆·汪庄·牡丹厅用餐，人均约386元。
【返回】18:00乘地铁到杭州东站，乘G1388高铁18:49返回上海虹桥19:41。
"""
QUERY = "当前位置上海。我一个人想去杭州玩一天，预算1500人民币，请给我一个旅行规划。"

llm = create_llm("deepseek-flash")
prompt = DIRECT_PROMPT + NOTEBOOK + QUERY
messages = [{"role": "user", "content": prompt}]

for trial in range(1, 4):
    completion = llm.llm.chat.completions.create(
        model=llm.model,
        messages=messages,
        response_format={"type": "json_object"},
        max_tokens=4096,
        temperature=0,
        top_p=0.00000001,
    )
    ch = completion.choices[0]
    content = ch.message.content
    reasoning = getattr(ch.message, "reasoning_content", None)
    print(
        json.dumps(
            {
                "trial": trial,
                "finish_reason": ch.finish_reason,
                "content_len": len(content or ""),
                "reasoning_len": len(reasoning or ""),
                "usage": completion.usage.model_dump() if completion.usage else None,
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )

# Now reproduce through the adapter (default max_tokens=4096)
for trial in range(1, 3):
    out = llm(messages, json_mode=True, one_line=False)
    print(
        json.dumps({"adapter_trial": trial, "len": len(out), "head": out[:80]}, ensure_ascii=False),
        file=sys.stderr,
    )
