# `data/` 数据说明书

| 目录 | 内容 | 大小 | 许可/说明 |
|---|---|---:|---|
| `catalog_v1_1_20261022/` | 扩展 10 城 catalog（SQLite `records` 表） | 193 MB → gz **14.5 MB** | 研究复现用；逐字段带来源/证据/TAG |
| `xian11_merged_sandbox/` | 第 11 城西安（v17 + 评级标准 v1） | 5.4 MB | price 有已知缺口；见下文语义 |
| `query_sets/` | 原生 easy/medium/human、xian11、competition_test | 2.2 MB | 官方部分 CC BY 4.0 |
| `datasets/` | 偏好、POI 匹配金标、不可行/修复样本 | 1.8 MB | 项目衍生 |
| `business_catalog_v1_7/` | 30 城业务库：14,057 实体 + 42,576 TAG + 5,187 证据 | 188 MB → gz **22.4 MB** | `full_completion=false`；见目录内 README |
| `xian11_merged_v17_tags/` | v17 快照 TAG 层导出（7,173 行 / 68 种 / 2,371 实体） | 0.45 MB | 派生提示 ≠ 来源事实 |
| `tag_store/` | TAG 层原型库 v1/v2（`tags` + `snapshots`，T1–T6 六闸） | 0.24 MB | OSM ODbL / Wikidata CC0 / Zenodo CC BY 4.0 |
| `airport_aliases.json` | 机场别名 → IATA 三字码（102 条） | 9.6 KB | `scripts/normalize_airports.py` 依赖 |
| `travel_source_registry.json` | 来源权威性 / 许可 / 独立性登记 | 3.8 KB | 分级与证据门用到 |

## catalog 的还原

仓库只放 gzip，避免 193 MB 二进制进 Git。还原后可用任意 SQLite 客户端打开：

```bash
python - <<'PY'
import gzip, shutil
with gzip.open("data/catalog_v1_1_20261022/catalog.sqlite3.gz","rb") as s, \
     open("data/catalog_v1_1_20261022/catalog.sqlite3","wb") as d:
    shutil.copyfileobj(s,d)
PY
```

`SHA256SUMS` 同时给出 gz 与解压后 sqlite 的哈希；`prepare_shorttrip_runs.py` 会自动还原。

## 表结构（catalog.sqlite3）

- `records(id, city, kind, payload, ...)`：`payload` 是 JSON，含 `data{...}`、来源、抓取时间、字段级证据。
- `kind ∈ {attraction, restaurant, accommodation, poi, subway, train, flight}`。
- 导出到 ShortTrip 时只映射景点/餐厅/住宿三类，见 `scripts/prepare_shorttrip_runs.py::export_extended_10`。

## 西安位置索引（2026-11-11 重建）

`xian11_merged_sandbox/poi/xian/poi.json` 原来只有 1,394 条，景点/酒店/餐厅大量取不到坐标。
已用三张实体表 `name + lat/lon` 重建，并补入地铁站、站名短别名和英文后缀别名：

| 实体 | 数量 | 重建前精确命中 | 重建后 |
|---|---:|---:|---:|
| 景点 | 591 | 68（11.5%） | **591（100%）** |
| 酒店 | 706 | 15（2.1%） | **706（100%）** |
| 餐厅 | 486 | 23（4.7%） | **486（100%）** |
| POI 总条数 | — | 1,394 | **4,571** |

- 重建脚本：`scripts/rebuild_xian_poi_index.py`（幂等，始终从 `poi.json.bak_20261111` 重建）。
- 明细：`poi_index_manifest.json`（新增、替换坐标、被跳过的歧义别名）。
- 实体表原值未改；英文后缀通过别名覆盖，`Poi.search` 对原值和新别名都能命中。

## 西安酒店 price 的三种状态

主表 `accommodations/xian/accommodations.csv` 每行只有一个数：观测价、或**估价区间的中点 mid**、或 `-1` 哨兵。
2026-11-11 起新增 `price_status` 列区分，语义如下：

| status | 条数 | 表里的 price | 说明 |
|---|---:|---|---|
| `source_value` | 254 | 观测价（含 14 条 Trip.com 恢复） | 有观测/详情页证据 |
| `estimated` | 78 | **区间中点 mid** | 只采纳 `confidence=high`；区间在 `price_provenance.csv` |
| `estimated_chain_branch` | 6 | 同城同品牌分店中位数 | 布丁/易休/OYO/尚客优 |
| `estimated_chain_cross_city` | 14 | 跨城同品牌中位数（按城市中位数归一） | 如家/汉庭/宜必思/星程/都市118/锦江之星 |
| `estimated_hostel_comparable` | 2 | 青旅同类中位数 | 木木夕/梦想家 |
| `unknown` | 352 | `-1` | 待动态询价；清单在 `dynamic_price_queue.csv` |

- `price_provenance.csv`：`price_low / price_high / price_mid / confidence / n_comparables / method`，估价区间可被程序读取。
- `price_estimates_supplement.csv`：352 家 unknown 中 241 家可算出 n>=8 的同类邻店区间（另 14 家 medium、4 家 low、93 家无可比），**仅供排序/参考，未写入主表**；方法见 `docs/hotel_roomtype_dynamic_price.md`。
- `-1` 不是 0 或空：ChinaTravel loader 会 `pd.read_csv(...).dropna()`，空值会丢行，所以用哨兵 + 状态列表达“未知”。
- 计划/报告里 `estimated` 必须写成“预估 ¥low–¥high”，不能当实价；`unknown` 必须先询价。
- 动态询价：`scripts/hotel_dynamic_price.py {provenance,price,batch}`，默认快照 v17。

## 西安 v17 的 price 缺口（全量口径）

| 类型 | price 覆盖 | 备注 |
|---|---:|---|
| 景点 | 112/908 = **12.3%** | 无公开票价源，补价脚本不覆盖 |
| 餐厅 | 561/807 = **69.5%** | 已尽力补 |
| 住宿 | 345/761 = **45.3%** | v17 全量；主路径 **354/706** |

预算类约束会受这些缺口影响，报告必须披露，不能用「缺价 = 免费」解释。

## 西安餐厅 price（2026-11-11）

餐厅 schema 是 cost = price × people_number，所以 price 就是**人均**，高德 usiness.cost 同口径。
用 20 家已有价餐厅校验：17 家有高德 cost，17/17 偏差 ≤30%，比值中位 1.00。
据此补齐 34 条 -1 中的 16 条，覆盖率 **452 → 468 / 486（96.3%）**；剩余 18 条多为非餐饮 POI（便利店、创业园、零售等），
高德无 cost，保留 -1。补齐记录：
estaurants/xian/restaurant_price_provenance.csv（source=amap_v5_place_text）。

酒店不同：price 是每间/晚，代码 cost = price × required_rooms，人均不是同一单位，不能直接套用。

