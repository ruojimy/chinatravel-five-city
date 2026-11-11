# 西安数据评级标准 v1（已批准执行）

制定：2026-11-10　适用快照：`snapshot_v14`　覆盖：7 类 4771 条

审批结论（2026-11-10 23:38）：
1. 准入方案 **A**：L1+L2+L3 进沙盒主路径。
2. 餐厅 `cuisine` 降为 **P2**（缺失不阻断，标「未分类」）。
3. **L2 / L3 记录在被访问时默认开启动态搜索**，补进架构（见第四节）。
4. `price` 24h TTL 照此执行。

本标准决定「哪些记录能进沙盒、进去怎么展示」；`quality_model.json` 的 A/B/C/D 证据评级保持独立，对外仍是 64.10%。

---

## 一、要素分层

按「缺失后果」分层，不按主观重要性：

| 层 | 含义 | 缺失后果 | 涉及字段 |
|---|---|---|---|
| **P0 定位** | 能不能上图、算距离 | 无法排程 | `lat` `lon`（POI/地铁为 `position`；火车/航班为 `From` `To` `TrainID`/`FlightID`） |
| **P1 时序** | 能不能判开门/发车 | 解析 `HH:MM` 会崩 | 景点/餐厅 `opentime` `endtime`；火车/航班 `BeginTime` `EndTime` `Duration` |
| **P2 属性** | 筛选与预算 | 可降级展示 | 景点 `type`；餐厅 `cuisine`；酒店 `price`；地铁 `line`；POI 无 |
| **P3 增强** | 体验与推荐 | 不影响可用 | 票价、推荐时长、推荐菜、`featurehoteltype`、`numbed`、`hotelname_en`、房型子表 |

酒店没有 P1：缺价只让预算算不准，不会让程序崩；景点/餐厅缺营业时间则会直接抛异常。这是数据类型约束，不是偏好。

## 二、等级定义

| 等级 | 判据 | 沙盒 | 展示 |
|---|---|---|---|
| **L1 完整可信** | P0+P1+P2 齐，且每个字段 `status=source_value` | 主路径 | 直接展示 |
| **L2 可用待核** | P0+P1+P2 齐，但至少一项为 `derived` / 估算 / legacy | 主路径 | 展示 + 标「参考」+ **强制动态查询** |
| **L3 降级** | P0+P1 齐，P2 缺 ≥1 | 主路径 | 缺项显示「需确认」+ **强制动态查询** |
| **L4 不进** | 缺 P0 或 P1 | `reference_only/` | 仅按名可查 |

## 三、七类要素与条数（v14 实测）

| 类别 | 总数 | P0 | P1 | P2 | L1 | L2 | L3 | L4 | 主路径 | 触发动态 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 住宿 | 761 | lat/lon | — | price | 234 | 84 | 388 | 55 | **706** | 686 |
| 景点 | 757 | lat/lon | 营业时间 | type | 388 | 20 | 0 | 349 | **408** | 20 |
| 餐厅 | 560 | lat/lon | 营业时间 | cuisine | 149 | 22 | 62 | 327 | **233** | 84 |
| POI | 1399 | position | — | — | 1298 | 96 | 0 | 5 | **1394** | 96 |
| 地铁站 | 545 | position | — | line | 474 | 0 | 71 | 0 | **545** | 71 |
| 火车 | 436 | 车次/出发/到达 | 时刻+历时 | — | 423 | 13 | 0 | 0 | **436** | 13 |
| 航班 | 313 | 航班号/出发/到达 | 时刻+历时 | — | 200 | 77 | 0 | 36 | **277** | 77 |
| **合计** | **4771** | | | | **3166** | **312** | **521** | **772** | **3999** | **1047** |

字段覆盖明细：

| 类别 | 关键字段覆盖 |
|---|---|
| 住宿 | 坐标 706/761；price 345（真实 267 + 高置信 78）；`numbed` 761；类型 361 |
| 景点 | 坐标 691；`opentime` 431 / `endtime` 429；`type` 754 |
| 餐厅 | 坐标 541；`opentime` 251 / `endtime` 242；`cuisine` 249 |
| 地铁站 | 坐标 545；`line` 474（71 个换乘站多线路不猜 / 不在线路表） |
| 火车 | 25 条线路 436 班次，7 字段 100%（13 条 Duration 由时刻推导） |
| 航班 | 时刻 296/290，Duration 275（21 缺到达、15 缺起飞 → L4） |
| POI | name+position 1394；96 条 position 为推导值 → L2 |

`reference_only/` 共 772 条：住宿 55（缺坐标）、景点 349（283 缺营业时间 + 66 缺坐标）、餐厅 327、POI 5。

## 四、L2/L3 动态搜索架构（本次新增）

### 触发规则

- 任何 L2/L3 记录被 planner 读取时，**先跑动态查询，再展示值**。
- 结果缓存按类别 TTL；查询成功则用新值覆盖展示，失败则降级为「需确认」，绝不回填估算。
- 每次查询写审计日志 `results/xian_gapfill_20261109/dynamic_log.jsonl`（kind / name / tool / status / ttl / 时间）。

### 记录内嵌字段

```json
"quality_tier": {
  "grade": "L3",
  "exposure": "main",
  "dynamic_fetch": {
    "required": true,
    "trigger": "on_access",
    "tool": "hotel_dynamic_price",
    "ttl_hours": 24,
    "reason": "grade_L3",
    "on_failure": "show_as_unconfirmed"
  }
}
```

`reason` 取 `grade_L2` / `grade_L3` / `ttl_expired`；TTL 过期同样触发。

### 各类对应的 provider

| 类别 | 工具 | TTL | 状态 |
|---|---|---:|---|
| 住宿 | `hotel_dynamic_price`（Trip.com 详情页） | 24h | **已接入**，实测威斯汀 2026-11-11 → ¥732 |
| 餐厅 | `poi_dynamic_lookup` | 168h | 未接入（需高德/美团，配额与风控受限） |
| 景点 | `poi_dynamic_lookup` | 72h | 未接入 |
| 地铁站 | `metro_line_lookup` | 720h | 未接入（本地线路表可离线补） |
| 火车 | `train_schedule_lookup` | 24h | 未接入 |
| 航班 | `flight_schedule_lookup` | 6h | 未接入 |
| POI | — | — | 不需要 |

统一入口：`scripts/dynamic_lookup.py --kind <类> --name <名称> [--checkin --checkout]`。
未接入的来源返回 `status=not_wired` + `display="需确认"`，不会伪造数值。

## 五、时效规则

| 字段 | TTL | 过期动作 |
|---|---|---|
| `price` / `Cost` | 24h | 转 `on_request`，只显示「需实时询价」 |
| `BeginTime` / `EndTime` / `Duration`（航班/火车） | 24h | 触发动态查询 |
| `opentime` / `endtime` | 90 天 | 标「需确认营业时间」，仍可排程 |
| `line`（地铁） | 2 年 | 触发线路查询 |
| `lat` / `lon` / `name` / `type` / `cuisine` | 长期 | 不设过期 |

## 六、已执行清单

| 项 | 产物 |
|---|---|
| 评级脚本 | `scripts/xian_grade_standard.py`（写 `quality_tier`，输出 `GRADE_INDEX.json`） |
| 准入调整 | `scripts/xian11_tier.py: ADMISSION_L1` = P0+P1；餐厅 `cuisine` 降 P2 |
| 动态查询 | `scripts/dynamic_lookup.py` + `dynamic_log.jsonl` |
| 快照 | `results/xian_gapfill_20261109/snapshot_v14/`（含 `GRADE_INDEX.json`） |
| 沙盒 | `data/xian11_sandbox`（attraction 408 / restaurant 233 / accommodation 706） |
| 合并集 | `data/xian11_merged_sandbox`（含 `TIER_INDEX.json`、`GRADE_INDEX.json`） |
| 回归 | A 类 64.10%、`hard_failures=0`、verify 硬失败 0 |
