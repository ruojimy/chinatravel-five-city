# 从 Trip.com 恢复 14 家酒店的房价（2026-11-11）

## 1. 为什么 388 家 `-1` 里其实有价

早期补价线已经抓过 693 家 Trip.com 详情页，但合并规则要求“同名 + 坐标距离 ≤300 m”。
其中 13 家的缓存距离是 **492–600 m**，被当成“不是同一家”拒掉了。复核后发现：

- 名称完全一致（含分店后缀）；
- URL 是同一 `hotel-detail-<id>`；
- 原始 HTML 在本地，报价 quote 可逐条回查；
- 492–600 m 是 Trip.com 与 catalog 的坐标系/地理编码差异，不是换了一家店。

## 2. 恢复结果：13 家缓存 + 1 家实时

| 酒店 | price | basis |
|---|---:|---|
| 西安索菲特传奇酒店（人民大厦） | 1,440 | page price |
| 维也纳国际酒店西安北站店 | 191 | page price |
| 西安威斯汀大酒店(大雁塔大唐不夜城店) | 776 | page price |
| 瑞诚假日酒店 | 181 | starting_average_price |
| **西安博豪快捷酒店**（numbed=2） | **98** | starting_average_price |
| **西安赛庭商务宾馆**（numbed=2） | **135** | starting_average_price |
| **西安庆丰商务宾馆**（numbed=2） | **117** | starting_average_price |
| 西安柏羽酒店 | 227 | starting_average_price |
| 西安永佳宾馆 | 91 | starting_average_price |
| 西安悦享精品酒店 | 137 | starting_average_price |
| 金舟酒店(西安比亚迪阳光天地店) | 161 | starting_average_price |
| 非哈酒店(西工程大西科大临潼校区地铁站店) | 158 | starting_average_price |
| 馨悦宾馆(西安长安大街店) | 98 | starting_average_price |

另 1 家青旅走实时详情页（带 2026-11-20/21 入住日期）：

| 酒店 | price | basis | 证据 |
|---|---:|---|---|
| 西安书友理想国主题青年旅舍大明宫遗址公园店 | **41** | `priceRange = 由 CNY41 起` | `raw/hotel/5982271.html` |

## 3. 覆盖率变化

| 指标 | 恢复前 | 恢复后 |
|---|---:|---:|
| `source_value` | 240 | **254** |
| `estimated` | 78 | 78 |
| `unknown`（-1） | 388 | **374** |
| 有价合计 | 318 / 706 | **332 / 706（47.0%）** |

优先级目标里的 **3 家 `numbed=2` 已全部补齐**；青旅补齐 1 家（书友 41）。

## 4. 仍缺的 3 家青旅

| 酒店 | 情况 | 建议 |
|---|---|---|
| 木木夕青年旅舍(西安钟楼店) | Trip.com 无精确同名 | 回退同类青旅中位数 **38 [25,42]** |
| 易休太空舱公寓(西安南门店) | 只有“咸宁店”分店，不能套用 | 同上 |
| 西安·梦想家青年旅舍(南稍门地铁口草场坡店) | Trip.com 无精确同名 | 同上 |

青旅已有价：25/26/38/41/42（+61 estimated），中位数 **38**。

## 5. 口径与风险

- 10 条 `starting_average_price` 是“挂牌起步均价”，不是绑定日期的 `minPrice`；provenance 的 `method=trip_com:starting_average_price` 已注明。
- 3 条 `page price` 的 locator 落在页面 header，但 quote/URL/HTML 均可回查。
- 距离 492–600 m 的记录统一标注 `identity_note=exact_name+hotel_id; distance is a datum offset`；若后续发现同名分店，可回滚。
- 实时抓取使用 `.secrets` 之外的公开页面，不涉及 key。

## 6. 复现

```bash
python scripts/adopt_cached_trip_prices.py          # 13 家缓存，dry-run
python scripts/adopt_cached_trip_prices.py --apply
python scripts/adopt_trip_live_price.py --hotel "西安书友理想国主题青年旅舍大明宫遗址公园店" \
    --hotel-id 5982271 --checkin 2026-11-20 --checkout 2026-11-21 --apply
```
