# Dataset Card — 五城 ChinaTravel 静态参考库 v4

## 1. 概要

| 项 | 值 |
| --- | --- |
| 版本 | `five_city_reference_v4_20261026` |
| 城市 | 西安、厦门、宁波、长沙、青岛 |
| 表 | 景点、餐厅、酒店、POI、地铁站、城际火车、航班 |
| 记录 | 1,914 |
| 证据 / claim / TAG | 3,598 / 5,790 / 6,072 |
| 全字段非空 | 1,607 |
| 构建时间 | 2026-10-26T03:01:42Z |
| 来源 catalog SHA-256 | `58a368a7d3d8ec66208fc7a42da3556b44f5b299b7fed849de32c868003dbdac` |

## 2. 结构与字段

- 原生字段严格按 `src/shorttrip/expansion_contract.py` 的 `FIELDS`；
- 景点 10 字段、餐厅 9、酒店 8、POI 2、地铁 3、火车 8、航班 7；
- 时间 `HH:MM`、价格人民币、`Duration` 小时、坐标 WGS84、POI `[lat,lon]`、地铁 `"lon,lat"`；
- 每条记录带 `field_provenance`（逐字段 evidence_id + quote）、`tags`、`scope`、六个时钟、`trust_status`、`entity_verified`、`uncertainty_flags`。

## 3. 证据与许可

- 3,598 条 evidence：1,903 条本地派生（id/映射/换算），1,695 条外部证据；
- 98 个主机标识；Wikidata 998（含地铁 970）、Nominatim 95、Overture 59、visitxian 48、OSM 41、inqingdao 40、nbtour 36 等；
- 许可：allowed 1,934（其中本地派生 1,903，真实网页仅 31）、cc0 970、unknown 554、odbl 95、public_page_reuse_unverified 20、api_terms 14、其他 11；
- **同一 host 存在标注不一致**（Nominatim 54 odbl/41 unknown；Overture 31 allowed/28 unknown），是本版本的已知缺陷；修复需 host 级许可登记表。

## 4. 本发布包的数据处理

- `records.jsonl.gz`：完整 record payload（含短 quote，便于复核）；
- `claims.jsonl.gz`：字段级 claim（含 quote）；
- `tags.csv.gz`：record_id、tag、value、status、policy_id、valid_until；
- `evidence_index.jsonl.gz`：evidence 元数据，**删除 `raw_text`**，保留 `raw_sha256`；
- 原始网页正文不随包发布；需要完整审计时，请在本地用原始 catalog 复核哈希。

## 5. 已知缺口

| 缺口 | 数量/说明 |
| --- | --- |
| `observed_at` 缺失 | 0/1914 有观察时间；只有 3 条 `source_published_at` |
| 实体未核验 | 0/1914 `entity_verified=true` |
| 许可未知 | 554 条 evidence |
| 非 WGS84 坐标 | 216 条（餐厅 68、酒店 24、POI 117、景点 7） |
| 合规拒绝 | 37 个实体（厦门 24、长沙 8、西安 5） |
| 单位异常 | 长沙 `G1692/G1693` `Duration=409` 为分钟 |
| 免费/开放地点 | 票价或营业时间留空（白城沙滩、栈桥、太平老街等） |
| 酒店价格 | 5 家只有协议价/起价，不能当门市价 |

## 6. 使用建议

- **可以**：做静态参考、候选发现、schema/证据链研究、复现报告中的统计；
- **不可以**：当实时价格/营业/余票；把 `reference_only` 当“已验证”；把本包数据再分发给第三方；
- 真实规划需在请求当天补 `observed_at`、价格、营业时间、余票（P31 的动态检索路径）。

## 7. 许可与伦理

第三方来源的权利未随本包授予；`unknown` 许可的证据尤其不能推定可用。代码 MIT，数据仅研究/复现使用。若需公开再分发，请先完成 host 级许可登记与逐条确认。
