// Auto-exported from results/p32_llm_96/prompts/static.txt — run with the harness workflow tool.

const base = "C:/Users/xiech/Downloads/计算机软件工程概论/reproduction/results/p32_llm_96";
const uids = args.uids || (() => {
  const out = [];
  for (const p of ["E", "D", "N"]) for (let i = 1; i <= 32; i++) out.push(p + String(i).padStart(2, "0"));
  return out;
})();
const chunkSize = 6;

const TEMPLATE = "【角色】你是被测的旅行规划 LLM，参加一个离线、冻结数据的评测。严格按下面的规则做题，不要自由发挥。\n\n【硬性禁止】\n- 不联网、不调用任何 API、不运行项目里的 planner / checker / 评分脚本。\n- 只读这一个输入文件：{PACK}\n- 不要读工作区里的其它文件，尤其不要读 results/p31_five_city_96/ 下的 final、evaluation、summary。\n- 不用常识补数据：task 里没有写出的价格、营业时间、路线时长一律视为未知，不能猜、不能写成 0。\n\n【输入文件里有什么】\n- schema / note / task。\n- task 含：nature_language（自然语言需求）、people_number、city_sequence、dates、start（起点坐标）、candidates（候选实体：data、tags、missing_fields）、constraints（window、start_time、budget、soft、overnight/chain）、static_estimate、retrieval_budget。\n- kind=attraction / restaurant / accommodation / train / flight。串联题还有 intercity（给定车次或航班）与 old_city（老城景点）。\n\n【要做什么】\n1. 只使用 task 数据。所有 kind=attraction 的景点都必须排进行程（用户点名要去，不能删点、换点、加点）。有 restaurant 就安排一顿午饭。串联题：第 1 天在新城看 candidates 里的景点、住给定酒店；第 2 天坐给定车次/航班去老城看 old_city.attraction。单城题忽略酒店/城际。\n2. 输出景点访问顺序 order（必须用候选的 name 原文，逐字一致）和午饭插入位置 lunch_after（0 到 len(order) 的整数；null 表示没有午饭）。例如 order=[A,B,C]、lunch_after=1 表示 A → 午饭 → B → C。\n3. 时间只能估算：市内移动 = 两点直线距离 / 18km/h + 8 分钟换乘（最少 12 分钟）；景点停留 = recommendmintime×60 分钟（缺失用 90），夹在 45–240 分钟；午饭 60 分钟，11:00 前到要等到 11:00。估算不是证据。\n4. 找\"必需字段\"缺口（本阶段核心）。必需字段：景点 price / opentime / endtime / lat / lon；餐馆 price / opentime / endtime；酒店 price / lat / lon；车次/航班 From / To / BeginTime / EndTime / Duration / Cost；old_city 景点 price / opentime / endtime。recommendmintime、recommendmaxtime、hotelname_en、numbed、recommendedfood 等是可选项，不是阻断缺口。candidates 的 missing_fields 可能混有可选项，要自己筛。gaps 只写实体字段缺口；天气和路线证据不属于本阶段缺口，写在 clarifications 里。\n5. verdict 三选一：ok = 必需字段齐全、按估算能排进 window、预算内（此时只差路线/天气等动态证据）；blocked = 缺必需字段；infeasible = 按估算也排不进 window（或串联题城际赶不上老城景点）。\n6. 预算：已知价格按人数计入（门票×人数、午饭×人数、酒店×1、城际×人数）；known_cost 只写这些已知价格之和，不要把市内交通估算混进去（交通估算单独在 answer 说明）。未知价格不能当 0。budget_limit 用 static_estimate.budget_limit。\n7. constraints.soft 里的偏好（elderly、slow_pace、half_day、rain_backup、efficient）要体现在安排和答复里，不要忽略。\n8. answer 写一段中文答复：顺序、时段、费用、还缺什么/要查什么。不要说\"已完成/已核实\"。\n\n【输出】只输出一个 JSON 对象，写到这个文件：\n{OUT}\nUTF-8 编码，不要 markdown 代码围栏，不要额外的解释文字。结构如下（值换成这道题的）：\n{\n  \"uid\": \"E01\",\n  \"stage\": \"static\",\n  \"order\": [\"汉阳陵\", \"大明宫国家遗址公园\"],\n  \"lunch_after\": null,\n  \"end_time\": \"17:20\",\n  \"known_cost\": 260.0,\n  \"budget_limit\": 380.0,\n  \"budget_items\": [\n    {\"entity\": \"汉阳陵\", \"amount\": 140.0},\n    {\"entity\": \"大明宫国家遗址公园\", \"amount\": 120.0}\n  ],\n  \"gaps\": [\n    {\"entity\": \"栈桥\", \"field\": \"opentime\", \"why\": \"候选没有营业时间\", \"check\": \"查高德 POI 详情或官网\"}\n  ],\n  \"soft_handling\": [{\"soft\": \"elderly\", \"how\": \"减少步行，每段留休息\"}],\n  \"clarifications\": [],\n  \"verdict\": \"ok\",\n  \"answer\": \"中文答复。\"\n}\n\n写完文件后，你的最终回复只写一行：{\"uid\":\"<本题uid>\",\"stage\":\"static\",\"ok\":true}。不要贴 JSON 内容。\n";

function promptFor(uid) {
  return TEMPLATE
      .split("{PACK}").join(`${base}/packs/${uid}_static.json`)
      .split("{OUT}").join(`${base}/out/${uid}_static.json`)
      .split("{UID}").join(uid);
}

phase("static");
const results = [];
for (let i = 0; i < uids.length; i += chunkSize) {
  const group = uids.slice(i, i + chunkSize);
  const part = await parallel(group.map((uid) => async () => {
    const text = await agent(promptFor(uid), { label: `${uid} static`, phase: "static" });
    return { uid, ok: !!text, text: text || null };
  }));
  results.push(...part);
  log(`static ${Math.min(i + chunkSize, uids.length)}/${uids.length}`);
}
return {done: results.filter(r => r.ok).length, failed: results.filter(r => !r.ok).map(r => r.uid)};
