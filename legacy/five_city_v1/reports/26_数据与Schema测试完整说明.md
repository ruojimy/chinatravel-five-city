# 五城数据与 Schema 测试完整说明（答辩版）

**日期**：2026-10-26　**数据集**：`data/five_city_reference_v4_20261026`（1914 条记录）　**测试**：`results/p31_five_city_96`（96 题）
**用途**：把「数据怎么来、怎么判可信、怎么过滤、怎么结构化、怎么测、LLM 在哪、结果说明什么」一次讲清，并预置可能被追问的缺口。

---

## 0. 一页速览

| 项 | 数字 | 出处 |
| --- | ---: | --- |
| 五城记录 | 1914（地铁 970、POI 494、餐厅 125、景点 123、火车 74、航班 64、酒店 64） | v4 `validation.json` |
| 证据 / 字段声明 / TAG | 3598 / 5790 / 6072 | 同上 |
| 全字段非空记录 | 1607 | 同上 |
| 被拒实体 | 37（厦门 24、长沙 8、西安 5） | `rejected_entities.json` |
| 采集阶段 | 4 段（P29、P30 一轮、补跑、二/三轮） | 报告 24 |
| 采集请求 | ≈1418（P29 179 + P30 1239） | 各 bundle |
| 证据主机 | 98 个标识（97 个外部站点 + 1 个本地派生） | v4 evidence |
| 96 题测试 | 72 complete、20 blocked、4 infeasible | 报告 25 |
| 动态调用 | 468（450 主 + 18 详情），4.88/题 | `retrieval/ledger.json` |
| `planning_ready` | **0**（设计门槛，不是采集失败） | 第 3 节 |

---

## 1. 数据收集方式

### 1.0 先分清三套数据

| 数据 | 规模 | 作用 | 不是 |
| --- | ---: | --- | --- |
| 原 ChinaTravel 沙盒 | 33,806 条（双语 67,612） | 原 10 城冻结基准 | 不是本次新采 |
| 扩容库（Overture + 业务补全） | 14,057 个地点、42,576 TAG、5,187 证据 | 30 城候选发现与缺口暴露 | 不是 ChinaTravel 原生七表 |
| 五城原生参考库 v4 | 1,914 条（七表） | 本次采集/测试的对象 | 不是扩容库全量 |

五城库是从扩容库与旧库中**抽取并补齐**的 ChinaTravel 原生形状；1,914 不等于 14,057，也不是替代关系。扩容库主体来自 Overture 公开地点数据（2026-10 快照），业务字段由 P13–P17 的地图/网页补全流程补齐。

### 1.1 四段采集

| 阶段 | 时间（北京） | 执行者 | 产出 |
| --- | --- | --- | --- |
| P29 | 10-25 17:59–18:23 | Codex 主线程 + 3 子代理 | v1：1099 条（66 实体 + 63 派生 POI + 970 地铁） |
| P30 一轮 | 10-25 19:42–20:13 | Claude 主线程 + 5 城子代理 | 4 城 bundle；厦门抓完未组装（额度中断） |
| 厦门补跑 | 10-26 00:34 | 原厦门 worker | 厦门 113 实体；00:36 合并 v2 |
| 第二轮 | 10-26 10:06–10:36 | xiamen_r2、flights_r2、gaps_r2 | 厦门非携程重采、五城航班、缺口补全；v3 |
| 第三轮 | 10-26 10:45–10:58 | flights_r3、restaurants_r3、stays_sights_r3 | 长沙航班 18、餐厅 3 处、酒店景点 26 处；v4 |

### 1.2 采集通道

| 通道 | 用法 | 规模 |
| --- | --- | --- |
| 检索器（Codex `web__run`） | `search_query` / `open` / `click`，批量站点定向查询 | P29：厦门 75、长沙 80、宁波青岛 90 次动作 |
| 直连 HTTP（P30） | 自写 `urllib` / `requests` / `curl`，保存 HTML/PDF/文本 | 第一轮 775 次、第二轮 318、第三轮 146 |
| 结构化 API | Wikidata SPARQL、Nominatim、Overpass、高德 | 地铁 970 条一次查询；Nominatim 95 条证据（P29 15 次定点）；高德 22 条证据（P29 6 次后限流停止） |
| 官方 PDF | 山东航空冬春计划、会议住宿通知 | 14 条 SC 航班 + 多城协议房价 |
| 模型中介（WebFetch） | 被验证页挡住的航班/酒店页 | 48 条记录带 `model_extracted_source_text` 标记 |

### 1.3 组织方式

- **合约先行**：`CONTRACT.md` 规定每城目标（景点/餐厅 ≥20、酒店 ≥10、POI ≥20、火车 ≥10、航班 ≥6）、原生字段、bundle 形状、TAG 词表、时间戳规则、诚信边界。
- **一城一目录**：每个 worker 只写自己的 `workers/<slug>/`，交付 `bundle.json + sources/ + requests.jsonl + README.md`。
- **零重试**：站点首次失败即记入 `new_pauses`，不换工具、UA、子域、移动版或镜像。
- **根代理统一审计**：按「首次失败后是否还有同家族请求」判定，做来源级剔除、规范化、合并与校验。

### 1.4 请求量

| 阶段 | 请求数 | 明细 |
| --- | ---: | --- |
| P29 | ≈179 | 厦门 75、长沙 80、宁波+青岛 24 |
| P30 第一轮 | 775 | 西安 130、宁波 192、青岛 130、长沙 119、厦门 204 |
| 第二轮 | 318 | xiamen_r2 210、gaps_r2 58、flights_r2 50 |
| 第三轮 | 146 | stays_sights_r3 94、restaurants_r3 42、flights_r3 10 |
| **合计** | **≈1418** | — |

---

## 2. 数据来源分布

### 2.1 证据总量与结构

- 3598 条 evidence：其中 **1903 条是本地派生占位**（`id` 与派生字段的 `local_derivation`），真实外部原文证据约 **1695 条**。
- 98 个主机标识（97 个外部站点 + `urn:shorttrip:p30-local-proxy`）。

### 2.2 主要来源（按证据条数）

| 来源 | 条数 | 主要贡献 |
| --- | ---: | --- |
| www.wikidata.org | 998（含地铁 970） | 地铁站线、景点/酒店坐标 |
| nominatim.openstreetmap.org | 95 | 地理编码（WGS84） |
| docs.overturemaps.org | 59 | 门牌级坐标、POI |
| visitxian.cn | 48 | 西安景点/餐厅/酒店属性 |
| www.openstreetmap.org | 41 | 青岛 POI/坐标 |
| inqingdao.com | 40 | 青岛景点/餐厅/酒店 |
| www.nbtour.com | 36 | 宁波景点/酒店 |
| en.wikivoyage.org | 30 | 长沙/厦门补充 |
| www.kaggle.com | 27 | 长沙历史景点数据 |
| www.ly.com | 27 | 航班/酒店 |
| www.cityhui.com | 26 | 长沙餐厅 |
| trains.ctrip.com | 26 | 车次（未被验证拦截，按站点暂停口径保留） |
| restapi.amap.com | 22 | P29 GCJ02 坐标 |
| www.dahepiao.com | 17 | 厦门票价 |
| train.hao86.com | 15 | 青岛车次 |
| www.gaotie.net | 14 | 宁波车次 |
| query.wikidata.org | 13 | 半径查询 |
| qq.ip138.com | 11 | 西安车次 |
| www.sda.cn | 8 | 山航航班计划 |

### 2.3 逐城来源结构（业务记录引用到的站点，已排除地铁）

| 城市 | 外部站点数 | 主要来源（引用记录数） |
| --- | ---: | --- |
| 西安 | 16 | visitxian 51、Wikidata 查询 25、高德存档 22、Nominatim 15、维基百科 13、同程 11、ip138 11 |
| 厦门 | 38 | Nominatim 65、大河票务 17、携程火车 14、同程 9、Overture 8、厦大会议页 6、iFlying 6 |
| 宁波 | 22 | nbtour 38、Wikidata 36、Nominatim 23、gaotie 17、查航线 10、Overture 8、什么值得买 8 |
| 长沙 | 30 | 维基导游 44、cityhui 25、Overture 23、同程 20、Kaggle 19、Wikidata 查询 18、携程火车 16 |
| 青岛 | 18 | OSM 54、inqingdao 38、hao86 15、山航官网 14、同程 8、Overture 7、买购网 4 |

### 2.4 许可分布（先弄清它统计的是什么）

**这张表统计的是 3598 条 evidence（来源快照），不是 1914 条记录。** 一条记录可以引用多条证据，所以表里的数字加起来正好是 3598。

| 许可标记 | 条数 | 实际是什么 | 使用限制 |
| --- | ---: | --- | --- |
| `allowed` | 1934 | **1903 条是本地派生占位**（`id`、类目映射、坐标换算等，不是外部内容）+ 31 条 Overture 文档页 | 本地派生可内部使用；31 条外部页仍应复核 |
| `cc0` | 970 | Wikidata 地铁站线（公共领域） | 可自由使用 |
| `unknown` | 554 | 网页没有声明许可：visitxian 47、Nominatim 41、inqingdao 40、nbtour 36、维基导游 30、Wikidata 实体页 28、同程 27、cityhui 26、携程火车 26 等 | **默认不可再分发**，需逐条确认 |
| `odbl` | 95 | OSM/Nominatim 的 ODbL | 可用，但需署名、相同方式共享 |
| `public_page_reuse_unverified` | 20 | 政府/景区页，标注「可引用但未核实」 | 仅研究引用，需复核 |
| `api_terms` | 14 | 高德 API 返回 | 受服务条款约束，通常不能批量再分发 |
| 其他 | 11 | CC-BY-SA 1、仓库许可未找到 1、版权未知 1、上游/指南/公共来源未核实 8 | 逐条处理 |

**怎么读这张表：**

1. **`allowed` 大不是因为「大家都允许」，而是因为本地派生占位多。** 1903 条本地派生把 `allowed` 抬到了 1934；真正的网页 `allowed` 只有 31 条（Overture 文档页）。
2. **`unknown` 554 是最大的合规缺口。** 它不代表「不能用」，而代表「没有依据说可以用」；只要许可不在允许集合内，`validate_record` 就会给 `usage_rights_unknown`，记录不能进 `planning_ready`。
3. **同一站点存在标注不一致**：Nominatim 95 条里 54 条标 `odbl`、41 条标 `unknown`；Overture 59 条里 31 条 `allowed`、28 条 `unknown`；Wikidata 地铁 970 条 `cc0`，但实体页 28 条 `unknown`。这说明许可是各 worker 按自己的判断打的，**缺一个按 host 的统一登记表**——这是已知缺陷，修复方式是「host → 许可」中心表 + 全量重标，而不是逐条争论。

**各状态一个例子：**

- `cc0`：西安地铁小寨站（Wikidata）；
- `odbl`：厦门站坐标（Nominatim）；
- `api_terms`：西安北站→兵马俑路线（高德）；
- `unknown`：兵马俑价格（visitxian.cn，网页未声明许可）；
- `public_page_reuse_unverified`：橘子洲开放信息（湖南省文旅厅，可引用但未核实）；
- `allowed`：橘子洲 `id` 的本地派生 evidence（我们自己生成的 JSON）。

**要点**：来源不是「一个爬虫抓全网」，而是**官方/半官方 + 开放数据 + 少量 OTA + 模型抽取**的混合；许可未知的 554 条证据是再分发前必须处理的缺口，也是 `planning_ready=0` 的阻断项之一（`usage_rights_unknown` 841 条记录）。

### 2.5 本地派生 1903 条是怎么算出来的

**触发条件**（`p30_build_five_city.py` 的 `envelope()`）：

1. 字段有 `field_refs` → 用外部 evidence，状态 `source_value`；
2. 没有 ref，但能从 P29 旧记录继承同值 → 用旧 evidence；
3. 两者都没有 → **为该字段生成一条本地派生 evidence**：
   `{record_id, field, value, basis:"deterministic local proxy or representation; not independently verified fact"}`，URL 为 `urn:shorttrip:p30-local-proxy`，`authority=local_derivation`，`licence_status=allowed`。

所以它是**逐字段的兜底**，不是逐记录：

- 7805 个字段引用中，4602 个有外部 quote（`source_value`），2534 个是 `derived`，669 个是 `unknown`（null）；
- 1903 条本地 evidence = **1234 个 derived 值 + 669 个 unknown(null)**；
- 1122 条记录一个本地字段都没有（970 条地铁全部来自 Wikidata，152 条业务记录字段全有外部引用或继承）。

**按字段分布（前 10）**：name 565、position 312、id 291、lon 119、lat 112、endtime 74、type 70、opentime 59、price 57、recommendmaxtime 55。

**四个具体例子**：

| 字段 | 记录 | 值 | 怎么来的 |
| --- | --- | --- | --- |
| `id` | 长沙·橘子洲景区 | 219317389894287 | `int(sha256(record_id)[:12],16)`，本地代理键 |
| `position` | 长沙·岳麓书院 POI | `[28.1839, 112.936]` | 由景点 `lat/lon` 组装；上游坐标 provenance 另存在 `field_provenance.position.upstream_coordinate_provenance` |
| `type` | 宁波·宁波帮博物馆 | `博物馆/纪念馆` | 源类目映射到 ChinaTravel 类型词表 |
| `Duration` | 青岛·SC4656 | `1.42` | 由 21:20–22:45 起降时刻计算 |
| `lat` | 长沙·火宫殿 | `null` | 缺坐标；仍生成一条 value=null 的本地占位 evidence，status=`unknown` |

**为什么许可写 `allowed`**：这条 evidence 的 `raw_text` 是我们自己生成的 canonical JSON，不含第三方内容，所以不存在第三方许可问题；它**不代表「原始网页允许转载」**。这也是为什么不能把 1903 当成「1903 条已授权网页」。

**为什么要有它**：如果没有这条占位，`field_provenance` 就会出现「有值但没有任何 evidence」的空洞，无法回答「这个值从哪来」。本地派生的作用是把「这是我们算的、不是抄的」显式写下来，让每个字段都可追溯。

---

## 3. 置信度判定

### 3.1 不是一个分数，而是六维

| 维度 | 取值 | 作用 |
| --- | --- | --- |
| D1 字段状态 | `source_value / estimated / derived / unknown / synthetic` | 值是不是来源直接写的 |
| D2 证据等级 | `verified / reference / estimate / sandbox / decision` | 动态证据的强度 |
| D3 实体核验 | `entity_verified` 真/假 | 是不是同一个实体（分店、同名） |
| D4 时钟 | `retrieved_at / observed_at / source_published_at / valid_until` + TTL | 事实何时被观察、是否过期 |
| D5 许可 | `allowed / cc0 / odbl / api_terms / unknown` | 能不能用、能不能再分发 |
| D6 不确定性标记 | `needs_live_verification`、`model_extracted_source_text`、`coordinate_system=unknown` 等 | 显式暴露剩余风险 |

### 3.2 字段状态实测（v4）

| 状态 | 字段数 | 含义 |
| --- | ---: | --- |
| `source_value` | 4602 | 来源原文直接支持 |
| `derived` | 2534 | 本地派生（id、类目映射、坐标转换） |
| `unknown` | 669 | 无值 |

### 3.3 时钟实测

- **0/1914 条记录有 `observed_at`**；
- 只有 3 条有 `source_published_at`；
- 抓取时间 `retrieved_at` 全部有，但**抓取时间不能当观察时间**。

**重要缺陷（答辩要主动说）**：v4 的 `record.retrieved_at` 全部等于 builder 时间 `2026-10-26T03:01:42Z`，与 `catalogued_at` 相同，**不是网页抓取时间**；真正的抓取时间在 `evidence.retrieved_at`（如兵马俑的 `2026-10-25T11:52:33Z`）。这是字段命名缺陷，审计时应读 evidence 时钟，不能读 record 的 `retrieved_at`。

这是 `unknown_field_age` 在每条记录上都出现的根本原因。

### 3.4 TTL（项目默认，不是来源保证）

| 字段策略 | TTL | 典型字段 |
| --- | ---: | --- |
| `opening_hours` | 24 小时 | opentime/endtime |
| `price` | 24 小时 | 景点/餐厅价格 |
| `dynamic_price` | 300 秒 | 酒店/机票/车票 |
| `intercity_schedule` | 6 小时 | 车次/航班时刻 |
| `coordinates` | 90 天 | 经纬度 |
| `theme/experience` | 90–180 天 | 类型、体验 TAG |

### 3.5 置信度阶梯

```
可规划（planning_ready）
  ↑ 需要：source_value + observed_at 在 TTL 内 + entity_verified + 许可允许 + WGS84
已验证（verified）      ← 只允许根侧登记为该级别的证据
来源值（source_value）  ← 原文直接支持，但可能没有观察日期
参考（reference）       ← 可追溯的发布参考
估计（estimate）        ← 提供方估计（如天气、路线）
派生（derived）         ← 本地计算/映射，不是事实
未知（unknown）         ← null
```

### 3.6 为什么 v4 的 `planning_ready=0`

每条记录都至少被三项阻断：

| 阻断 | 记录数 | 原因 |
| --- | ---: | --- |
| `entity_unverified` | 1914 | builder 没有独立实体核验环节 |
| `unknown_field_age` | 1914 | 没有来源观察日期 |
| `unverified_field` | 1835 | 本地派生的 `id`、类目映射不是 `source_value` |
| `usage_rights_unknown` | 841 | 网页许可未知 |
| `checker_requires_wgs84` | 216 | 餐厅 68、酒店 24、POI 117、景点 7 非 WGS84 |
| `expired_field` | 1 | 单条过期 |

**结论**：`planning_ready` 的定义是「已实时核验」，不是「字段齐全」。静态采集给的是 **reference_only 候选**；要规划级，必须在请求当天补 observed_at、价格、营业时间、余票。

### 3.7 六维各举一例

| 维度 | 例子 | 说明了什么 |
| --- | --- | --- |
| D1 字段状态 | 兵马俑 `price=120`（quote「¥120 起」）是 `source_value`；橘子洲 `id=219317389894287` 是 `derived`；火宫殿 `lat=null` 是 `unknown` | 同一个库里三种状态并存 |
| D2 证据等级 | P24 兰州开放时间 `reference`；长沙天气 `estimate`；P27 厦门路线 `verified`（`entity_verified=true`）；北京环球影城 503 是 `sandbox`；预算 200 是 `decision` | 等级由来源与上下文决定 |
| D3 实体核验 | 兵马俑 `entity_verified=false`；P27 路线起终点坐标一致 → `true`；南普陀旧同名点（park、24.6088）不采用 | 同名/异点不能靠猜 |
| D4 时钟 | 兵马俑 evidence `retrieved_at=2026-10-25T11:52:33Z`、`observed_at=null`；橘子洲 `source_published_at=2026-09-23T10:35+08`；价格 TTL 24h | 抓取 ≠ 观察 |
| D5 许可 | 小寨站 `cc0`；厦门站 `odbl`；高德路线 `api_terms`；兵马俑 `unknown`；橘子洲 `public_page_reuse_unverified`；本地 id `allowed` | 许可按来源逐条标 |
| D6 不确定性 | 全库 `needs_live_verification=true`；CZ3379 `model_extracted_source_text`；火宫殿 `coordinate_system=unknown`；970 条地铁 `metro_operational_status_unknown` | 剩余风险显式化 |

**把六维串起来看兵马俑**：价格是 `source_value`，但证据等级只是 `reference`；`entity_verified=false`；`observed_at=null`；许可 `unknown`；`needs_live_verification=true`。所以字段全齐、quote 也对，仍然进不了 `planning_ready`——缺的是「观察时间 + 实体核验 + 许可」，不是「值」。

---

## 4. 数据冲突处理

### 4.1 规则

1. **不取平均、不投票**：冲突时选一个值，另一个写进 `scope`/`notes`；
2. **不合并身份**：同名不同分店、不同地址一律分列；缺门牌/边界证据不按相似名合并；
3. **保留原值**：单位换算、24:00→23:59、GCJ→WGS84 都保留原文；
4. **冲突不自动升级**：保留为 `reference` 或 `unknown`，不因「有两源」就标 verified。

### 4.2 实例

| 实体 | 冲突 | 处理 |
| --- | --- | --- |
| 缸鸭狗 | 人均 41（水晶街店） vs 57（四明中路总店） | 保留 41，注明分店不同，不平均 |
| 日光岩 | 闭园 17:30 vs 18:00 | 采用官方/管委会口径，另一值进 scope |
| 杜甫江阁 | 票价 12 / 11 / 18 | 选一个并注明票种/日期 |
| 1980 烧肉粽 | 人均 13 vs 29 | 选 13，注明来源与分店 |
| 信号山 | 门票「免费」 vs 「¥10 旋转观景楼」 | 保留免费，另注观景楼收费 |
| 海景花园大酒店 | 区名 市南 vs 崂山 | 保留冲突，不强行归一 |
| 月华沙茶面 | 人均 17 vs 20–35 | 采用 17，注明区间来源 |
| G1692 | 票价 621 vs 568 | 作为不同车次记录分列，不合并、不平均 |
| 广仁寺 | 中英文开放时间不一致 | 取中文 8:00–17:30，英文进 notes |
| 长沙 G1692/G1693 | Duration 409（分钟） vs 6.82 小时 | 记录单位异常；规划器对 >24 的值不自动换算，作为已知缺陷 |

### 4.3 冲突类型

- **价格**：票种、日期、分店、起价/协议价；
- **时间**：淡旺季、临时调整、只写日期不写时分；
- **身份**：同名分店、连锁品牌、旧址/新址；
- **单位**：分钟 vs 小时、元/人 vs 元/间夜；
- **坐标**：WGS84 vs GCJ02、入口 vs 山顶。

---

## 5. 数据过滤与剔除

### 5.1 来源级排除（8 条规则）

| # | worker | 站点/家族 | 触发 |
| --- | --- | --- | --- |
| 1 | 西安 | trip.com | curl 遇验证页后改用 WebFetch |
| 2–4 | 厦门 | m/you/gs.ctrip.com | you.ctrip 验证重定向后换移动页/H5 |
| 5–6 | 长沙 | gs/you.ctrip.com | 验证后换 H5 |
| 7 | 长沙 | nz.trip.com | www.trip.com 432 后换子域 |
| 8 | flights_r2 | chahangxian.com | 首次 TLS 超时后循环继续 |

处理：**来源级删除**该来源及引用它的字段值与 TAG；实体只在没有剩余来源时整条拒绝。

### 5.2 结果

| 版本 | 整条拒绝 | 部分剥离 |
| --- | ---: | ---: |
| v2 | 41 | 27 |
| v3 | 41 | 10 |
| **v4** | **37** | **7** |

37 条分布：厦门餐厅 16、厦门酒店 8、西安航班 5、长沙酒店 4、长沙航班 4。
7 条部分剥离中只有「大中沙茶面」丢了 5 个字段，其余只删来源不断值。

### 5.3 其它过滤

- **robots/条款**：`echinacities`（禁 `/detail/*`）、`sohu`（全禁）、`mafengwo`（全禁）、`flightera`（`ai-input=no`）、OSM 节点页（禁 `/node/`、`/way/`）；
- **抓后丢弃**：`chinaholiday` SSL 失败后误抓 2 页、`sohu` 文章，均已删除且未入库；
- **暂停不重试**：`dianping`/`meituan`、`michelin`、`bendibao`、`baike`、`zhihu`、`overpass`、`wikidata`（429）等；
- **未访问**：携程/Trip 全家族（第二轮起）、高德 API（P30）、已暂停站点。

### 5.4 去重与规范化（225 条事件）

| 类型 | 数量 | 说明 | 例子 |
| --- | ---: | --- | --- |
| `partial_date_preserved_as_text` | 129 | 时间不完整或缺时区，不能解析成带时区时钟，原文另存 | 宁波旅游网 `2025-08-04T21:27`（无时区）；81 条只有日期、39 条日期+时分无时区、9 条带秒/空格 |
| `transport_name_set_to_id` | 55 | 车次/航班名含区间，改为编号；不同区段保留多条 | 「G1692 长沙南站-厦门北站」→ `G1692` |
| `gcj02_converted_to_wgs84` | 21 | 迭代反解，误差约 1e-6 度，原值进 scope | 三阳开泰酒楼 `[34.235854,108.958143]` → `[34.237428,108.953455]` |
| `excluded_sources_stripped` | 7 | 合规剥离，只删来源与引用，不整条删值 | 乌糖沙茶面的 `m.ctrip.com` 来源被剥，原字段保留 |
| `end_of_day_24_00_as_23_59` | 7 | 校验器只收 ≤23:59，原值进 scope | 宁波老外滩 `endtime 24:00` → `23:59` |
| `p29_entity_superseded_by_p30` | 6 | 同 `existing_record_id` 的新版本覆盖旧记录 | 青岛「小魚山公園」的 P29 版被 P30 版取代 |

去重键：车次/航班「城市 + 编号 + 目的城市」；同编号不同目的地保留；POI 由有坐标实体派生，同名同引用。

---

## 6. 数据结构化

### 6.1 ChinaTravel 原生七表

| 表 | 字段 | 原库文件形态 | 本项目导出 |
| --- | --- | --- | --- |
| 景点 | `id,name,type,lat,lon,opentime,endtime,price,recommendmintime,recommendmaxtime` | `attractions/<city>/attractions.csv` | `reference_database/attractions/<slug>/attractions.csv` |
| 餐厅 | `id,name,lat,lon,price,cuisine,opentime,endtime,recommendedfood` | `restaurants/<city>/restaurants_<city>.csv` | `reference_database/restaurants/<slug>/restaurants_<slug>.csv` |
| 酒店 | `id,name,hotelname_en,featurehoteltype,lat,lon,price,numbed` | `accommodations/<city>/accommodations.csv` | `reference_database/accommodations/<slug>/accommodations.csv` |
| POI | `name,position` | `poi/<city>/poi.json`（`[lat,lon]`） | `reference_database/poi/<slug>/poi.json` |
| 地铁 | `name,position,line` | `transportation/subways.json` | `reference_database/subway_stations/<slug>/subway_stations.json` |
| 火车 | `TrainID,TrainType,From,To,BeginTime,EndTime,Duration,Cost` | `intercity_transport/train/from_X_to_Y.json` | `reference_database/intercity_transport/<slug>/train.json` |
| 航班 | `FlightID,From,To,BeginTime,EndTime,Duration,Cost` | `intercity_transport/airplane.jsonl` | `reference_database/intercity_transport/<slug>/airplane.json` |

### 6.2 值约定

- 时间 `HH:MM`（闭园可用 `24:00`，导出时转 `23:59` 并保留原文）；
- `price` 人民币数值；景点/餐厅为每人，酒店为每间夜；
- `Duration` 小时数（如 4.6）；
- 坐标 WGS84，POI `position=[lat,lon]`，地铁 `position="lon,lat"`；
- `id` 由根代理统一生成，不允许子代理写。

### 6.3 扩展层（我们自建）

一条记录除原生 `data` 外还带：

```json
{
  "record_id": "p30:...", "kind": "attraction", "city": "西安", "name": "秦始皇兵马俑",
  "data": {"id": 123, "name": "秦始皇兵马俑", "type": "历史古迹", "lat": 34.385, "lon": 109.273,
           "opentime": "08:30", "endtime": "18:30", "price": 120.0,
           "recommendmintime": 2.5, "recommendmaxtime": 4.0},
  "tags": [{"tag": "reservation_required", "value": true,
            "basis": {"source_index": 0, "quote": "需要提前实名预约"},
            "status": "source_value", "policy_id": "experience"}],
  "field_provenance": {"price": {"source_id": "p30:...", "evidence_id": "p30-evidence:...",
                                 "status": "source_value", "observed_at": null,
                                 "source_url": "https://visitxian.cn/..."}},
  "source_id": "...", "source_url": "https://visitxian.cn/...", "retrieved_at": "2026-10-25T11:52:33Z",
  "observed_at": null, "coordinate_system": "WGS84", "trust_status": "reference_only",
  "entity_verified": false, "needs_live_verification": true,
  "uncertainty_flags": ["static_reference_not_live_confirmation"],
  "scope": {"price": "成人普通票，旺季"}
}
```

> `field_refs`（source_index + quote）是 **bundle 的输入形态**；入库时被展开成 `field_provenance[*].evidence_id + quote`，并生成 evidence/claim。

### 6.4 存储与导出

- `catalog.sqlite3`：`records / evidence / claims / tags / metadata` 五表；
- `records.jsonl.gz`、`evidence.jsonl.gz`、`claims.jsonl.gz` 明文副本；
- `reference_database/`（含 null）与 `complete_reference_database/`（1607 条全非空）两套原生形状；
- `manifest.json` 记录每个产出文件 SHA256，builder 不联网。

### 6.5 TAG 结构

```json
{"tag": "theme", "value": "history",
 "basis": {"source_index": 0, "quote": "历史古迹"},
 "status": "source_category", "policy_id": "theme",
 "source_time_ref": "observed_at", "valid_until": null}
```

6072 个 TAG：结构性 `kind`、`native_fields_complete` 各 1914；地铁线路/网络各 970；业务 TAG 304（cuisine 44、theme 44、reservation_required 41、amenity 36、open_24_hours 23、closed_weekday 22 等）。

---

## 7. Schema 测试设计

### 7.1 三代 schema

| 代 | 规模 | 目的 | 结果 |
| --- | --- | --- | --- |
| P24 | 96 题（30 新城 ×3 层 + 6 串联） | 新城市缺口与动态反馈 | 0/96 complete；40/528 字段 |
| P27 | 3 题 ×4 轮 | 集中预算深挖 | 原题 0/3；补起点后 1/2 |
| P31 | 96 题（五城 ×3 层 + 20 串联） | 扩张后静态集 + 动态能力 | 72/96 complete |

### 7.2 P31 任务构造

- easy 32：单城 2 个字段完整景点 + 火车站起点；日期 10-28；
- hard 32：20 题单城（3 景点 + 午饭）、12 题新旧城串联（新城 1 天 + 老城 1 天）；日期 10-29 / 10-28–29；
- human 32：24 题单城自然表达 + 8 题串联，含老人、预算、半天、雨天等软约束；
- 候选实体全部从 v4 与旧库拷贝；景点按 30 km 聚类、起点站 ≤35 km，避免人为制造跨城不可行；
- 预算 = 门票×人数 + 午饭×人数 + 酒店 + 城际×人数 + 120 元市内交通，human 再放宽 10%。

### 7.3 三个任务例子

**E01（easy）**
> 2026-10-28，两人从西安北站出发，想去西安的汉阳陵、大明宫国家遗址公园，坐地铁或公交，当天 18:00 前回到西安北站。请核对开放时间、两人门票、当天天气和往返路上要多久，预算 380 元。

候选：汉阳陵、大明宫（字段齐全）；检查：2 张门票、开放时段、3 段路线、天气；实际 4 次调用，complete。

**D31（hard，串联）**
> 西安两天一夜：10-28 上午两人从西安北站出发，看西安城墙和西安碑林博物馆，住 Hilton Xi'an；10-29 早上坐 CA1206（08:20）去北京，下午看颐和园。核对车次/航班时刻、酒店价格、两侧开放时间与天气，总预算 1870 元。

候选：城墙、碑林、希尔顿、CA1206；旧城侧颐和园来自旧库；检查：酒店价、航班时刻、两侧开放、2 城天气、3 段市内路线；实际 5 次调用，complete。

**N17（human，失败例）**
> 去长沙出差，下午 1 点从长沙南站出发，只看一个景点，6 点前回站，预算 460。

候选：长沙海底世界（票价 150×2）；实际：13:00 出发、真实公交 2 段，返回 18:20，超 20 分钟 → infeasible。说明「规则规划器不会砍点/换点」。

### 7.4 评测检查与状态

| 检查 | 通过条件 |
| --- | --- |
| 字段闭合 | 必填字段全部非空（或动态补齐） |
| 开放 | 每个到访实体有开放时段，访问落在窗口内 |
| 路线 | 每段有动态路线（或 ≤1.5 km 步行） |
| 预算 | 已知费用 ≤ 上限，且无未知价格 |
| 天气 | 每天有预报值 |
| 城际 | 车次/航班字段齐全，到达后能赶上老城景点 |

状态：`complete`（全过）、`blocked`（缺价/缺时）、`infeasible`（超窗）、`partial`（证据不全，本轮无）。

### 7.5 防泄漏

- 隐藏要求只在 evaluator 里，参与者只看到自然语言 + 候选；
- 不在首稿前给 checker 反馈；
- 每题的 `requests` 由计划显式生成，未请求的来源不会自动灌入；
- P24 的 `requirements` 放在 private，public 只给 `levels/queries`。

---

## 8. LLM 引入方式

### 8.1 五种角色

| 角色 | 实验 | 模型/代理 | 规模 | 结果 |
| --- | --- | --- | --- | --- |
| API 参与者 | P20 | DeepSeek V4 Pro | 4 题、61 次调用 | 0 严格接纳 |
| API 参与者 | P21 | DeepSeek V4.1 Flash | 4 题、101 次调用 | 0 严格接纳 |
| 子代理参与者 | P23 | Codex 子代理 ×3 | 150 题、1148 份计划 | 对照 704 题 |
| 子代理参与者 | P24 | Codex/Claude 子代理 | 96 题、192 份稿 | 0/96 complete |
| 子代理深挖 | P27 | 3 个参与 LLM | 3 题 ×4 轮、12 份 | 原题 0/3；补起点 1/2 |
| 规则对照 | P31 | **无 LLM** | 96 题、96 份 | 72/96 complete |

另有两条「模型参与但不作参与者」的用途：

- **抽取**：WebFetch 把页面转成 markdown 当 `raw_text`，48 条记录带 `model_extracted_source_text`；
- **审阅**：P29 一个子代理做语义复核，产出 39 条发现（high 11），只作审阅不作金标。

### 8.2 为什么 P31 不用 LLM

- 要测的是**数据集 + 动态检索**，不是模型能力；用 LLM 会把「模型会不会换点/砍点」混进来；
- 规则规划器可复算、可解释，每次失败都能定位到字段、路线或预算；
- 换入 LLM 的接口已经留好：`p31_static.build_plan` 的输入（任务 + 候选 + 约束）与输出（活动/交通/请求）就是参与者接口，LLM 只需产出同样的 plan JSON。

### 8.3 LLM 与确定性门的分工

- LLM 负责：理解自然语言、选点、排序、写解释、提出澄清问题；
- 门负责：quote 子串、字段齐全、单位、TTL、许可、坐标系、预算算术；
- **LLM 不能给自己的证据升权**：`entity_verified`、`verified` 只能由根侧登记。

---

## 9. Schema 如何跑在 ChinaTravel 原框架 + 动态检索框架上

### 9.1 原框架

ChinaTravel 的冻结沙盒是「query → planner → checker」：query 含人数、起城、目标城、日期、预算；planner 产出 itinerary/day/activities；checker 做 schema、常识与硬 DSL 检查。

### 9.2 我们的扩展

P24/P27 的**计划 schema** 在原框架上做了以下扩展；v4 的记录层只保留其中的 provenance/evidence 部分，不把计划对象混进静态库。

| 原字段 | 扩展 | 目的 |
| --- | --- | --- |
| `target_city` | `city_sequence`（有序） | 支持新旧城串联 |
| `activities` | 加 `date/city/entity_id/activity_id` | 核对实体归属与日期 |
| `price/cost` | 数量对象 `{value,status,evidence_ids}` | 分开单价/总价，未知不是 0 |
| `transports` | 加 `duration_minutes/cost/evidence_ids` | 计划时段不冒充实测 |
| 最终 plan | 加 `stage/gaps/retrieval_requests/feedback` | 对比检索前后 |
| 无 | `evidence/claim/record` 三层 | 每条值可回指原文 |

### 9.3 动态检索运行时

```
① 读 query：日期、人数、起终点、预算、偏好
② 静态候选：v4 + 旧库 SQL/预检，按城市/类型/TAG 剪枝
③ 缺口：缺坐标→路线无法算；缺时/价→不能判开放与预算；缺城际→不能排第 2 天
④ 请求：weather(city,date) / route(origin,dest,departure) / place(name,city)
⑤ 证据：Amap 返回 → claim/evidence（retrieved_at、infocode、raw、sha256）
⑥ 门：assess_evidence/validate_claim（目标、字段、城市、上下文、等级、quote、TTL）
⑦ 重排：用真实时长/票价/营业时间重算；仍缺→blocked，超窗→infeasible
⑧ 交付：plan + gaps + evidence_ids + 未解决项
```

### 9.4 与官方沙盒的隔离

- builder 不联网、不改 `ChinaTravel/` 原文件、不改历史 catalog 指针；
- 官方 checker 不注入、不修改；扩展 schema 不冒充官方评分；
- 原生投影只写 `reference_database/`，原库哈希保持不变。

---

## 10. 结果分析

### 10.1 P24（96 题，30 新城）

| 指标 | 值 |
| --- | ---: |
| 结构/协议通过 | 96/96 |
| 证据状态正确 | 89/96（动态后 90/96） |
| 必需字段 | 528 |
| 静态解决 | 0 |
| 动态解决 | 40（24 estimate + 16 reference，verified 0） |
| 网关请求 | 374（returned 43 / unavailable 331） |
| 有证据的题 | 27/96 |
| complete | **0/96** |

关键解释：**即使把当时捕获的全部语料给模型，上限也只有 40/528**；96 题都缺合格身份来源，所以 0/96 同时反映供给不足与评测设计，不能单独评价模型。

### 10.2 P27（3 题深挖）

- 3 题、12 份 plan、43 次请求（16 搜索 + 8 页面 + 19 高德）；
- 原题 0/3 接纳（厦门、长沙缺精确起点）；
- 研究者补起点后 1/2 接纳（长沙条件方案）；
- 说明：**增加调用不能生成用户没给的起点**，但能把「起点明确」的任务做闭合。

### 10.3 P31（五城 96 题）

| 层 | complete | blocked | infeasible |
| --- | ---: | ---: | ---: |
| easy | 32 | 0 | 0 |
| hard | 19 | 10 | 3 |
| human | 21 | 10 | 1 |
| 合计 | **72** | **20** | **4** |

- 静态阶段 68/96 已满足「字段 + 时段 + 预算」；动态详情救回 7 道缺营业时间的题；3 道静态可排的题被真实通行时间判死；**68 − 3 + 7 = 72**；
- 城市：西安 21/21、长沙 14/20、厦门 14/19、宁波 13/17、青岛 10/19；
- 单城 58/76，串联 14/20（0 城际失败，6 卡酒店价）；
- 动态调用 468 次；天气 116/116；路线 276 段动态 + 35 段步行；place 19/23 匹配、0 条营业时间；detail 11/18 有营业时间。

---

## 11. 薄弱之处（数据集 / 动态搜索 / 评测）

### 11.1 数据集

1. **价格缺口**：15 道 blocked 与票价/房价有关；免费景点（白城沙滩、鼓浪屿管风琴艺术中心、天封塔、宁波鼓楼、太平老街、黄兴路）没有「免费」的明示来源；
2. **营业时间缺口**：10 道 blocked 与开放街区/海滩有关（沙坡尾、大学路、栈桥、太平角、燕儿岛、爱晚亭）；
3. **酒店价格**：5 家连锁/高端酒店只有协议价或起价，不能当门市价；
4. **实体核验**：0/1914 `entity_verified=true`；
5. **观察时钟**：0/1914 `observed_at`，3 条 `source_published_at`；
6. **单位缺陷**：长沙 `G1692/G1693` Duration=409（分钟当小时）；
7. **坐标**：216 条非 WGS84（餐厅 68、酒店 24、POI 117、景点 7）；
8. **许可**：554 条证据 `unknown`；
9. **结构失衡**：地铁 970/1914，业务实体只占一半；
10. **厦门损失**：携程剔除导致 24 个实体被拒，景点 73%、餐厅 55%，是五城里偏低的一组；
11. **复用前缀不一致**：青岛 7 条 `existing_record_id` 写成 `overture:<uuid>`，其余城写成 `p29:<id>`；这是复用关系的一处不一致，按前缀 join 会漏。

### 11.2 动态搜索

1. **高德 v5 place 不返回营业时间**（0/23），必须再调 v3 detail（11/18）；
2. **不提供门票价、酒店房价**；
3. **不提供城际班次**，只能沿用冻结记录；
4. **短距离无公交方案**（35 段 ≤1.5 km，按步行处理）；
5. **名称匹配失败** 5 次（南普陀素菜馆、大方素菜馆、春和楼×2、燕儿岛公园）；
6. **天气窗口只有 4 天**，更远日期无预报；
7. **配额/限流**：P29 高德 6 次后 `10021` 停止；P30 不用高德；
8. **模型抽取文本**：WebFetch 的 `raw_text` 不是原始字节，48 条记录带标记。

### 11.3 评测方法

1. P31 是**规则规划器**，不是 LLM；结论只说明「数据 + 检索」，不说明模型上限；
2. `complete` 是规则校验，不是现实可执行性；
3. human 是研究者写的自然表达，不是真人采样；
4. 三层共享实体，96 题不是 96 个独立需求；
5. 日期固定在 10-28/29，天气窗口有限；
6. 没有预订、库存、排队、临时闭馆验证；
7. 任务预算由数据推算，存在循环性；
8. 只覆盖五城，不能外推 30 城；
9. **串联题第 1 天以回到起点站收尾，酒店只校验价格与存在，没有校验「景点 → 酒店」的接驳**；这会让部分串联题显得比实际容易，是当前评测的明确简化。

### 11.4 口径红线（答辩时不要这样说）

- 不说「96 题代表真实用户需求」——human 是研究者构造，三层共享实体；
- 不说「`complete` 等于现实可执行」——它只是规则自洽；
- 不说「0/96 说明模型不会规划」——P24 的供给上限只有 40/528；
- 不说「数据全部有许可」——554 条证据许可未知；
- 不说「P31 证明 LLM 不行/行」——P31 没有用 LLM；
- 不说「价格是实时价」——静态价是参考，动态价是起价；
- 不说「地铁 970 条等于 970 个车站」——是 970 条站线关系、851 个不同车站。

---

## 12. 可能被提问的 34 问

**Q1：为什么 `planning_ready=0`？是采集失败吗？**
不是。门要求 `source_value + observed_at 在 TTL 内 + entity_verified + 许可 + WGS84`；静态采集没有观察日期，builder 也不做实体核验，所以每条记录都被 `unknown_field_age` 与 `entity_unverified` 阻断。这是设计，不是数据为空。

**Q2：P24 是 0/96，P31 是 72/96，矛盾吗？**
不矛盾。P24 是模型在**冻结语料网关**里做 96 题，供给上限只有 40/528 字段；P31 是**规则规划器 + 真实高德**在 v4 上做 96 题，v4 比当时语料完整得多。两者测的不是同一件事。

**Q3：72/96 是不是自己放宽了标准？**
标准是预先写死的五项通用检查（字段、开放、路线、预算、天气）加串联的城际检查，没有按题调参；20 道 blocked 与 4 道 infeasible 都逐条列出。能争的是「complete 是否等于现实可行」，不能争的是「有没有偷偷放水」——所有请求、响应、计划、评估都在盘上。

**Q4：为什么 P31 不用 LLM？**
为了把「数据集 + 动态检索」与「模型能力」分开。规则规划器可复算，失败能定位到字段/路线/预算；LLM 接口已留好，换入后可直接对比。

**Q5：P31 的 complete 能说明现实可行吗？**
不能。它只说明「在给定静态参考 + 动态路线/天气下，字段、时段、预算、路线自洽」；票价仍是参考，营业时间可能临时调整，预约/库存未验证。

**Q6：数据是爬的还是 API？**
混合：公开网页直连（urllib/requests/curl）、检索器、Wikidata/Nominatim/Overpass/高德 API、官方 PDF。每条证据都记录通道与抓取时刻。

**Q7：为什么禁携程？禁了还怎么补厦门？**
携程/ Trip 在验证页后出现「换移动页/换子域/换 WebFetch」的绕行，违反合约，所以按来源级剔除。厦门第二轮改用非携程来源（官方景区站、大河票务、会议 PDF、OSM）重采，景点从 17 补到 23，但餐厅/酒店完整度仍偏低（55%/58%）。

**Q8：37 个被拒实体是不是数据丢了？**
不是丢失，是**合规拒绝**：来源被剔除后没有剩余来源，实体整条不入库；清单在 `rejected_entities.json`，可重采恢复。

**Q9：置信度是一个分数吗？**
不是。是六维：字段状态、证据等级、实体核验、时钟/TTL、许可、不确定性标记。把它们压成一个分数会掩盖「有值但不可用」的情况。

**Q10：怎么保证 quote 不是编的？**
所有 `field_refs`/`tags` 的 quote 必须是 `raw_text` 的精确子串，否则 build 抛错或实体被拒；`raw_sha256` 与文件哈希可离线复核。

**Q11：时间戳怎么防造假？**
`retrieved_at` 是抓取时刻，`observed_at` 只在来源明说时填；抓取时间不能顶替观察时间；只有日期就保留文本、不补时分；TTL 过期即不可用。

**Q12：冲突为什么不取平均？**
平均会造出一个没有任何来源支持的新值。项目规则是「选一个 + 记录另一个」，让读者能回到原文判断。

**Q13：免费景点为什么不能填 0？**
「没有价格」不等于「免费」。只有来源明说「免费/免票」才能写 0；否则写 null 并进缺口。P31 的 15 道价格 blocked 多数是这一类。

**Q14：酒店价格为什么不能用协议价？**
协议价绑定会议、日期、房型、资格，不能当任意日期门市价；项目把它写成 `scope` 里的参考价，不升为 `verified`。

**Q15：为什么地铁 970 条占大头？**
地铁是 Wikidata 一次性结构化查询的结果（970 条站线关系、851 站），字段完整、许可 CC0；业务实体（景点/餐厅/酒店）才 450 条左右，采集成本高得多。

**Q16：数据来源合法吗？**
优先官方/开放数据；网页遵守 robots，遇验证码/登录/限流即停；许可未知的 554 条证据已标注，再分发前需处理。项目定位是研究性复现，不声称商业再分发权。

**Q17：模型抽取的 WebFetch 文本算证据吗？**
算「模型抽取文本」，不算原始字节。48 条记录带 `model_extracted_source_text` 标记；quote 能对上提取文本，但不能证明页面逐字如此。

**Q18：GCJ02 怎么处理？**
确定性反解为 WGS84（21 处），原值进 `scope`，误差约 1e-6 度；无法确认基准的坐标写 `unknown`，不冒充 WGS84。

**Q19：为什么还有 216 条坐标非 WGS84？**
餐厅 68、酒店 24、POI 117、景点 7 缺坐标或基准不明；不用异店/邻近点顶替，所以留 unknown，规划时被 `checker_requires_wgs84` 阻断。

**Q20：96 题怎么保证不是挑简单的？**
三层各 32，覆盖五城与 20 条串联；候选从真实数据按规则抽，景点按距离聚类；失败题（20 blocked + 4 infeasible）全部保留，没有替换成简单题。

**Q21：human 题是真人写的吗？**
不是。是研究者构造的自然表达（含老人、预算、半天、雨天），用于测「非结构化表达」；报告里明确标注，不冒充真人语料。

**Q22：为什么天气只有 4 天？**
高德预报窗口就是 4 天；任务日期都安排在窗口内。更远日期只能留缺口或改用气候估计，不能编造。

**Q23：为什么高德不给营业时间/票价？**
高德 POI 是地图数据，不是票务/运营方；v5 place 只给坐标与分类，v3 detail 偶有 `opentime2`；票价不在高德能力内。

**Q24：城际为什么不用实时接口？**
项目没有合规的城际实时票务源；v4 的 74 条火车/64 条航班是冻结时刻表，足以排时段，但不能保证余票/停运。

**Q25：35 段步行是不是失败？**
不是。被高德判定「无需公交」的相邻段距离都 ≤1.5 km，按 4.5 km/h 估算步行是合理的；计划里标 `walk`，不计为失败。

**Q26：预算怎么算？**
门票×人数 + 午饭×人数 + 酒店 + 城际×人数 + 市内公交票价×人数；未知价格直接判 blocked，不用 0 或平均值。

**Q27：结果能复现吗？**
能。`p31_prepare → static → retrieve → detail → finalize → validate` 全脚本；响应文件按 `uid/req_id` 落盘，重复运行会跳过；manifest 记录所有文件 SHA256。

**Q28：子代理之间怎么隔离？**
每个 worker 只写自己的目录，读 P29/合约；根代理统一合并、审计、剔除。是角色/文件边界，不是 OS 沙箱。

**Q29：和 ChinaTravel 官方 benchmark 什么关系？**
扩展 schema 保留原框架的 itinerary/activity/价格/交通结构，但不冒充官方评分；官方 checker 不注入、不改文件；原生投影单独导出。

**Q30：最大的缺口是什么？**
一句话：**静态数据能告诉你「有什么、大概多少钱、几点开」，但不能告诉你「今天开不开、现在多少钱、还有没有票」**。价格与营业时间的「来源明示」通道、酒店动态房价、城际实时班次，是下一步最该补的三件事。

**Q31：14,057 与 1,914 是什么关系？**
前者是扩容候选库（Overture + 业务补全，30 城），后者是五城 ChinaTravel 原生参考库；五城库从前者与旧库抽取并补采到七表字段。二者不是同一层，不能拿 14,057 说「五城有 1.4 万条」。

**Q32：easy 全过，是不是题太简单？**
easy 是对照组：只测「字段完整的单城两景点」能否被静态数据 + 路线/天气支撑。它全过说明数据基础可用，不说明规划能力；hard/human 才是难点，分别只有 19/32 与 21/32。

**Q33：为什么没有测酒店库存、餐厅排队？**
结构里保留了相关字段，但没有合规的库存/排队数据源；P24 也主要覆盖景点与交通。本轮只对酒店价格与存在做校验，库存与排队属于动态能力边界，已在第 6 节列明。

**Q34：许可表为什么 `allowed` 这么多？同一网站为什么既有 `odbl` 又有 `unknown`？**
表统计的是 3598 条 evidence；`allowed` 1934 中 1903 是本地派生占位（不是外部内容），真正网页 `allowed` 只有 31 条。`unknown` 554 是网页未声明许可，默认不可再分发。同一 host 标注不一致（Nominatim 54 odbl/41 unknown、Overture 31 allowed/28 unknown、Wikidata 实体页 28 unknown）说明许可是各 worker 各自打的，缺 host 级统一登记表——这是已知缺陷，修复方式是「host → 许可」中心表 + 全量重标。

---

## 13. 文件索引

| 路径 | 内容 |
| --- | --- |
| `报告/24_五城数据采集完整汇报.md` | 五城采集最终态总账 |
| `报告/25_五城96题分层测试.md` | P31 测试报告 |
| `data/five_city_reference_v4_20261026/` | 1914 条记录、证据、TAG、原生导出 |
| `results/p31_five_city_96/tasks/` | 96 题 |
| `results/p31_five_city_96/retrieval/` | 450 条响应 + 18 条详情 + 账本 |
| `results/p31_five_city_96/final/` | 96 份最终计划与检查 |
| `results/p31_five_city_96/evaluation_all_96.csv` | 逐题评估 |
| `results/p24_dynamic_feedback/` | P24 96 题与 192 份稿 |
| `results/p27_focused_deep_retrieval/` | P27 三任务深挖 |
| `src/shorttrip/expansion_contract.py` / `freshness.py` | 字段表、校验门、TTL |
| `scripts/p30_build_five_city.py` / `p31_*.py` | 合并器与测试脚本 |
