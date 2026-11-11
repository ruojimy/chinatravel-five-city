# SourceCapabilityMatrix — 数据源授权与字段能力（实测）

> 生成日期：2026-10-21　｜　实测依据：`results/baidu_path_probe.json`、`results/baidu_field_inventory.json`、`results/baidu_raw/`
> 规则：**没有实测过的字段一律标 `unavailable / unverified`，不写"应该可以"。**

## 1. 逐源矩阵

| 维度 | 百度地图 Place API（v2） | 高德 Web 服务 | Wikipedia / Wikidata | OpenStreetMap (Nominatim) | 授权评论语料 | 人工标注 |
| --- | --- | --- | --- | --- | --- | --- |
| 授权依据 | 开放平台服务条款 + AK/SK | 开放平台服务条款 + key | CC BY-SA 4.0 / CC0 | ODbL | 未取得 | 本项目自建 |
| 认证方式 | **SN（MD5）已实测通过** | key 直传 | 无 | 无 | — | — |
| 端点可用性 | `/place/v2/search` = 0；**`/place/v3/search` = HTTP 404** | `/v5/place/text` 等可用 | 可用 | 可用 | — | — |
| POI 身份 | ✅ uid / 名称 / 地址 / 省市区 | ✅ | 部分 | ✅ | — | — |
| 坐标 | ✅ GCJ-02（`ret_coordtype=gcj02ll`），原生 BD-09 | ✅ GCJ-02 | ✅ | ✅ WGS-84（需转换） | — | — |
| 类别/权威标签 | ✅ `tag` / `classified_poi_tag` / `label` / `scope_grade` / `scope_type` | ✅ `type` | 部分（分类语句） | ✅ `tourism=*` | — | — |
| 营业时间 | ✅ `shop_hours` + 结构化 `regular_open_hour`（含闭馆日） | ✅ `opentime_week` | 文本中偶见 | ✅ `opening_hours`（中文景点覆盖率低） | — | — |
| 票价 | ✅ 仅 `/place/v2/detail` 返回 `price` | ✅ `cost` | 文本中偶见 | ✅ `fee`（稀疏） | — | — |
| 平台评分 | ✅ `overall_rating`（如 4.6） | ✅ `rating` | — | — | — | — |
| 评论数量 | ⚠️ `comment_num`，**在 200 处封顶**（广州塔与故宫同为 200），只能作序数分桶 | — | — | — | — | — |
| **游客体验标签** | ⚠️ `content_tag`（UGC 衍生词表，如「适合亲子」「提供无障碍设施」「人气旺」）；**无单条评论、无投票数、无时间戳** | ❌ | ❌ | ⚠️ `wheelchair` 等，中国景点极稀疏 | ✅（本该是主力，**不可用**） | ⚠️ 主观，需标注人 |
| **建议游玩时长** | ❌ **接口不提供** | ❌ | ❌ | ❌ | — | — |
| 每分钟/每日配额 | 个人认证配额，**2026-10-21 已接近耗尽** | 有配额，3 把 key 轮换 | 礼貌使用 | ≤1 rps | — | — |
| 是否允许缓存 | 允许（本项目落盘 7 天 TTL + 夹具） | 允许 | 允许（署名） | 允许（ODbL 署名） | — | — |
| 可否长期落库 | ✅ 派生标签 + 来源 URL + 响应摘要；**不落原始评论（本就没有）** | ✅ 同上 | ✅ 需署名 | ✅ 需署名 | ❌ | ✅ |
| 可否再分发/发表 | ⚠️ 仅聚合派生统计；原始响应不发表 | ⚠️ 同上 | ✅ 署名后可 | ✅ 署名后可 | ❌ | ✅ |
| 隐私 | 无用户个人信息 | 无 | 无 | 无 | — | 需匿名化 |
| 验证时间 | 2026-10-21 | 2026-10-17（沿用） | 连通性已验证 | 2026-10-21 连通性验证 | — | — |

## 2. 结论（写进报告时必须保留的句子）

1. **百度 Place API 不是游客评价 API。** 它能给"这家景点是什么、几点开、多少钱、平台打几分、平台给它挂了哪些体验词"，不能给"游客具体说了什么、多少人这么说、什么时候说的"。
2. **`content_tag` 是唯一的体验通道，且无法审计其聚合方法。** 因此它的置信度上限是 `0.55 × 短语强度`，拥挤/排队类还要再乘 0.7 并落 quarantine（缺语境）。
3. **`comment_num` 不能当评论数用。** 两个不同量级的景点都返回 200，说明它是封顶值；本项目一律转成 `>=200(capped)` 分桶。
4. **接口不提供建议游玩时长。** 沙盒里的 `recommendmintime` 只能来自沙盒自身，不能声称来自百度。
5. **`visitor_feedback`（授权评论语料）通道保持为空。** 这是本阶段最主要的数据缺口，也是"体验 TAG 只覆盖 2 个 POI"的根因之一（另一个是配额）。

## 3. 复现命令

```powershell
cd reproduction
$env:PYTHONUTF8='1'
# 离线：读夹具，零配额
.\.venv\Scripts\python scripts\check_baidu_replay.py
# 在线：仅配额恢复后执行，会消耗配额
$env:BAIDU_OFFLINE='0'
.\.venv\Scripts\python scripts\probe_baidu_paths.py
.\.venv\Scripts\python scripts\probe_baidu_fields.py
```
