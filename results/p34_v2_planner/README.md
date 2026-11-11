# P34：V2 规则规划器在 ChinaTravel 原 schema 上的测试（结果目录）

本目录是 2026-10-29 的重做实验：把 P33 的 `SkeletonPlanner + RepairEngine` 升级为
`src/shorttrip/planner_v2.py` 的 `ConstraintPlannerV2`（确定性、无 LLM），用**官方 checker 当裁决**
做约束定向的候选生成与接受，再用未修改的 `eval_exp.py` 打分。

## 一句话

三关全过 **48.7% / 46.0% / 70.8%**（easy/medium/human），比 P33 的 30.0 / 18.0 / 46.1 提升
**+18.7 / +28.0 / +24.7** 个百分点；hard DSL 从 32.3 / 30.7 / 46.8 升到 56.3 / 51.3 / 76.0。
与论文 FPR 对比：easy 48.7 vs NeSy 52.6、medium 46.0 vs 46.7、human-val 70.8 vs 37.0（NeSy）/ 45.4（NeSy*）。

## 结构

| 路径 | 内容 |
| --- | --- |
| `easy_ShortTripV2_easy.json` | easy 300 题逐题结果（hard 列、moves、evaluations） |
| `medium_ShortTripV2_medium.json` | medium 150 题 |
| `human_ShortTripV2_human.json` | human 154 题 |
| `aggregate.json` | 与 P33、论文同表的汇总（含 gains） |
| `table.md` | 上面那张 markdown 表 |
| `delta_analysis.json` | 相对 P33 修好/弄坏的约束列、commonsense 列分布 |
| `../ChinaTravel/eval_res/splits_*_p33/ShortTripV2_*` | 官方 schema/commonsense/logical_py CSV |
| `../ChinaTravel/results/ShortTripV2_*` | 导出的原 schema 计划 |

## 复现

```powershell
cd reproduction\ChinaTravel
$env:PYTHONUTF8='1'; $env:PYTHONPATH='../src'
..\.venv\Scripts\python ..\scripts\p34_run_v2.py --split easy --method ShortTripV2_easy
..\.venv\Scripts\python eval_exp.py --splits easy_p33 --method ShortTripV2_easy --lang zh
..\.venv\Scripts\python ..\scripts\p34_aggregate.py
```

## 边界

- 纯规则、无 LLM；测的是 10 个老城市的**原 schema**，不与五城扩展 schema（P31）互比。
- `room_type` 修复、`FlightID` 修正、餐段替换都已在 V2 默认路径内，不需要额外开关。
- P33 的旧数字保留在 `../p33_native_planner/`，用于回归对照，不覆盖。
- 详细分析见 `../报告/28_规则规划器在ChinaTravel原schema的测试.md`。
