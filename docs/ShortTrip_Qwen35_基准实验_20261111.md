# ShortTrip + Qwen3.5-4B Q8 三组基准：协议与当前结果

## 1. 模型（与教程严格一致）

| 项 | 值 |
|---|---|
| 基座 / 量化 | `Qwen/Qwen3.5-4B` / Q8_0 GGUF（`SoAIHQ/Qwen3.5-4B-GGUF`） |
| 文件 | `Qwen3.5-4B-Q8_0.gguf`，4,610,580,288 B |
| sha256 | `5b25856e42534b000b5e06d7cfc10c756931f4dc66a4ca6ef08d835bd233a833` |
| 服务 | llama.cpp b12248 CUDA 12.4，16K/slot，`-np 6`，`--reasoning off`，别名 `qwen3.5-4b-q8` |
| 端点 | `http://127.0.0.1:18080/v1` |

## 2. 三组设计（1/10 分层抽样，seed 20261111）

| 组 | 数据层 | 题集 | 题数 | 副本 |
|---|---|---|---:|---|
| G1_native | 官方原生 10 城沙盒（132 文件，release 2026.08.2） | 原生 604 × 1/10 | 60（easy 30 / medium 15 / human 15） | `G1_native_v3` |
| G2_ext10 | 我们的 `catalog_v1_1` 导出成同结构 CSV | **与 G1 同一批 60 个 UID** | 60 | `G2_ext10_v3` |
| G3_ext11 | G2 + 第 11 城西安 | xian11 90 × 1/10 | 9（3/3/3） | `G3_ext11_v4` |

- 「除扩展数据集外都用 ShortTrip 架构」：只替换 `database/{attractions,restaurants,accommodations}/<city>/*.csv`；
  规划、翻译、DFS、软评分、评估全部是上游原码。
- 第 11 城只在数据层注册 `xian / 西安 / Xi'an`，不改规划逻辑。
- 单题预算保持上游默认：墙钟 1800 s、候选目标 20、`max_tokens=4096`、请求超时 600 s。

## 3. 就绪闸门

开测前 `scripts/shorttrip_readiness.py` 必须 READY：数据树 60 s 双采样静止、快照/覆盖率跨次不变、
GGUF 完整、`/v1/models` 返回别名、研究者显式 `--accept-coverage`。本次放行说明：
「景点 price 12.3% / 餐厅 69.5% / 住宿 40.4% 为已知开放缺口，研究者接受」。

## 4. 规则规划器对照组（P34 ConstraintPlannerV2，0 LLM token）

| split | 1/10 子集 | 全量 |
|---|---:|---:|
| easy | 18/30 | 146/300 |
| medium | 4/15 | 69/150 |
| human | 9/15 | 109/154 |
| **合计** | **31/60 = 51.7%** | **324/604 = 53.6%** |

子集结果由 `scripts/p35_rule_baseline_1of10.py` 从全量逐题明细过滤得到，UID 与 G1/G2 完全一致。

## 5. LLM 三组当前状态

G1 第一波 6 题进入 `phase=search` 后，本机 **13:04 左右 GPU 黑屏**，服务与 worker 一起被杀；
**0 题到达终态**，G2/G3 未开始。详见 [事故记录](LOCAL_RUN_INCIDENT_20261111.md)。
换机器或降并发后重跑 `scripts/run_shorttrip_benchmark.py --all` 即可续跑。

## 6. 口径边界

- G3 的 30 道 `shorttrip-dynamic-v1` 多城串联题与 ShortTrip 单目标规划器不兼容，未计分。
- 扩展组只替换三类实体表；POI / 地铁 / 跨城沿用同一官方 release（题目 DSL 引用精确 TrainID/FlightID）。
- 西安数据来自 snapshot_v17：景点 price 12.3%、餐厅 69.5%、住宿 40.4%，预算类约束会被这些缺口影响。
- 官方三关与 C 组扩展规则并列统计，不混算。
- 每题一次提交即终态；driver 对已有 `status/` 或 `traces/` 的题不重跑。
