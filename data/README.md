# `data/` 数据说明书

| 目录 | 内容 | 大小 | 许可/说明 |
|---|---|---:|---|
| `catalog_v1_1_20261022/` | 扩展 10 城 catalog（SQLite `records` 表） | 193 MB → gz **14.5 MB** | 研究复现用；逐字段带来源/证据/TAG |
| `xian11_merged_sandbox/` | 第 11 城西安（v17 + 评级标准 v1） | 5.4 MB | 同；price 有已知缺口 |
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

## 西安 v17 的已知缺口

| 类型 | price 覆盖 | 备注 |
|---|---:|---|
| 景点 | 112/908 = **12.3%** | 无公开票价源，补价脚本不覆盖 |
| 餐厅 | 561/807 = **69.5%** | 已尽力补 |
| 住宿 | 375/929 = **40.4%** | 房型/动态价另见 `docs/hotel_roomtype_dynamic_price.md` |

预算类约束会受这些缺口影响，报告必须披露，不能用「缺价 = 免费」解释。
