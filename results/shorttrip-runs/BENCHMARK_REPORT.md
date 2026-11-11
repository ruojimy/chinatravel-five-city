# ShortTrip + Qwen3.5-4B Q8 三组基准实验

模型：`Qwen/Qwen3.5-4B` Q8_0 GGUF（`Qwen3.5-4B-Q8_0.gguf`，4,610,580,288 B，sha256 `5b25856e…3a833`），llama.cpp b12248 CUDA 12.4，`--reasoning off`、16K/slot、`-np 6`、别名 `qwen3.5-4b-q8`，单实例顺序跑三组。

抽样：固定 seed 20261111，每组 1/10（native easy 30 / medium 15 / human 15 = 60；xian11 3/3/3 = 9，30 道 chain 与单目标规划器不兼容未计分）。

| 组 | 数据层 | split | 完成/目标 | generated | 官方三关全过 | C组规则通过 | 共同通过 |
|---|---|---|---:|---:|---:|---:|---:|
| G1_native | 官方原生沙盒 | easy | 6/30 | 0 | 0 | 0 | 0 |
| G1_native | 官方原生沙盒 | medium | 0/15 | 0 | 0 | 0 | 0 |
| G1_native | 官方原生沙盒 | human | 0/15 | 0 | 0 | 0 | 0 |
| **G1_native 合计** | 官方原生沙盒 | all | 6/60 | 0 | 0 | 0 | 0 |
| G2_ext10 | catalog_v1_1 | easy | 0/30 | 0 | 0 | 0 | 0 |
| G2_ext10 | catalog_v1_1 | medium | 0/15 | 0 | 0 | 0 | 0 |
| G2_ext10 | catalog_v1_1 | human | 0/15 | 0 | 0 | 0 | 0 |
| **G2_ext10 合计** | catalog_v1_1 | all | 0/60 | 0 | 0 | 0 | 0 |
| G3_ext11 | catalog_v1_1 + xian11 | easy | 0/3 | 0 | 0 | 0 | 0 |
| G3_ext11 | catalog_v1_1 + xian11 | medium | 0/3 | 0 | 0 | 0 | 0 |
| G3_ext11 | catalog_v1_1 + xian11 | human | 0/3 | 0 | 0 | 0 | 0 |
| **G3_ext11 合计** | catalog_v1_1 + xian11 | all | 0/9 | 0 | 0 | 0 | 0 |

状态：**running**　更新：2026-11-11T06:35:04.656427+00:00

## 规则规划器对照（P34 ConstraintPlannerV2，纯规则、0 LLM token）

同一冻结 60 题：三关全过 **31/60 = 51.7%**（easy 18/30、medium 4/15、human 9/15）。

## 口径边界

- 每组 1/10：native 60/604（9.93%），xian11 9/90（10%）；easy/medium/human 均覆盖，G1/G2 共用同一批 UID 配对。
- G3 的 30 道 `shorttrip-dynamic-v1` 多城串联题与 ShortTrip 单目标规划器不兼容，未计入 LLM 组成绩。
- 扩展组只替换 attractions/restaurants/accommodations 三类实体表；POI / 地铁 / 跨城沿用同一官方 release，因为题目 DSL 引用精确 TrainID/FlightID。
- 第 11 城数据来自 snapshot_v17；景点 price 12.3%、餐厅 69.5%、住宿 40.4% 为已知开放缺口。
- 官方三关成绩来自 ShortTrip worker 自带的独立评估；C 组规则为其扩展检查，两者并列不混算。
- 每题一次提交即终态，driver 对已有产物不重跑；中断后重跑 runner 即续跑。
- 规则规划器绑定原生沙盒，因此只作 G1 对照；G2/G3 无同构规则规划器。

