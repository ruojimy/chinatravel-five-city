# 西安单城采集 · 定时任务提示（WorkBuddy 调度）

工作目录：`C:\Users\xiech\Downloads\计算机软件工程概论\reproduction`
每轮只做**一个批次**：开新 run → 子代理采集 → 主代理验收 → 入库新快照 → 报告 → 收尾。
**目标**：三类 discovery + 交通规模同时达到 ChinaTravel 单城水平（`targets.json`）：
景点 341 / 餐饮 466 / 住宿 387；
POI 1217 / 地铁站线 364 / 列车 407（9 对城市双向）/ 航班 160。
未达到就继续，不做“差不多收工”的判断。

---

## 0. 每轮开始必做

```powershell
cd C:\Users\xiech\Downloads\计算机软件工程概论\reproduction
.\.venv\Scripts\python.exe scripts\xian_campaign.py status
```

- `complete: True` → 停止采集：用 `automation_update` 把本自动化置为 `PAUSED`，写最终报告，逐项列出三类 discovery/原生齐备/层3 与四类交通的目标和实际数，不得虚报。
- 否则继续。读 `collector_agent/xian_single_city/RESUME_XIAN.md`、上一轮最新 `next_queue.json`、`report.md`、`quarantine.jsonl`，再读 `targets.json` 确认差额。

## 1. 硬边界（违反即作废，不是“可商榷”）

- 只读：`data/`、`ChinaTravel/`、`results/xian_claude_20261106_*`、`results/weekly20_*`。**不覆盖任何旧快照**；每轮新建 `results/xian_claude_<YYYYMMDD_HHMMSS>/`。
- 暂停家族**不访问、不换路**：`xa.gov.cn`(403)、`people.com.cn`、Overture、Wikidata、visitxian。
- **高德/百度 API 已获用户授权**（2026-11-06）：允许调用、允许持久化 POI 与坐标。凭证只从 `.secrets/amap.key`、`.secrets/baidu.key` 读取，**不得打印、不得写入日志/报告/产物**；日志里必须显示 `[REDACTED]`。配额失败就停该 provider，不换 key、不换账号、不加 UA 绕行。
- 不用摘要充当原文；不编字段值；未知一律 `null`，不补时分秒/时区。价格、营业时间、坐标缺证据就留空。
- 公告落款往往只有日期：日期不是时钟，写进 `source_published_at` 会被 `validate_record` 拒（`invalid_clock`）。入库脚本已把纯日期转存到 `source_locator.date_text`，时钟字段留 `null`。
- 不调用 `claude` CLI（本机网络 403，`model_not_found`/region blocked），采集由本轮子代理完成。
- 中文参数不进命令行；需要传中文时写 UTF-8 文件再引用路径。

## 2. 子代理（模型配置读 `worker_policy.json`）

开子代理前先读 `collector_agent/xian_single_city/worker_policy.json`，按其中的 `model` / `mode` 启动 2–3 个 `general-purpose` 子代理。当前值是 **`model: auto` + `mode: auto`**（2026-11-06 用户指示：接下来几轮不再固定 `lite`；实测 `model: auto` 在本环境可用）。每个子代理领一个**有界工单**（一个 kind × 一个区县或一个来源家族），互不重叠：

- 只允许写自己的 `results/<run_id>/staging/<worker>/`；禁止写 `data/`、主库、脚本、其它 worker 目录。
- 每个 worker 交付 `raw/`（用 `curl` 保存的**原始页面字节**，不是 WebFetch 摘要）+ `claims.jsonl`。
- 单个 worker 上限 **6 个原始页面**；同一来源家族不得并发；遇到 403/验证码/限流 → 记录失败并**暂停整个家族**，不换子域、不换 UA、不换工具重试。
- `claims.jsonl` 每行一个候选实体：

```json
{"kind":"restaurant","name":"长安大排档","aliases":["长安大排档(钟楼店)"],
 "data":{"district":"碑林区","address":"…","price":78,"cuisine":"陕菜","opentime":"10:00","endtime":"22:00","lat":null,"lon":null},
 "source":{"url":"https://…","publisher":"…","authority":"government_published_list","licence_status":"public_official_notice","trust_status":"official_listing","published_at":null,"observed_at":null},
 "evidence":{"raw_path":"results/<run_id>/staging/w1/raw/xxx.html","quote":"页面里的逐字原句","locator":"第3张表第2行"},
 "notes":"口径/冲突/存疑"}
```

`authority` 取值示例：`government_published_list`、`municipal_culture_tourism_bureau_public_table`、`official_agency`、`aggregator_user_generated`（后者 `trust_status` 必须是 `reference_only`）。
`quote` 必须是 `raw` 文件里能逐字找到的原句；名称本身也必须出现在原文里，否则入库会被拒。

## 2.5 API 采集（比网页快，优先用）

```
.\.venv\Scripts\python.exe scripts\xian_api_collect.py --run results/<run_id> --worker api_amap
  --source amap --kind poi --query "钟楼" --query "大雁塔" --pages 2 --page-size 25 --max-calls 20
```

- `--source amap`（GCJ02）或 `baidu`（BD09），脚本自动转 WGS84 并在 notes 里记录转换；`--kind` 支持 `poi / metro_station / attraction / restaurant / accommodation`。
- 每次调用都落 `raw_api/*.json`（原始字节 + sha256）并写 `api_log.jsonl`；`quote` 取实体名，入库门会核它在原始 JSON 里逐字存在。
- 单轮预算：高德 ≤ 60 次、百度 ≤ 40 次；命中配额码或 `status!=0` 立即停并记 `stop_reason`，不重试、不换 key。
- 地铁站按“站名+地铁站”查，入库时 `-地铁站`、`(地铁站)` 后缀会被归一去重。
- 列车/航班没有 place 接口：列车走 12306 会话（见下），航班走航司/机场公开时刻表。

## 2.6 列车：12306 半自动会话

- 登录（用户扫码一次）：`node scripts\xian_12306_login.cjs`，浏览器打开 12306，检测到 `tk` cookie 后把会话写进 `.secrets/12306_state.json`。**这一步必须由用户完成，脚本不做验证码绕过。**
- 采集（复用会话）：`node scripts\xian_12306_query.mjs --run results/<run_id> --dates 3`，按西安 2 个站 × 9 个原版城市双向逐日拉取，原始 JSON 落 `raw_api/`，输出 `staging/api_12306/items.jsonl`。
- 退出码 3 = 会话失效，在报告里写“需用户重新登录”，不要重试、不要换账号。
- 余票接口不给票价，`Cost` 留 null；`Duration` 由「历时」换算成小时。

## 3. 主代理验收（这是唯一的入库口）

子代理交回后，**你**逐条验收，不看它自己的结论。**子代理换成 auto 不改变任何验收标准**：`xian_ingest.py` 的原文/引文/哈希/契约校验和 `xian_verify.py` 的审计一律照旧，不因模型变强就放宽。

0. **先去重，再谈新增**。拿候选名跟现有西安记录做包含式比对（`甲 in 乙 or 乙 in 甲`，或前 3 字相同）。已经存在的实体不算新增，改走字段补全（只补空字段，不许覆盖已有值）。2026-11-06 首批实测：9 个官方公告页、8 条候选，只有 1 条是真正的新实体，其余 5 条早已在库里——官方名录的边际收益就是这么低。
1. 抽样人工核对：至少 3 条，打开 `raw` 确认 `quote` 真的在原句里、字段没有被“合理推测”。
2. 跑入库门（会自己复算 `raw_sha256`、校验引文逐字、校验名称在原文、跑 `validate_record`、去重；不合格进 `quarantine.jsonl` 且不计数）：

```powershell
.\.venv\Scripts\python.exe scripts\xian_campaign.py open --note "batch <主题>"
.\.venv\Scripts\python.exe scripts\xian_ingest.py --parent <最新快照 catalog.sqlite3> `
  --out results/<run_id>/snapshot_v1 --items results/<run_id>/staging/reviewed/items.jsonl `
  --enrich results/<run_id>/staging/reviewed/enrich.jsonl --label "<主题>"
```

`--enrich` 只填现有记录的空字段（例如给已有景点补 `type`/`district`），已有值一律跳过并记 `already_known`；它不是“升级等级”的通道，别拿它刷数。

3. 期望是“接受几条就涨几条”。如果 `accepted=0`，不要改脚本放宽校验，改为在报告里写明每条被拒原因（`quote_not_verbatim_in_raw` / `name_not_in_raw` / `duplicate_name` / `validate_record`）。
4. 入库后立刻复核：`xian_campaign.py status` 的 discovery 必须等于上一轮 + `accepted`。
5. **每批必须跑真实性审计**（硬门）：

```
.\.venv\Scripts\python.exe scripts\xian_verify.py --snapshot results/<run_id>/snapshot_v1/catalog.sqlite3
```

它会逐条复算：证据行是否存在、`raw_path` 是否还在且 sha256 一致、`quote` 是否仍逐字在原页、实体名是否在原文、坐标是否落在西安 bbox 且声明了坐标系、同类身份是否重复。
输出三组数：`本地可复核 / 无本地原文(legacy) / 硬失败`。**`hard_failures > 0` 时本批记 blocked，下一轮先修数据，不许继续堆量。** legacy 是早期目录继承的记录（从未本地留原文），只能算“结构通过”，不能算已核实。

## 4. 每轮收尾（必须写）

在 run 目录写：

- `report.md`：本轮 run_id、来源与动作数、`accepted/rejected` 及原因分布、三类 discovery/原生齐备变化、暂停家族、剩余差额。
- `next_queue.json`：下一轮可执行工单（具体 URL 或检索入口 + 目标字段），按可做性排序；不可做的写明阻塞证据。
- `pass_01.json`：`{run_id, pass, state: "checkpoint"|"completed"|"blocked", ready_work: [...], progress_artifact, reason}`。
- `terminal_exit.json`：`xian_campaign.py close --run <dir> --state checkpoint --reason "..." --artifact results/<run_id>/report.md`。

最后用一句话报进度：`景点 a/341、餐饮 b/466、住宿 c/387`，并说明本轮净增与主要阻塞。

## 5. 什么时候算完成

三类 discovery 同时 ≥ `completion_target`，且 poi / metro_station / train / flight 同时 ≥ 交通目标（1217 / 364 / 407 / 160），才算完成。层3（严格规划就绪）因价格/营业时间 TTL 只有 1 天，静态快照下**天然为 0**，只报告不设为目标；原生字段齐备（tier2）持续提升但不作为完成门槛。
