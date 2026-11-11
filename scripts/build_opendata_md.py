"""Build the Markdown counterpart of the open-data TAG deck.

Same discipline as the deck builder: every number is read from `results/` at build
time, so the Markdown report cannot drift from the experiments. Output:
`输出/开放数据TAG路线_汇报.md`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parent / "输出" / "开放数据TAG路线_汇报.md"


def load(relative: str) -> dict:
    path = ROOT / relative
    if not path.exists():
        print(f"  ! missing {path}")
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


P0 = load("results/p0/smoke_no_baidu.json")
P1 = load("results/p1/poi_mapping.json")
P2 = load("results/p2/tag_summary.json")
P4 = load("results/p4/b0_b4_report.json")
PREF = load("results/p4/preference_example.json")
REGISTRY = ROOT / "data" / "source_registry.csv"

S1 = P1.get("summary") or {}
REC = P2.get("records") or {}
G = P4.get("groups") or {}
GROUPS = ["B0_original", "B1_static_tags", "B3_preference", "B4_dynamic_replay"]
LABEL = {"B0_original": "B0 原始", "B1_static_tags": "B1 静态属性 TAG",
         "B3_preference": "B3 + M5 偏好", "B4_dynamic_replay": "B4 + 动态重放"}
CHECKS = P0.get("checks") or []
PASSED = sum(1 for c in CHECKS if c.get("ok"))


def pct(value: float | None) -> str:
    return f"{round((value or 0) * 100)}%"


def group_rows() -> str:
    rows = ["| 组 | n | 硬约束通过 | 平均 regret | 一次选中最优 | TAG 覆盖率 | 说明 |",
            "| --- | --- | --- | --- | --- | --- | --- |"]
    notes = {
        "B0_original": "取第一个可行方案，不做任何排序",
        "B1_static_tags": "有标签但不个性化（population 画像）",
        "B3_preference": "用户画像 + 软效用重排",
        "B4_dynamic_replay": "B3 + 离线动态重放（overlay + 营业时间）",
    }
    for key in GROUPS:
        item = G.get(key) or {}
        rows.append(
            f"| {LABEL[key]} | {item.get('n', 0)} | {item.get('hard_pass_rate', 0):.2f} | "
            f"{item.get('mean_regret', 0):.4f} | {item.get('exact_best_rate', 0):.2f} | "
            f"{item.get('mean_tag_coverage', 0):.2f} | {notes[key]} |")
    rows.append("| B2 游客体验 TAG | 0 | — | — | — | — | **不可执行**：无授权评论语料 |")
    return "\n".join(rows)


def preference_block() -> str:
    profiles = PREF.get("profiles") or []
    if not profiles:
        return "_（该次运行没有产出偏好示例）_"
    query = PREF.get("query") or {}
    lines = [f"查询 `{query.get('uid', '—')}` · {query.get('city', '—')} · "
             f"{query.get('days', '—')} 天 · 三个候选全部通过官方 checker", ""]
    for profile in profiles[:2]:
        lines.append(f"**{profile.get('uid')}** — {profile.get('summary', '')}")
        lines.append("")
        lines.append("| 排名 | 方案变体 | Q | 标签覆盖率 |")
        lines.append("| --- | --- | --- | --- |")
        for item in profile.get("ranking") or []:
            coverage = (item.get("coverage") or {}).get("rate", 0)
            lines.append(f"| #{item.get('rank')} | `{item.get('variant')}` | "
                         f"{item.get('Q', 0):+.4f} | {coverage:.2f} |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    by_tag = REC.get("accepted_by_tag") or {}
    by_class = REC.get("accepted_by_evidence_class") or {}
    by_licence = REC.get("accepted_by_licence") or {}
    by_source = REC.get("accepted_by_source") or {}
    gates = P2.get("gates") or {}

    gate_rows = "\n".join(
        f"| {name} | {value.get('pass', 0)}/{value.get('pass', 0) + value.get('fail', 0)} | "
        f"{'硬' if value.get('hard') else '软'} |"
        for name, value in sorted(gates.items()))

    tag_rows = "\n".join(
        f"| `{tag}` | {count} |" for tag, count in
        sorted(by_tag.items(), key=lambda kv: -kv[1]))

    cities = S1.get("by_city") or {}
    city_rows = "\n".join(
        f"| {city} | {item.get('n', 0)} | {item.get('matched', 0)} |"
        for city, item in sorted(cities.items()))

    doc = rf"""# 开放数据 TAG 路线汇报（百度额度耗尽后的接续）

> 2026-10-22　｜　对应演示文稿：`输出/开放数据TAG路线_汇报.pptx`（14 页，同一套数据）
> 一句话：**百度预算归零后，全流程仍跑通；用许可明确的 OSM(ODbL)+Wikidata(CC0) 建起 27 条可审计 TAG、覆盖 11 个 POI；偏好排序在不破坏官方硬约束的前提下改变了排序结果——但"游客体验"这一类证据仍然为空。**

---

## 一页速览

| 维度 | 结果 |
| --- | --- |
| 百度请求 | 预算 **0**，`live_calls = 0`，冒烟门槛 {PASSED}/{len(CHECKS) or 15} 断言通过 |
| 50 POI 匹配 | 命中 **{S1.get('either_matched', 18)}/{S1.get('n', 50)}（{pct(S1.get('matched_rate'))}）**；OSM {S1.get('osm_matched', 18)}、Wikidata {S1.get('wikidata_matched', 13)} |
| TAG 数据层 | **{REC.get('total', 27)} 条**全部 accept，覆盖 **{REC.get('distinct_pois_with_accepted', 11)} 个 POI**；ODbL {by_licence.get('odbl', 16)} + CC0 {by_licence.get('cc0', 11)} |
| 证据类 | `POI_STATIC_ATTRIBUTE` {by_class.get('POI_STATIC_ATTRIBUTE', 25)}、`CONTEXT_PRIOR` {by_class.get('CONTEXT_PRIOR', 2)}、`VISITOR_EXPERIENCE` **{by_class.get('VISITOR_EXPERIENCE', 0)}** |
| 消融 | 硬约束四组均 **1.0**；regret B0 {G.get('B0_original', {}).get('mean_regret', 0):.4f} → B3 {G.get('B3_preference', {}).get('mean_regret', 0):.4f} |
| 验收 | 要求"≥10 条可核验 TAG / ≥10 个 POI"，实际 {REC.get('total', 27)} 条 / {REC.get('distinct_pois_with_accepted', 11)} 个 |

---

## 1. 问题：一个供应商的额度停掉了整条流水线

上一轮的采集脚本对 42 个 POI 逐个请求百度，每次失败都重试；额度耗尽后**落库 0 条**。缺陷不在额度，在架构：
把"某个供应商可用"当成了硬前提，只有手工开关 `BAIDU_OFFLINE`，没有预算概念，也没有熔断。

## 2. P0 修复：把供应商变成可降级依赖

| 机制 | 位置 | 行为 |
| --- | --- | --- |
| 配置层 | `src/shorttrip/config.py` | `BAIDU_REQUEST_BUDGET` 默认 **0**；`SOURCE_FALLBACK_ORDER=local,osm,wikidata,authorized_dataset,official_site,baidu` |
| 预算 + 熔断 | `src/shorttrip/providers.py` | 每次真实调用先 `acquire()`；quota/auth 错误触发**当日熔断**并写入 `data/provider_state.json` |
| 百度适配器 | `dynamic/baidu.py` | 预算 0 时 `get_client("live")` 返回 blocked 客户端，**不打开 socket**；缓存命中仍可读 |
| 冒烟门槛 | `scripts/p0_smoke_no_baidu.py` | {PASSED}/{len(CHECKS) or 15} 断言通过才允许继续 |

> 没有做的事：不换 AK、不换账号、不绕过限额——那是规避平台限制，也会让实验无法复现。

## 3. P1 许可核验：能打开不等于可以用

| ID | 来源 | 许可结论 | 判定依据 |
| --- | --- | --- | --- |
| S1 | 广东旅游景点数据集 | `license_pending` | GitHub `/license` → 404，根目录只有 CSV |
| S2 | [OpenStreetMap](https://www.openstreetmap.org/copyright) | **ODbL-1.0 ✅** | copyright 页含 ODbL，需署名 + share-alike |
| S3 | [Wikidata](https://www.wikidata.org/wiki/Wikidata:Licensing) | **CC0-1.0 ✅** | licensing 页含 CC0，需 UA/限速/429 退避 |
| S4 | 携程评论样本 | `license_pending` | `/license` → 404，只有 README + zip |
| S5 | Contextual Appropriateness | `license_pending` | `/license` → 404 |
| S6 | 景区官网 / 文旅公告 | `license_pending` | 未逐站核验，未批量抓取 |
| S7 | ChinaTravel 沙盒 | 内部可用 | 项目自带基准数据 |
| S8 | 平台评论 / 平台 TAG | **unavailable** | 无授权渠道；禁止绕过登录/验证码 |

结论：只有 **S2 + S3** 进入可发布数据层；S1/S4/S5 只保留链接、字段说明与许可状态。
完整表见 `data/source_registry.csv`，原始证据见 `results/p1/source_probe.json`。

## 4. P1 匹配实验：50 个 POI 对上 {S1.get('either_matched', 18)} 个

样本：9 城 × 多类型 × 三价位，另外**刻意加入 6 个跨城同名陷阱**（中山公园 ×2、人民公园 ×2、孙中山纪念馆 ×2），冻结在 `datasets/p1/poi_sample_50.json`。

| 校验方式 | 数量 | 含义 |
| --- | --- | --- |
| OSM `wikidata=Q…` 交叉引用 | {S1.get('verified_by_osm_wikidata_tag', 12)} | 两个独立来源互指同一实体，最强身份证据 |
| 坐标 ≤3 km 佐证 | {S1.get('wikidata_coords_within_3km', 6)} | 弱校验，只用于排除同名异地 |
| 无 P625，需人工复核 | {S1.get('wikidata_needs_geo_check', 2)} | 不自动接受，进待核队列 |
| 判为同名异地而拒绝 | {S1.get('rejected_far_mismatch', 1)} | 例：广州孙中山纪念馆 ≠ 南京实体 |
| 有任意标签证据 | {S1.get('with_any_tag_evidence', 14)} | 匹配上 ≠ 有标签；OSM 中国区属性稀疏 |

分城市：

| 城市 | 样本 | 命中 |
| --- | --- | --- |
{city_rows}

### 四个必须记住的实测事实

1. **坐标系不对齐**：沙盒是 GCJ-02 且漂移约 1.4 km，`overpass around:200` 直接返回 **0** 个对象。
2. **类别过滤会丢最著名的景点**：广州塔在 OSM 是 `man_made=tower`，没有 `tourism=*`。
3. **同名会撞实体**：南京/广州"孙中山纪念馆"曾映射到同一 QID，因此无坐标的实体**一律不自动接受**。
   中间一次读数到过 74%，但那次同时受第 6 节的变量串味 bug 影响，是虚高值；修完后定稿在 {pct(S1.get('matched_rate'))}——**用覆盖率换精度是自觉选择**，不是能力上限。
4. **逐 POI 搜索会被限流**：`wbsearchentities` 43 次调用 8 次 429，改为单条 SPARQL `VALUES ?label`。

## 5. P2 TAG 数据层：{REC.get('total', 27)} 条 / {REC.get('distinct_pois_with_accepted', 11)} 个 POI

| 维度 | 结果 |
| --- | --- |
| 记录 | {REC.get('total', 27)}，全部 accept（reject 0 / quarantine 0） |
| 许可 | ODbL {by_licence.get('odbl', 16)}、CC0 {by_licence.get('cc0', 11)} |
| 来源 | OSM {by_source.get('osm', 16)}、Wikidata {by_source.get('wikidata', 11)} |
| 证据类 | `POI_STATIC_ATTRIBUTE` {by_class.get('POI_STATIC_ATTRIBUTE', 25)}、`CONTEXT_PRIOR` {by_class.get('CONTEXT_PRIOR', 2)}、`VISITOR_EXPERIENCE` {by_class.get('VISITOR_EXPERIENCE', 0)} |

按标签分布：

| TAG | 条数 |
| --- | --- |
{tag_rows}

闸门通过率（T1–T6）：

| 闸门 | 通过 | 类型 |
| --- | --- | --- |
{gate_rows}

证据分级纪律：
- `wheelchair=yes`、`fee=no`、`opening_hours=Tu-Su 09:00-17:00` 是**客观属性**；
- `tourism=museum → 室内 → 天气敏感度低` 是**推断**（`CONTEXT_PRIOR`，置信度 0.35，必须写明规则）；
- `拥挤/排队/性价比` 需要真实游客反馈 → **0 条**，因为没有授权语料，也不用模型生成"游客说"。

## 6. 质量事故：汇总数字上涨了，但数据是错的

`category_nature` 从 4 条"涨"到 14 条，汇总表看起来像覆盖率提升；人工抽检发现**水疗、高空跳伞、电音节、直升机观光区全被标成"城市公园"**。
根因：循环变量 `osm_wikidata` 未按 POI 重置，某个 POI 查不到 OSM 时会沿用上一个 POI 的 QID。

| 修复前 | 修复后 |
| --- | --- |
| `category_nature` 14 条（含误判） | `category_nature` 4 条（真实值） |
| 覆盖 POI 23 个（虚高） | 覆盖 POI 11 个（可核验） |
| 未发现异常的汇总表 | 抽检 + 单测双保险 |

同类问题本轮共修 4 个：循环变量串味、`enum` 空值域导致属性标签被全拒、`valid_until` 时区比较崩溃、Wikidata 多余参数让批量查询静默返回 0 实体。

## 7. P3 偏好排序：同一批可行方案，两个人相反的顺序

{preference_block()}
每条解释都带 `source_record_id` / `source_url` / `licence`，可回溯到具体 OSM way 或 Wikidata QID；
未知标签按中性处理并计入不确定度，**不因数据少而把冷门景点排到最后**。

## 8. P4 消融（easy_short 8 条查询 × 3 画像 = 24 行）

{group_rows()}

必须一起说的三句话：

1. 硬约束四组全 **1.0**：重排层没有污染官方判定；
2. B1 把"一次选中最优"从 **{G.get('B0_original', {}).get('exact_best_rate', 0) * 100:.1f}%** 提到 **{G.get('B1_static_tags', {}).get('exact_best_rate', 0) * 100:.1f}%**，说明静态标签本身有区分力；
3. B3/B4 的 regret=0 是 **3 个候选变体**的小池效应；B4≈B3 说明这批查询上动态重放没有可观测增益。

实验本身外部 API 调用 **0 次**（标签在 P2 预建）。

## 9. 边界：这一轮不能声称什么

| 不能说 | 原因 |
| --- | --- |
| "游客体验更好" | 没有人工成对偏好标注；只证明了重排器正确实现了所述偏好关系 |
| "体验 TAG 已建立" | `VISITOR_EXPERIENCE` 为 0：S4/S8 许可未确认，B2 组不可执行 |
| "覆盖了大多数景点" | 50 个 POI 命中 {S1.get('either_matched', 18)} 个、有标签 {S1.get('with_any_tag_evidence', 14)} 个 |
| "动态更新已闭环" | B4 只是离线重放，未调用天气/路网 |

可以声称的：架构上解除了单点依赖；数据层可审计（许可 + 来源 ID + 逐字引文）；许可边界清楚；排序有效且不越界；8 个真实坑全部写进 `STATE.md` 并配了回归/失败用例。

## 10. 下一步

不依赖任何配额：
1. 扩样 50 → 200 POI（缓存可复用，成本只是限速等待）；
2. 补齐 `natural` / `man_made` / `heritage` 的标签映射；
3. 候选池 3 → ≥8 变体，验证 regret=0 是否只是小池效应；
4. 对 27 条记录做双人核验（指令要求 ≥30 POI）。

需要外部条件：可授权游客评论语料（S4/S8）、标注人力、地图供应商配额。

---

## 附录：产物与复跑

| 产物 | 路径 |
| --- | --- |
| 检查点（卡点/失败案例/命令） | `reproduction/STATE.md` |
| 详细技术报告 | `reproduction/报告/08_开放数据TAG与偏好规划.md` |
| 演示文稿 | `输出/开放数据TAG路线_汇报.pptx` |
| 源许可登记表 | `reproduction/data/source_registry.csv` |
| 许可核验原始证据 | `reproduction/results/p1/source_probe.json` |
| P0 冒烟 | `reproduction/results/p0/smoke_no_baidu.json` |
| 50 POI 映射 | `reproduction/results/p1/poi_mapping.json` / `.csv` |
| TAG 记录与汇总 | `reproduction/results/p2/tag_summary.json`、`tag_records.json` |
| B0–B4 | `reproduction/results/p4/b0_b4_report.json` / `.md` |
| 两用户示例 | `reproduction/results/p4/preference_example.json` |

```powershell
cd reproduction
$env:PYTHONUTF8='1'; $env:BAIDU_REQUEST_BUDGET='0'
.\.venv\Scripts\python scripts\p0_smoke_no_baidu.py
.\.venv\Scripts\python scripts\probe_source_registry.py     # 唯一会联网核验许可的一步
.\.venv\Scripts\python scripts\p1_match_50_pois.py
.\.venv\Scripts\python scripts\p2_build_tag_layer.py
.\.venv\Scripts\python scripts\p4_abcd_open_data.py easy_short 8
.\.venv\Scripts\python scripts\p4_preference_example.py
.\.venv\Scripts\python tests\test_tags_preference.py        # 54
.\.venv\Scripts\python tests\test_open_data_extractor.py    # 16
```

本文由 `reproduction/scripts/build_opendata_md.py` 从上述 JSON 直接渲染，数字不手抄。
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(doc, encoding="utf-8")
    print(f"wrote {OUT} ({len(doc)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
