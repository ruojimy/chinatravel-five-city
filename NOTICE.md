# NOTICE — 来源、许可与数据边界

## 1. 上游代码与数据

| 上游 | 用途 | 许可 |
|---|---|---|
| [LAMDA-NeSy/ChinaTravel](https://github.com/LAMDA-NeSy/ChinaTravel) | 框架、原生 10 城沙盒（release 2026.08.2）、官方题集、评估器 | 代码 MIT；数据集 CC BY 4.0（上游 commit `f445e00` 声明） |
| [Paddington633/ShortTrip](https://github.com/Paddington633/ShortTrip) | C 组规划/翻译/DFS/软评分/官方三关 | MIT |

本仓库保留了两者的 `LICENSE` 与 README；`ShortTrip-upstream/` 含本仓库的沙盒、动态证据与评分修复，
所有新增脚本、规则规划器、打包文档按 MIT 发布（见 `LICENSE`）。

## 2. 本仓库新增数据

| 数据 | 来源与处理 | 发布边界 |
|---|---|---|
| `data/catalog_v1_1_20261022/` | 在高德/百度/携程/大众点评等公开页面采集后结构化，逐字段带来源与抓取时间 | 只保留结构化字段与来源索引；不含原始网页正文。第三方权利未授予，仅供研究复现 |
| `data/xian11_merged_sandbox/` | snapshot_v17 + 数据分级标准 v1；含地铁/跨城/POI | 同上；price 字段有已知缺口（景点 12.3%） |
| `data/query_sets/`、`data/datasets/` | 原生题集为官方数据；xian11 题集为本项目合成/人工构造 | 官方部分 CC BY 4.0；xian11 部分随本仓库研究使用 |
| `results/p34_v2_planner/` | 规则规划器在官方 604 题上的输出 | 与代码同许可 |
| `data/sandbox_profiles/xian_n16v2/` | 十一城脱敏快照，含有限来源响应和字段证据 | 仅供研究核验；第三方权利未授予，实际价格、时段和库存需重新查询 |
| `data/observations/` | 指定日期的铁路摘要及航班参考页面 | 含第三方页面；不授予第三方内容再分发权或保证当前有效 |
| `results/g3-20261116/` | 十一城样本与规则对照的脱敏逐题记录 | 源文件与公开副本哈希分别保存；不等同逐字节公开原件 |

## 3. 明确不做的事

- 不提供实时价格/库存/班次保证；所有值都是**静态快照**。
- 不授予任何第三方网站内容的再分发权；需要商用请自行逐条确认来源许可。
- 不应提交 API key、cookie 或登录态；`.secrets/` 与 `.env` 已 gitignore，新增证据公开前须另行扫描与脱敏。

## 4. 引用

若用于课程/论文，请引用本仓库，并同时引用 ChinaTravel 与 ShortTrip 上游工作。
