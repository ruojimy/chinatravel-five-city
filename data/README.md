# `data/` 数据说明书

| 目录 | 内容 | 大小 | 许可/说明 |
|---|---|---:|---|
| `catalog_v1_1_20261022/` | 扩展 10 城 catalog（SQLite `records` 表） | 193 MB → gz **14.5 MB** | 研究复现用；逐字段带来源/证据/TAG |
| `xian11_merged_sandbox/` | 第 11 城西安（v17 + 评级标准 v1） | 5.4 MB | price 有已知缺口；见下文语义 |
| `query_sets/` | 原生 easy/medium/human、xian11、competition_test | 2.2 MB | 官方部分 CC BY 4.0 |
| `datasets/` | 偏好、POI 匹配金标、不可行/修复样本 | 1.8 MB | 项目衍生 |

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
| `source_value` | 240 | 观测价 | 有 `hotel_price_observations` 记录 |
| `estimated` | 78 | **区间中点 mid** | 只采纳 `confidence=high`；区间在 `price_provenance.csv` |
- price_estimates_supplement.csv：388 家 unknown 中 253 家可算出 n>=8 的同类邻店区间（另 32 家 medium、7 家 low、96 家无可比），**仅供排序/参考，未写入主表**；方法见 docs/hotel_roomtype_dynamic_price.md。
| `unknown` | 388 | `-1` | 待动态询价；清单在 `dynamic_price_queue.csv` |

- `price_provenance.csv`：`price_low / price_high / price_mid / confidence / n_comparables / method`，估价区间可被程序读取。
- price_estimates_supplement.csv：388 家 unknown 中 253 家可算出 n>=8 的同类邻店区间（另 32 家 medium、7 家 low、96 家无可比），**仅供排序/参考，未写入主表**；方法见 docs/hotel_roomtype_dynamic_price.md。
- `-1` 不是 0 或空：ChinaTravel loader 会 `pd.read_csv(...).dropna()`，空值会丢行，所以用哨兵 + 状态列表达“未知”。
- 计划/报告里 `estimated` 必须写成“预估 ¥low–¥high”，不能当实价；`unknown` 必须先询价。
- 动态询价：`scripts/hotel_dynamic_price.py {provenance,price,batch}`，默认快照 v17。

## 西安 v17 的 price 缺口（全量口径）

| 类型 | price 覆盖 | 备注 |
|---|---:|---|
| 景点 | 112/908 = **12.3%** | 无公开票价源，补价脚本不覆盖 |
| 餐厅 | 561/807 = **69.5%** | 已尽力补 |
| 住宿 | 345/761 = **45.3%** | 267 观测 + 78 估价；主路径 318/706 |

预算类约束会受这些缺口影响，报告必须披露，不能用「缺价 = 免费」解释。

## 西安餐厅 price（2026-11-11）

餐厅 schema 是 cost = price × people_number，所以 price 就是**人均**，高德 usiness.cost 同口径。
用 20 家已有价餐厅校验：17 家有高德 cost，17/17 偏差 ≤30%，比值中位 1.00。
据此补齐 34 条 -1 中的 16 条，覆盖率 **452 → 468 / 486（96.3%）**；剩余 18 条多为非餐饮 POI（便利店、创业园、零售等），
高德无 cost，保留 -1。补齐记录：
estaurants/xian/restaurant_price_provenance.csv（source=amap_v5_place_text）。

酒店不同：price 是每间/晚，代码 cost = price × required_rooms，人均不是同一单位，不能直接套用。

