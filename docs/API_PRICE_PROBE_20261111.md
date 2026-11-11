# 高德 / 百度能不能给酒店“区间价”？实测（2026-11-11）

结论先说：**不能。** 两家只返回**单个参考值**（甚至通常为空），语义是“人均消费/参考价”，
不是房费，更没有日期维度或区间；名字匹配还会命中酒店内的餐厅/SPA 子场馆，价格会严重误导。

## 1. 实测口径

- 环境：`restapi.amap.com` / `api.map.baidu.com` 直连（HTTP 200，status 正常）。
- 样本：西安 29 家有观测房价的酒店（luxury/mid/budget 分层）+ 10 家餐厅（正对照）+ 高德“酒店”类型检索 25 家；百度 6 家酒店。
- 结果文件：`results/api_hotel_price_probe_20261111.json`、`results/api_hotel_price_bulk_20261111.json`。

## 2. 结果

| 来源 | 对象 | 样本 | 有价格字段 | 是区间 | 说明 |
|---|---|---:|---:|---:|---|
| 高德 v5/v3 place/text | 酒店 | 29 | **1** | 0 | 唯一命中是“希尔顿酒店-自助餐厅”，`cost=132`，是自助餐人均 |
| 高德 place/text | 餐厅 | 10 | **10** | 0 | `cost` 26–62 元，标准“人均消费” |
| 高德 types=100000 酒店检索 | 酒店 | 25 | **0** | 0 | 整页 25 家酒店没有任何 `cost` |
| 百度 place/v2 search+detail | 酒店 | 6 | **2** | 0 | 命中“W酒店·AWAY SPA”872.1、“华邑酒店·举茗邑”45.9，都是子场馆 |

对照真实房价：

| 酒店 | 观测房价 | 百度返回 | 命中对象 |
|---|---:|---:|---|
| 西安W酒店 | 1,116 | 872.1 | 西安W酒店·AWAY SPA |
| 西安唐华华邑酒店 | 829 | 45.9 | 西安浐灞华邑酒店·举茗邑（茶室） |
| 西安威斯汀大酒店 | 776 | 空 | — |
| 金鑫宾馆(西安钟楼店) | 84 | 空 | — |

## 3. 字段语义

- 高德 `business.cost` / `biz_ext.cost`：POI 的“人均消费”。餐厅/景点常有值；酒店基本为空；即使有值也可能是酒店内餐厅。
- 百度 `detail_info.price`：同样是参考/人均价，格式是单个字符串（缓存 fixture 里景点为 `"30.0"`、`"230.0"`），**从未出现 `100-300` 这种区间**。
- 两家都没有“入住日期 + 房型”参数，也没有房价区间字段；高德 Web 服务不提供酒店预订价，百度 LBS 同样不提供。

## 4. 对数据管线的影响

1. **不能用它们补酒店房价或区间**；`price_status` 仍应保持 `unknown`，走 OTA 动态询价。
2. 若把百度/高德的 `price` 写入酒店，最大的风险不是“没有”，而是**错配到子场馆**（SPA、餐厅、茶室），
   例如 W 酒店会得到 872 而不是 1,116，华邑会得到 45.9 而不是 829。
3. 两家可用的字段是：名称/地址/坐标/评分/营业时间/电话/标签——用于**身份核验与排序**，不用于报价。

## 5. 获取区间价的可行路径

| 路径 | 能否给区间 | 说明 |
|---|---|---|
| Trip.com / 携程详情页（`hotel_dynamic_price.py`） | ✅ | 指定 checkin/checkout 抓 `minPrice`；多次观测可形成 band |
| 多次实时询价 | ✅ | 同一酒店不同日期/房型 → `[min,max]` + 观测时间 |
| 同类邻店估计（`xian_estimate_fill.py`） | ⚠️ | p25–p75，留出覆盖率约 44%；`mid±60%` 约 74–79%，只能标注为 estimate |
| 高德 / 百度 | ❌ | 无房费、无区间、子场馆误配风险 |

## 6. 修正：餐厅人均可以直接当 `price`，酒店不行

餐厅的 schema 是 `cost = price × people_number`（`nesy_agent.py:424/464`），所以 `price` 就是**人均**；
高德 `business.cost` 正好是同一口径，可以直接用。实测校验（20 家已有价餐厅）：

| 指标 | 结果 |
|---|---|
| 高德返回 `cost` | 17 / 20 |
| 与现有价偏差 ≤30% | **17 / 17** |
| 比值中位数 / p10 / p90 | **1.00 / 1.00 / 1.00** |

据此把西安餐厅表 34 条 `-1` 中的 **16 条**用高德人均补齐，覆盖率 **452 → 468 / 486（96.3%）**；
剩余 18 条里多数不是餐饮 POI（便利店、创业园、鲜花港、教育学院、二手设备、腊牛羊肉零售），
高德本身没有 `cost`，继续保留 `-1`。补齐记录在 `restaurant_price_provenance.csv`（source=amap_v5_place_text）。

酒店则不同：prompt 明确“price per night per room”，代码是 `cost = price × required_rooms`（`nesy_agent.py:362`），
所以 `price` 是**每间/每晚**。高德/百度给的是**人均**，而且经常命中酒店内的餐厅/SPA：
W 酒店 SPA 872.1 vs 房费 1,116、华邑茶室 45.9 vs 房费 829。两者不是同一单位，不能直接当酒店 `price`。

## 7. 结论（按实体分开）

| 实体 | 高德/百度人均能否当 `price` | 原因 |
|---|---|---|
| 餐厅 | ✅ 可以 | schema 的 price 就是人均；17/17 校验一致 |
| 酒店 | ❌ 不可以 | schema 的 price 是每间/晚；人均是另一个单位，且常命中子场馆 |

复现：

```bash
python scripts/probe_hotel_price_apis.py        # 3 家酒店，高德 v5/v3 + 百度 search/detail
python scripts/probe_amap_hotel_price_bulk.py   # 29 酒店 + 10 餐厅 + 6 百度酒店
python scripts/fill_restaurant_price_from_amap.py --validate 20
python scripts/fill_restaurant_price_from_amap.py --apply
```

> 凭证只从 `.secrets/amap.key`、`.secrets/baidu.key` 读取；本文与结果文件均未记录 key。
