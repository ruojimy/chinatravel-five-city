# ChinaTravel + ShortTrip 完整实验套件

**10 城原生沙盒 · 12 城冻结评测 · ShortTrip 架构 · 规则规划器 · 高德/百度 API · Luna 对照**

本仓库是本项目（ChinaTravel 静态沙盒 → 扩展数据 → ShortTrip 本地基准）的研究实验套件，
替代此前的「五城静态参考」v1 包（旧内容保留在 [`legacy/five_city_v1/`](legacy/five_city_v1/)）。

> 研究性复现包，不是可商用的旅行数据产品。数据里的价格/营业时间/班次都是**静态参考**，
> 不是实时库存；第三方来源的权利不随本包授予，详见 [NOTICE.md](NOTICE.md)。

---

## ShortTrip 8795 · openGauss 与 Android 2.1

Windows 工作台与 Android 共用账号、行程和旅行数据。安装包导入西安和厦门的 V20 目录，保留参考记录和缺字段的隔离数据。 [下载 Windows 安装包和 APK](https://github.com/ruojimy/chinatravel-five-city/releases/tag/shorttrip-8795-gaussdb-20261123) · [源码和部署说明](apps/shorttrip/)

## 0. 十二城 V20（2026-11-19）

V20 统一西安和厦门的景点类别与菜系读取，补入部分门票、营业时段及 POI 关联，并新增指定日期的跨城班次和展示票价。36 道原题的往返时刻预检从 **30/36** 提升到 **36/36**，城际展示票价在预算内的从 **29/36** 提升到 **35/36**。这些数字仅衡量交通。Luna 行程分数沿用下方 V19 评测。 [V20 逐题结果及数据边界](results/v20-20261119/README.md)

```sh
python -B -X utf8 scripts/g3_sandbox12_repaired_v20.py
python -B -X utf8 scripts/replay_benchmark12_v20.py
```

## 0.1 十二城 V19（2026-11-18）

V19 纳入西安和厦门的历史目录、跨日到达与跨夜退房校验、景区子点判定，以及按精确出发时刻回放的高德接驳。公开快照保留评测所用的标准化字段和证据摘要。历史报价和路线估算适用于本次冻结评测。

Luna 在 36 道 Easy／Medium／Human 题上的首稿为 **11/36**，每题一次反馈修订后为 **23/36**。题目来自 18 道 ChinaTravel 原题模板，每个模板分别改为西安和厦门。人数、天数及原硬约束保留，本批选题侧重预算、住宿与交通。 [逐题记录](results/v19-20261118/luna_v19_standard_36/analysis.json) · [题目来源](results/v19-20261118/luna_v19_standard_36/sources.json)

安装 `requirements.txt` 后，可用以下命令加载 V19 或离线重评一份已提交方案。

```sh
python -B scripts/g3_sandbox12_repaired_v19.py
python -B scripts/replay_benchmark12_v19.py --uid xi-ct-m02 --phase revision --output score.json
```

评测方法、公开文件的校验方式和历史对照见 [V19 评测归档](results/v19-20261118/README.md)。

## 0.2 十一城历史状态（2026-11-16）

十一城 `xian_n16v2` 快照与主沙盒修复已加入仓库，包含西安城际参考、多段接驳检查、日期和席别限定的交通接口及南京南站定向别名核验。默认仍为原生十城；十一城须显式选择 profile。公开快照经过脱敏，与本地冻结评测输入的哈希不同。[使用说明及数据边界](docs/G3_VERIFIED_SANDBOX.md)

同一批十一城样本中，Luna 每类 6 条，严格结果为 easy 2 通过、medium 0 通过、human 2 通过；数据阻塞和待定未计为评分失败。规则器全量 60 题中 4 题通过；规则器能读取硬约束和检查器反馈，Luna 不能。完整分母、条件通过、逐题脱敏记录和哈希见 [评测记录](results/g3-20261116/RESULTS.md)。

## 0.3 历史状态（2026-11-11）

| 项 | 状态 |
|---|---|
| 本地 Qwen3.5-4B Q8 部署 | ✅ 已核验（GGUF hash、`/v1/models` 别名、无 `<think>`） |
| 三组 1/10 基准（G1/G2/G3） | ⚠️ 已启动，**13:03 本机 GPU 黑屏中断，0 题到达终态**；可续跑，见 [事故记录](docs/LOCAL_RUN_INCIDENT_20261111.md) |
| 规则规划器对照组（G1 同一 60 题） | ✅ **31/60 = 51.7%**（easy 18/30、medium 4/15、human 9/15） |
| 规则规划器全量 604 题 | ✅ 324/604 = 53.6%（easy 146/300、medium 69/150、human 109/154） |

本机（RTX 5080 Laptop 16 GB）连续跑 llama.cpp 会触发驱动级黑屏，因此**不把本仓库的产出绑定在这台机器上**：
所有中间状态逐题落盘，换机器/降并发后可原样续跑。

---

## 1. 套件内容

| 路径 | 内容 | 规模 |
|---|---|---|
| `ChinaTravel/` | 官方 ChinaTravel 框架 + **原生 10 城沙盒**（132 文件，release 2026.08.2）+ 官方题集 | 17 MB |
| `ShortTrip-upstream/` | **ShortTrip 架构源码**（规划/翻译/DFS/软评分/官方三关评估） | 2.4 MB |
| `data/catalog_v1_1_20261022/` | **扩展 10 城 catalog**（景点/餐厅/住宿三类实体表，SQLite） | 193 MB → **gz 14.5 MB** |
| `data/xian11_merged_sandbox/` | **第 11 城西安**（v17 快照 + 评级标准 v1，含地铁/跨城/POI） | 5.4 MB |
| `data/query_sets/` | 原生 easy/medium/human、xian11 题集、competition_test | 2.2 MB |
| `data/datasets/` | 偏好/POI 匹配金标/不可行与修复样本 | 1.8 MB |
| `src/shorttrip/` | **规则规划器**（P34 `ConstraintPlannerV2` 等）、TAG/证据/动态检索模块 | 3 MB |
| `scripts/` | 采集、补价、评估、**三组基准 runner**、就绪闸门、汇总 | 3.5 MB |
| `results/p34_v2_planner/` | 规则规划器全量跑分（604 题逐题明细） | 0.4 MB |
| `results/shorttrip-runs/` | 冻结抽样、模型 hash、就绪记录、基准报告 | <0.1 MB |
| `legacy/five_city_v1/` | 旧「五城静态参考」v1 包（西安/厦门/宁波/长沙/青岛） | 5 MB |
| `docs/` | 数据分级标准、房型动态价、来源能力矩阵、基准协议、事故记录 | <0.1 MB |

**没有放进仓库的**：模型权重（4.6 GB，见 §2.2 自行下载）、`.secrets/`（API key）、
`shorttrip-local/`（llama.cpp 二进制）、大体量运行快照（`results/` 原始目录 9.5 GB）。

---

## 2. 快速开始

### 2.1 环境

```bash
python -m venv .venv
# Windows
.venv\Scripts\pip install -r requirements.txt
# Linux/macOS
.venv/bin/pip install -r requirements.txt
```

推荐 **Python 3.12**（3.13 上 `numpy==1.26.4` 无 wheel；本套件在 numpy 2.x 下已验证）。
`ChinaTravel/`、`ShortTrip-upstream/` 也各自带 `requirements.txt`，二者依赖相同。

### 2.2 同款模型（必须一致）

| 项 | 值 |
|---|---|
| 基座 | `Qwen/Qwen3.5-4B` |
| 量化 | `Q8_0` GGUF，`SoAIHQ/Qwen3.5-4B-GGUF` 的 `Qwen3.5-4B-Q8_0.gguf` |
| 大小 / sha256 | 4,610,580,288 B / `5b25856e42534b000b5e06d7cfc10c756931f4dc66a4ca6ef08d835bd233a833` |
| 推理后端 | llama.cpp **b12248**（Windows CUDA 12.4 x64 预编译包） |
| 上下文 | 16K / slot，`-np 6`，`--kv-unified-per-slot 16384` |
| 思考 | `--reasoning off`（服务端关闭，源码零改动） |

```bash
# 目录约定（可用环境变量覆盖，见 .env.example）
shorttrip-local/
  llama-bin/llama-server.exe
  Qwen3.5-4B-Q8_0.gguf
```

### 2.3 起服务与显存

```bash
llama-server -m Qwen3.5-4B-Q8_0.gguf \
  --host 127.0.0.1 --port 18080 --alias qwen3.5-4b-q8 \
  -np 6 --kv-unified-per-slot 16384 -ngl 99 --reasoning off --jinja
```

实测：单份 4.6 GB 权重 + 6×16K KV ≈ **7.9 / 16.3 GB**。
**三组实验共用这一个服务、顺序跑**；不要为每组各起一个模型实例——第二份权重就会把 16 GB 卡压爆。
显存更小的卡：`SHORTTRIP_NP=2..4`、`SHORTTRIP_CTX=8192`，或 `-ngl` 留几层给 CPU。

### 2.4 跑三组 1/10 基准

```bash
# 1) 准备三份独立 checkout + 冻结抽样（G1/G2 共用同一批 UID）
python -B -X utf8 scripts/prepare_shorttrip_runs.py

# 2) 一键：起服务 → 冒烟 → 就绪闸门 → G1 → G2 → G3
python -B -X utf8 scripts/run_shorttrip_benchmark.py --all \
  --accept-coverage "研究者确认：景点 price 12.3% 为已知开放缺口"

# 3) 随时看进度 / 出报告（只读，不干扰长跑）
python -B -X utf8 scripts/summarize_shorttrip_benchmark.py
```

产物：`<SHORTTRIP_RUNS>/G1_native_v*/experiments/c_only/{status,traces,results}/`，
逐题 `status/*.json` 记录官方三关、C 组规则、候选数、失败原因；`traces/*.jsonl` 是完整请求/响应。
**已有 status 或 traces 的题不会重跑**，中断后重跑同一命令即续跑。

### 2.5 规则规划器对照组

```bash
# 全量 604 题（纯规则、0 LLM token）已在 results/p34_v2_planner/
python -B -X utf8 scripts/p35_rule_baseline_1of10.py   # 过滤到与 G1/G2 相同的 60 个 UID
```

---

## 3. 数据层

### 3.1 原生沙盒（G1）

`ChinaTravel/chinatravel/environment/database/`，官方 release **2026.08.2**，132 文件 × 10 城：
北京、上海、南京、苏州、杭州、深圳、成都、武汉、广州、重庆。
七类原生表：景点、餐厅、住宿、POI、地铁、跨城火车、航班。

### 3.2 扩展 10 城 catalog（G2）

`data/catalog_v1_1_20261022/catalog.sqlite3.gz`（`records` 表，JSON payload 带来源/证据/TAG）。
**只替换 attractions / restaurants / accommodations 三类实体表**；POI、地铁、跨城沿用同一官方 release，
因为题目 DSL 会引用精确 `TrainID` / `FlightID`。

```bash
python - <<'PY'
import gzip, shutil
with gzip.open("data/catalog_v1_1_20261022/catalog.sqlite3.gz","rb") as s, \
     open("data/catalog_v1_1_20261022/catalog.sqlite3","wb") as d:
    shutil.copyfileobj(s,d)
PY
```
`prepare_shorttrip_runs.py` 会自动解压；`SHA256SUMS` 同时给出 gz 与解压后 sqlite 的哈希。

### 3.3 第 11 城西安（G3）

`data/xian11_merged_sandbox/`：snapshot_v17 + 数据分级标准 v1（`GRADE_INDEX.json` / `TIER_INDEX.json`）。
已知开放缺口（**必须在报告里披露**）：景点 price 112/908 = 12.3%、餐厅 561/807 = 69.5%、
住宿 375/929 = 40.4%。补价脚本只覆盖餐厅，景点票价没有公开源。

### 3.4 题集

| 题集 | easy | medium | human | chain | 合计 |
|---|---:|---:|---:|---:|---:|
| 原生 10 城 | 300 | 150 | 154 | — | 604 |
| xian11 | 30 | 15 | 15 | 30 | 90 |

`chain` 是 `shorttrip-dynamic-v1` 多城串联契约，**与 ShortTrip 单目标规划器不兼容**，只登记不计分。

---

## 4. 高德 / 百度 / DeepSeek API

代码里没有任何真实 key。凭证只从两处读：

1. 环境变量：`AMAP_KEY` / `AMAP_KEYS` / `BAIDU_AK` / `BAIDU_SK` / `DEEPSEEK_API_KEY`
2. 仓库根的 `.secrets/`（已 gitignore）：`amap.key`、`amap.keys`、`baidu.key`、`deepseek.key`

```bash
cp .env.example .env      # 填入自己的 key；注意 .env 已在 .gitignore
```

| 客户端 | 入口 | 用途 |
|---|---|---|
| 高德 Web 服务 | `src/shorttrip/live_amap.py`、`scripts/probe_amap.py` | POI/路径/营业时间/动态价，默认预算 4 次/题 |
| 百度 Place API 3.0 | `src/shorttrip/dynamic/baidu.py`、`scripts/probe_baidu.py` | 实体核验、SN 签名、字段补全 |
| DeepSeek | `scripts/probe_deepseek_search.py` 等 | 动态检索/翻译兜底（基准实验**不用**云端 LLM） |

> ⚠️ 旧工作副本里曾有两处硬编码高德 key，发布前已改为读环境变量/`.secrets`。
> 如果你的 key 曾出现在任何提交/压缩包里，请到高德控制台**轮换**。

---

## 5. 架构与基准协议

ShortTrip 的 C 组流程：自然语言 → 约束程序（LLM 翻译 + 程序校验）→ DFS 逐 POI 搜索
（真实交通/营业时间/用餐窗口约束 + 软评分）→ 候选池 → 官方三关（schema / commonsense / hard）
+ C 组扩展规则审计。

三组对照（固定 seed 20261111，1/10 分层抽样）：

| 组 | 数据层 | 题集 | 题数 |
|---|---|---|---:|
| **G1_native** | 官方原生 10 城沙盒 | 原生 604 × 1/10 | 60（30/15/15） |
| **G2_ext10** | 我们的 catalog_v1_1（10 城） | **与 G1 同一批 60 个 UID** | 60 |
| **G3_ext11** | G2 + 西安 | xian11 90 × 1/10 | 9（3/3/3） |

- 「除扩展数据集外都用 ShortTrip 架构」：只换 `database/{attractions,restaurants,accommodations}/<city>/*.csv`；
  规划、翻译、DFS、软评分、评估全部是上游原码。
- 单题预算保持上游默认：墙钟 1800 s、候选目标 20、`max_tokens=4096`、请求超时 600 s。

---

## 6. 结果

### 6.1 规则规划器（P34 ConstraintPlannerV2，0 LLM token）

| split | 1/10 子集（与 G1/G2 同 UID） | 全量 |
|---|---:|---:|
| easy | 18/30 | 146/300 |
| medium | 4/15 | 69/150 |
| human | 9/15 | 109/154 |
| **合计** | **31/60 = 51.7%** | **324/604 = 53.6%** |

### 6.2 LLM 三组

本机在 G1 第 1 波 6 题仍在搜索阶段时黑屏中断（13:03），**没有可报告的通过率**。
换机器后按 §2.4 重跑即可；规则对照组已经给出同一 60 题的下界参照（51.7%）。

口径边界：
- G3 的 chain 不计分；
- 扩展组只换三类实体表，POI/地铁/跨城沿用官方 release；
- 西安 price 覆盖率是已知缺口；
- 官方三关与 C 组扩展规则并列统计、不混算。

---

## 7. 许可与引用

- **代码**：MIT（`LICENSE`），继承 ChinaTravel / ShortTrip 上游版权。
- **官方沙盒与题集**：ChinaTravel 数据集 **CC BY 4.0**（上游 `f445e00` 声明）。
- **本仓库新增数据**（扩展 catalog、西安 v17、TAG/证据）：仅供研究与复现，第三方来源权利未授予；
  原始网页正文已剔除，只保留来源索引与哈希。逐项说明见 [NOTICE.md](NOTICE.md) 与
  `legacy/five_city_v1/DATASET_CARD.md`。

上游：
- ChinaTravel — https://github.com/LAMDA-NeSy/ChinaTravel
- ShortTrip — https://github.com/Paddington633/ShortTrip

---

## 8. 已知限制

1. **本地 GPU 黑屏**：RTX 5080 Laptop + CUDA 12.4 连续高负载会驱动级黑屏；建议降 `-np`/ctx、限时跑，
   或换数据中心卡。见事故记录。
2. **西安 price 缺口**：主表 706 家中，**354 家有数值**（254 观测 + 78 高置信估价 + 6 本市连锁 + 14 跨城连锁 + 2 青旅同类），352 家为 `-1` 哨兵且 `price_status=unknown`。
   估价行存的是**区间中点 mid**，区间在 `accommodations/xian/price_provenance.csv`；报告不得把估价当实价。
3. **西安位置索引（已重建）**：原 `poi.json` 1,394 条，景点仅命中 68/591；重建后 **4,571 条，591 景点 / 706 酒店 / 486 餐厅 100% 精确命中**，
   英文后缀走别名、未改实体表原值。重建脚本 `scripts/rebuild_xian_poi_index.py`，明细 `poi_index_manifest.json`。
4. **多城 chain 题**：当前 ShortTrip 规划器不支持，未计分。
5. **静态数据**：所有价格/班次是快照，不是实时值；真实出行需接 §4 的动态检索。
6. **1/10 抽样**：60 题的置信区间较宽（±约 12 个百分点），结论只作方向性判断。
