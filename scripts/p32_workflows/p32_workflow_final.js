// Auto-exported from results/p32_llm_96/prompts/final.txt — run with the harness workflow tool.

const base = "C:/Users/xiech/Downloads/计算机软件工程概论/reproduction/results/p32_llm_96";
const uids = args.uids || (() => {
  const out = [];
  for (const p of ["E", "D", "N"]) for (let i = 1; i <= 32; i++) out.push(p + String(i).padStart(2, "0"));
  return out;
})();
const chunkSize = 6;

const TEMPLATE = "【角色】同一道题的最终阶段。你在第一阶段已经给过一份静态方案，现在拿到了真实检索到的动态证据。严格按规则定稿。\n\n【硬性禁止】\n- 不联网、不调用任何 API、不运行项目里的 planner / checker / 评分脚本。\n- 只读这两个文件：\n  1) 证据包：{PACK}\n  2) 你的静态方案：{STATIC_OUT}\n- 不要读工作区里的其它文件，尤其不要读 results/p31_five_city_96/ 下的 final、evaluation、summary。\n- evidence 之外的时长、票价、营业时间一律不能编造；不要用常识补。\n\n【输入文件里有什么】\n- 证据包里是 task（和第一阶段同一道题）与 evidence：weather（按城市/日期）、routes（按 from→to 的实测公交/地铁时长与票价，含失败状态 no_transit_route 与直线距离）、places（POI 检索结果，可能有 opentime_text）、details（POI 详情，可能有 hours_text/hours_window）。\n- 静态方案里有你上一版的 order、lunch_after、gaps、verdict。\n- evidence.coverage_note 说明了路线只覆盖哪些 OD 对；没列出的段没有实测。\n\n【要做什么】\n1. 仍然只能使用 task 数据 + evidence。所有 kind=attraction 的景点都必须排进行程（不能删点、换点、加点）。order 只写第 1 天 candidates 里的景点，不要把 old_city 的老城景点写进 order（老城景点在第 2 天单独说明）。\n2. 可以改 order / lunch_after，但要先看 routes：如果改成没有证据的顺序，相关路段只能算\"未核实\"，status 不能是 complete。\n3. 逐项判定并写进 checks：\n   - opening：每个到访景点/餐馆有可用开放时段（静态字段、places.opentime_text、或 details.hours_text），且访问落在窗口内。\n   - route：起点→第1个点→…→起点 的每一段都有 routes 里的实测时长（或直线距离 ≤1.5km 可步行）。\n   - budget：所有候选的已知价格按人数计入 + 动态公交票价，且没有未知价格。\n   - weather：每个城市/日期都有预报。\n   - intercity：串联题为 ok/blocked，单城题为 na。\n4. status 四选一：complete = 以上全过；blocked = 仍有未知价格（任何候选）或到访景点缺开放时间；infeasible = 真实时长排不进截止时间 / 城际赶不上老城景点；partial = 字段不缺但路线/天气证据不全。注意本实验的交付门控：餐馆营业时间缺失、酒店坐标缺失只写进 unsolved，不改变 status。\n5. total_cost 用人民币、按题面人数；changes 写证据带来的实际改动；unsolved 写仍未解决项；evidence_used 写你实际用到的 req_id。\n6. answer 写一段中文最终答复：顺序、关键时段、费用、天气、依据（可带 req_id），以及仍要确认什么。blocked/partial 不能写成 complete。\n\n【输出】只输出一个 JSON 对象，写到这个文件：\n{OUT}\nUTF-8 编码，不要 markdown 代码围栏，不要额外的解释文字。结构如下（值换成这道题的）：\n{\n  \"uid\": \"E01\",\n  \"stage\": \"final\",\n  \"order\": [\"汉阳陵\", \"大明宫国家遗址公园\"],\n  \"lunch_after\": null,\n  \"status\": \"complete\",\n  \"end_time\": \"17:17\",\n  \"total_cost\": 290.0,\n  \"checks\": {\"opening\": \"ok\", \"route\": \"ok\", \"budget\": \"ok\", \"weather\": \"ok\", \"intercity\": \"na\"},\n  \"unsolved\": [],\n  \"changes\": [\"按真实公交 83 分钟替换了估计\"],\n  \"soft_handling\": [],\n  \"clarifications\": [],\n  \"evidence_used\": [\"E01-R-0\", \"E01-R-1\", \"E01-R-2\", \"E01-W-西安\"],\n  \"answer\": \"中文答复。\"\n}\n\n写完文件后，你的最终回复只写一行：{\"uid\":\"<本题uid>\",\"stage\":\"final\",\"ok\":true}。不要贴 JSON 内容。\n";

function promptFor(uid) {
  return TEMPLATE
      .split("{PACK}").join(`${base}/packs/${uid}_final.json`)
      .split("{STATIC}").join(`${base}/out/${uid}_static.json`)
      .split("{OUT}").join(`${base}/out/${uid}_final.json`)
      .split("{UID}").join(uid);
}

phase("final");
const results = [];
for (let i = 0; i < uids.length; i += chunkSize) {
  const group = uids.slice(i, i + chunkSize);
  const part = await parallel(group.map((uid) => async () => {
    const text = await agent(promptFor(uid), { label: `${uid} final`, phase: "final" });
    return { uid, ok: !!text, text: text || null };
  }));
  results.push(...part);
  log(`final ${Math.min(i + chunkSize, uids.length)}/${uids.length}`);
}
return {done: results.filter(r => r.ok).length, failed: results.filter(r => !r.ok).map(r => r.uid)};
