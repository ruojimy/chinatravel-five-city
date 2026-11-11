# 字段可用性阶段 · 定时批次规程

工作目录：`C:\Users\xiech\Downloads\计算机软件工程概论\reproduction`
目标文件：`collector_agent/xian_single_city/field_targets.json`

## 0. 每轮第一步

```powershell
.\.venv\Scripts\python.exe scripts\xian_field_campaign.py status --snapshot <最新快照 catalog.sqlite3>
```

`complete=True`（三类 L1 齐备各 ≥ 300）→ 跑一次全量 `xian_verify.py`，写最终报告，把本自动化置为 `PAUSED`，不再采集。

否则继续本轮。

## 1. 口径（不要自行放宽）

- **L1 静态可复核字段**：景点 `lat/lon/type/opentime/endtime`；餐饮 `lat/lon/cuisine/opentime/endtime`；住宿 `lat/lon/featurehoteltype`。
- **L2 运行时依赖**：`price`、`numbed`、房态、库存、天气。按项目 TTL 规则（price TTL 86400s、inventory 300s）**不在静态快照固化**，不要用 API 里的价格去凑 L1，也不要把「缺票价」说成不可用。
- **全部原生字段齐备**只是报告指标，不是完成门槛：`id` 是供应商数值主键、`numbed`/推荐时长等无法从 POI 接口合规取得。
- 字段可用 **不等于** 官方 checker 三关通过；冻结快照 `planning_ready` 恒为 0，报告里必须写明。

## 2. 每轮流程

1. `xian_campaign.py open --note "字段可用性第 N 轮"` 开新 run（绝不覆盖旧快照）。
2. 按 status 的 `delta` 挑 2–3 个缺口最大的类，分别跑：

```
.\.venv\Scripts\python.exe scripts\xian_field_campaign.py enrich --snapshot <最新快照> --run results/<run_id> --kind <kind> --offset <N> --limit 80 --max-calls 80 --sleep 0.7
```

`offset` 用该 kind 的 `pending_records` 里尚未处理过的顺序推进（每轮递增 limit，避免重复打同一批）。单轮总调用 ≤ 240。百度 `place/v2/search` + `place/v2/detail` 为主，高德 `business` 兜底；凭证只从 `.secrets` 读，日志 `[REDACTED]`，配额失败即停、不换 key。

3. 主代理验收：合并各 `enrich_*.jsonl`，人工抽检至少 3 条（quote 逐字、单一营业区间、无 `24:00` 非法时钟、平台标签未被当数值）。

**身份匹配的两条合法路径**（不要混用）：
- `identity_basis=name`：记录名逐字出现在原始响应里；
- `identity_basis=coordinate_match`：名称写法不同，但把百度 BD09 坐标转成 WGS84 后与记录坐标相差 ≤ 200 m，脚本会在 evidence 里写 `identity_distance_m`，审计对此单列 `coordinate_identity` 计数、不算硬失败。
任何一条都不满足就跳过并记 `name_not_in_raw`，**不许拿第一个搜索结果硬套**。第一轮实测有 28 个字段因此被审计硬门拦下并回滚，这是验收起作用的正常表现，不是要放宽校验。
4. 入库（只补空字段，不覆盖已有值）：

```
.\.venv\Scripts\python.exe scripts\xian_ingest.py --parent <最新快照> --out results/<run_id>/snapshot_v1 --items <空文件> --enrich staging/reviewed/enrich_all.jsonl
```

若没有新实体，`--items` 传一个空 jsonl 即可（`accepted=0` 是正常的，本阶段看 `enrichment.fields`）。

5. **必须跑审计**：`xian_verify.py --snapshot <新快照>`。`hard_failures > 0` 或本批引入 `fails_contract` 时记 `blocked`，下一轮先修数据。
6. 写 `report.md`（本轮调用数、补字段数、L1 前后对比、拒收原因、审计三组数）、`next_queue.json`、`pass_01.json`，再 `xian_campaign.py close`。

## 3. 硬边界

- 只读 `data/`、`ChinaTravel/`、旧 `results/`；新产物只写新 `results/<run_id>/`。
- 不编价格、房型、床数；名称匹配不上就跳过并记 `no_exact_name_match`，不许拿第一个搜索结果硬套。
- 中文参数写 UTF-8 文件再引用；不调用 `claude` CLI（本机 403）。
- 子代理若用于静态页，按 `worker_policy.json` 用 `model=auto` / `mode=auto`，只写各自 staging；主代理验收标准不随模型变化。

## 3.5 OTA 登录态路线：已试点，勿重复

2026-11-06 实测（详见 `results/xian_claude_20261106_232815/report.md`）：大众点评登录态有效，但 20 次只读尝试 **0 条可入库**；美团入口不可用。原因：商户详情页触发点选验证（脚本按边界不自动过）、详情页只给「开始营业」不给结束时间、结果卡片名称匹配率 1/10 且推荐位会张冠李戴、菜系词来自导航栏不能当事实。

因此**字段自动化不要调用 `xian_ota_collect.cjs`**，也不要提示用户重新扫码，除非用户明确要求再次试点。补字段优先用携程公开详情页（免登录、原始 HTML 逐字含营业区间）或调整 L1 口径。

## 3.6 携程公开页（免登录）：已试点，仅作低优先级补充

2026-11-07 实测（`results/xian_claude_20261107_000146/report.md`）：`scripts/xian_ctrip_collect.py` 抓 4 个列表页 → 89 个详情链接 → 9 条候选 → 主代理严格验收后 **3 条**可入库，景点 L1 24→27，审计 0 硬失败。剔除原因：4 条身份近似误配（西安城墙-长乐门、大雁塔↔大雁塔北广场等）、2 条旺淡季多时段歧义。

**覆盖率 3/730 ≈ 0.4%**，靠它把 L1 推到 300 需要 8,000 次以上详情页请求，不现实。因此：
- 每轮最多跑 10 个携程链接，只补标题与记录名完全一致、且页面内营业区间唯一的条目；
- **不作为达标主路径**，也不要为了凑数放宽名称匹配或猜旺淡季时段；
- 若连续几轮无增量，直接跳过携程，不要反复压公开站点。

## 4. 每轮报告格式

`景点 L1 a/300、餐饮 b/300、住宿 c/300`，附本轮补字段数、审计结论（本地可复核 / legacy / 硬失败）与剩余缺口。
