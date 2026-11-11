# 酒店房型子表与动态询价（西安 / ChinaTravel 对齐方案）

## 为什么主表只保留一种房型

ChinaTravel 原生 `accommodations/<city>/accommodations.csv` 的列是：

```
id, name, hotelname_en, featurehoteltype, lat, lon, price, numbed
```

`price` 与 `numbed` 都是**单个值**，没有房型维度。为了让西安沙盒与官方 loader / checker 对齐，主表必须只保留一种房型，不能把 8 种房型摊成 8 行（会重复酒店身份、破坏 `Is_hotels_correct` 的唯一性与价格校验）。

因此约定：

- **主表**：`price` = 该酒店观测到的起步价；`numbed` = **主房型**床位数。
- **主房型选择规则**（可审计、不猜）：
  1. 统计页面里所有房型的床位数；
  2. 取出现次数最多的床位数（众数）；
  3. 众数不唯一（例如大床/双床各 4 种）→ `numbed` 留空，不猜；
  4. 众数唯一时，在所有该床数的房型里取面积最小的一间作为 `is_primary=1`。
- **子表**：`room_types` 保存全部房型（名称、床型文本、床数、面积、窗户、是否主房型、来源 URL、raw 路径、观测时间）。

## 子表结构

catalog snapshot 内新增两张表：

```sql
room_types(
  hotel_name, room_id, room_name, bed_text, bed_count, area, window,
  is_primary, source_url, raw_path, observed_at, hotel_id,
  primary key (hotel_name, room_id)
)

hotel_price_observations(
  hotel_name, price, observed_at, source_url, raw_path, basis
)
```

`room_types` 是“用户敲定酒店后再查”的明细；`hotel_price_observations` 用来做价格区间与陈旧度判断。

## 规划时的调用顺序

1. **候选阶段**：只用主表。按位置、预算档、`featurehoteltype` 筛出 3–5 家。
2. **用户敲定酒店**：拿到 `hotel_name`。
3. **查房型子表**：
   ```
   python scripts/hotel_dynamic_price.py rooms --hotel "西安威斯汀大酒店"
   ```
   返回全部房型；让用户选大床/双床/家庭房，而不是让模型替用户决定。
4. **动态询价**（入住/退房日期确定后）：
   ```
   python scripts/hotel_dynamic_price.py price --hotel "西安威斯汀大酒店" \
       --checkin 2026-11-10 --checkout 2026-11-11
   ```
   返回 `price`、`observed_at`、`band`（历史 min/max/n）与来源。
5. **写计划**：主表 activity 的 `price` 用本次询价；`cost = price * rooms`；`room_type` 用选中的房型名。

## 动态询价的语义

- 价格 TTL 短是事实，但**浮动区间通常不大**：返回 `band` 而不是假装精确。
- 询价失败时返回 `status=unknown` + `last`（上次观测与年龄），计划里应保留“待定/需确认”，不得填一个编造值。
- 同一天同一酒店重复询价走缓存：`data/hotel_price_cache.jsonl`，默认 24h 内复用。
- 价格是“起步价/最低可售房型”，不是用户选中房型的价格；若子表房型与最低价房型不一致，应在计划里注明“价格为该酒店起步价，选中房型可能更高”。

## 预估价格与默认床数（v7 修正策略）

用户口径（2026-11-09）：**有具体数值就用具体数值；实在找不到才给预估范围；numbed 取 1 或 2 即可。**

- **观测价优先**：74 家已有 `status=source_value` 的真实价格，一律不覆盖。
- **估价必须先搜过**：只有已抓到该酒店 Trip.com 详情页、页面确实没有价格的 **9 家**，才允许估价；每条估价必须带 `attempt_ref`（run_log 路径 + hotel_id）。
- **未搜过不估**：554 家未抓取、88 家携程无同名的酒店，`price` 保持空值，继续换源搜索；不得用最近邻“补”出一个数。
- **估价方法**：按档次（luxury / mid / budget）取 8km 内同类酒店的 p25–p75，主表存中位数；区间写入 `hotel_price_estimates(hotel_name, hotel_class, low, high, mid, n_comparables, method, confidence, attempt_ref)`。
- **床数默认**：27 家已有观测/主房型床数；其余 734 家默认 `numbed=1`，provenance 标 `status=estimated`、`basis=default_single_bed`。这是容量假设，不是事实断言；用户选定酒店后可改。
- **展示规则**：`status=estimated` 的酒店，规划里必须写成“预估 ¥low–¥high”，不能写成确定房价；用户给定日期后调用动态询价替换。
- **质量语义**：estimated 字段不是 `source_value`，不参与 A 类的“原文可复核”计数；A 类不因估价增加。

## 覆盖现状与限制

- 主表 `price`（merged 主路径 **706** 家）：**318 / 706（45.0%）** = **240 条来源观测** + **78 条采纳的高置信估价**；其余 388 家写 `-1` 占位（`price_status=unknown`），不估价。
- 主表 `numbed`：**706 / 706**。
- 搜索覆盖：Trip.com 693 家；携程 UI 39 次（0 命中）；美团 UI 90 次/账号，3 个账号各 90 次后限流，累计 360 次查询、58 命中。
- `room_types`：**308 家 / 2243 个房型**，多床型酒店可查子表。
- 合并集主路径：**706 家**（`ready` 318 / `l1_only` 388），`reference_only` 55 家（全部缺坐标）。
- 采纳规则 2026-11-10 v1：**只采纳 `confidence=high` 的估价（78 家）**；medium/low 一律 `price=None`、`status=unknown`、`basis=estimate_not_adopted`。
  - 准入口径 2026-11-10 调整：`featurehoteltype` 允许留空，不再阻断 planner；仅 `lat`/`lon` 为硬门槛。
  - 主路径价格构成：真实 240 家、采纳的估价 78 家、需询价 388 家。
- 估价区间校准（留一法，holdout 240 家真实价酒店）：

  | 指标 | 原区间 p25–p75 | 低置信放宽 ×0.75–1.25 |
  |---|---:|---:|
  | 真实价落入区间 | **44.6%** | **67.1%** |
  | 中位相对误差 | 33.7% | — |
  | P90 相对误差 | 115.6% | — |

  分价格段覆盖率（原区间 / 放宽）：≤¥100 46.6%/64.7%、¥101–200 53.0%/81.9%、¥201–400 24.1%/48.3%、>¥400 16.7%/33.3%；luxury 22.2%/44.4%。
  结论：**这是同类邻店的经验分布，不是该酒店的真实报价区间**，只能做量级参考与排序，不能当报价展示。

## 2026-11-11 修复：表里到底存了什么

| 问题 | 答案 |
|---|---|
| 高置信区间估价的**主表**里填的是区间还是估价？ | 填的是**区间中点 `mid`**（单一数值），不是区间。78 条全部核对为 `price == mid`。 |
| 有标注它不是来源明确的 price 吗？ | **修复前没有**：CSV 只有 8 列，估价和观测价长得一样。现在新增 `price_status ∈ {source_value, estimated, unknown}`，每行都有值（loader 会 `dropna()`，不能留空）。 |
| 区间还能访问吗？ | **能**：`accommodations/xian/price_provenance.csv` 保存 `price_low / price_high / price_mid / confidence / n_comparables / method`；`scripts/hotel_dynamic_price.py provenance --hotel "<name>"` 直接返回。 |

约定：

- `estimated` 行的 `price` = `mid`；报告/计划里必须写成“预估 ¥low–¥high”，不能当实价。
- `unknown` 行的 `price` = **`-1` 哨兵值**（不是 0，也不是空），避免 `pd.read_csv(...).dropna()` 丢行；语义由 `price_status=unknown` 表达。
- `dynamic_price_queue.csv` 列出 388 家待询价酒店，可直接批跑：

```bash
python scripts/hotel_dynamic_price.py batch --queue data/xian11_merged_sandbox/accommodations/xian/dynamic_price_queue.csv \
    --checkin 2026-11-20 --checkout 2026-11-21 --limit 20
```

- 工具默认快照已从 `snapshot_v7` 切到 `snapshot_v17`（可用 `SHORTTRIP_HOTEL_SNAPSHOT` 覆盖）。

## 不做什么

- 不把多房型写成多行主表记录。
- 不用星级/营销文案冒充房价（`priceRange` 里没有具体金额的，记为 unknown）。
- 不在页面只有繁体店名、与 catalog 简体名无法逐字对齐时，把价格写进主表（会触发 `name_not_in_raw` 硬失败）；这类酒店只进子表，主表价格留空。
