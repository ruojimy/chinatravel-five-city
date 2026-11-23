# 数据库说明（openGauss 6 / GaussDB，schema `shorttrip`）

连接：`%LOCALAPPDATA%\ShortTrip\server.env`（`SHORTTRIP_DB_HOST/PORT/NAME/USER/PASSWORD/SCHEMA`），环境变量优先。表结构在 `server/shorttrip_cloud/schema.sql`，`st_meta.schema_version` 记录版本；改表时递增 `db.SCHEMA_VERSION` 并让语句保持幂等。

| 表 | 内容 |
| --- | --- |
| `st_user` | 账号；密码 `pbkdf2:sha256:600000$salt$hex`（与数据库课程大作业相同格式）；`failed_logins`/`locked_until` 实现 5 次锁 15 分钟 |
| `st_session` | 只存 token 的 SHA-256；30 天滑动过期；`client` = pc / android |
| `st_audit_log` | 注册、登录、失败、锁定、改密 |
| `st_blob`, `st_blob_chunk` | 按 SHA-256 去重的文件内容，4 MB 一块 BYTEA |
| `st_snapshot`, `st_snapshot_file` | 数据快照版本与文件清单；`derived_from = gunzip:<path>` 表示由 .gz 还原 |
| `st_catalog_record`, `st_catalog_tag` | 按快照查询地点、交通目录和标签 |
| `st_catalog_quarantine` | 字段缺失、证据不足或无法核对的行。按 `snapshot_id, city, kind` 筛选，`reasons` 是原因代码的 JSON 数组，`payload` 保留源行或原始字段及来源 |
| `st_catalog_reference` | 有明确证据的参考条目，保留原隔离原因并标记预算和排程限制 |
| `st_catalog_browse`, `st_catalog_pending` | 查询入口。前者合并目录和参考条目，后者显示仍待补证的条目 |
| `st_release` | 发布版本：使用的快照、APK 的 SHA-256/大小/versionCode、默认服务器地址 |
| `st_trip_request` | 需求（出发地、目的地、天数、人数、原话） |
| `st_trip_job` | 规划任务、标题、状态、发起客户端 |
| `st_itinerary_edit` | 行程修改及是否采用 |
| `st_object_file` | 规划器 `result/` 目录的镜像（scope: tripspec/manual/inputs/edits） |
| `st_feedback` | 采用意向评价 |

常用查询：

```sql
-- 某城市的景点
SELECT name, payload FROM st_catalog_record WHERE snapshot_id='5e0ee8a' AND city='杭州' AND kind='attraction' LIMIT 20;
-- 各账号规划次数（区分电脑/手机）
SELECT u.username, j.client, count(*) FROM st_trip_job j JOIN st_user u ON u.id=j.user_id GROUP BY 1,2;
-- 存储去重效果
SELECT id, round(total_bytes/1048576.0,1) AS 原始MB, round(stored_bytes/1048576.0,1) AS 新写入MB FROM st_snapshot;
```

`python -m shorttrip_cloud status` 打印上述概况；`create-user <名> --admin`（密码取 `SHORTTRIP_NEW_PASSWORD` 或交互输入）在关闭注册时开账号。

## V20 西安与厦门目录

`6de12f4` 的数据来自已安装的 V20 快照。首次恢复快照后，用发布目录的虚拟环境 Python 跑 `scripts/import_v20_city_catalog.py --release <发布目录>/ShortTrip`。加 `--check` 可先检查数据和统计，加 `--report <路径>` 可导出按城市、类型和隔离原因统计的 JSON。重复执行会对照已入库的记录、标签和批次收据。批次收据位于 `st_meta` 的 `city_catalog_v20_xian_xiamen`。

景点和餐饮采用快照的营业时间、位置和 POI 绑定检查，另外检查票价或餐费及景点游览时长。酒店要求有依据的价格、计价单位和床数。厦门历史展示价和假定一床的信息随原行保留在隔离表。POI 是位置索引，关联到被隔离实体的索引同样隔离。地铁按线路和站点成员记录，缺线路名的记录隔离。

按日期保存的报价使用 `train_observation` 或 `flight_observation`，保留日期、席别与来源。`train` 和 `flight` 保存冻结的班次参考。两城之间的同向班次只存一条，`city` 归到起点，`payload.data` 同时保留起点和终点。P042 的产品层规划城市范围独立管理。

## 查询免费景点和厦门酒店历史证据

在基础目录导入后，用同一虚拟环境 Python 执行 `scripts/extend_v20_city_references.py --release <发布目录>/ShortTrip --report <输出.json>`。该批次校验 V20 文件。已有兼容格式的本地酒店观察时可通过 `--hotel-observations` 指定证据目录。入库收据记录在 `st_meta.city_catalog_v20_references`。`st_catalog_browse.entry_scope` 为 `reference_only` 时，可查询原始票价、历史报价或房型来源，排程和预算须使用符合实际条件的数据。

免费范围按 [V20 公共区域证据](v20-free-public-spaces.json) 或 V20 明示的零票价记录。公园、广场、海滩、街道和公共步道的基础入场可按 0 元作目录参考。只有名称和分类均符合的公共户外范围适用，已有收费、经营设施及明确限入的记录保持源口径。按实体 ID 和名称绑定，只填基础入场费，游览时长和未核实位置保留原状态。涉及鼓浪屿时保留轮渡与收费景点的范围说明。景点名称与 POI 绑定及位置均通过核对时，票价、营业时间或建议游览时长缺失的记录可加入查询参考。缺失字段保持原值，且明确标记为未确定的预算或排程条件。未核对的位置、禁止进入的地点和明显非景点条目保留在待补证目录。

住宿历史证据按酒店 ID 和名称绑定，展示价、房型配置和预订观察各自保留。床数假设与不明单位的报价不投影到酒店的预算字段。
