# ChinaTravel V19 冻结评测

西安和厦门使用同一套十二城沙盒。Luna 独立提交首稿，首稿全部冻结后，每题接收评分器反馈并提交一次修订或保留首稿。

| 批次 | 分母 | 首稿通过 | 修订后通过 |
|---|---:|---:|---:|
| ChinaTravel Easy／Medium／Human | 36 | 11 | 23 |
| 按交通、接驳、类别和证据边界划分的扩测 | 48 | 31 | 39 |
| V17 未通过题的 V19 复测 | 9 | 2 | 4 |

三批分别统计。V17 原始对照见 [24 题结果](luna_feedback_24/results.json) 和 [9 题逐题对照](luna_v19_residual_9/comparison.json)。分项实验见 [48 题逐题结果](luna_v19_expanded_48/analysis.json)。

## Easy／Medium／Human

36 道题由三档各 6 道 ChinaTravel 本地题库模板派生。每个模板分别替换为西安和厦门，保留原起点、人数、天数及硬约束。 [逐题结果](luna_v19_standard_36/analysis.json) · [题目来源](luna_v19_standard_36/sources.json) · [交通预检](luna_v19_standard_36/transport_preflight.json) · [住宿目录预检](luna_v19_standard_36/lodging_preflight.json)

| 档次 | 首稿 | 修订 |
|---|---:|---:|
| Easy | 5/12 | 6/12 |
| Medium | 2/12 | 6/12 |
| Human | 4/12 | 11/12 |

最终 23 题通过，1 题因市内交通方式失败，12 题报告阻塞。其中 7 题通过独立的冻结记录预检确认存在往返票价、行程时限或预算障碍。

公开快照的收据使用发布文件的 SHA-256。归档中的 `profile_receipt_sha256` 记录实际评测输入。适用时，`public_profile_receipt_sha256` 标识供复评使用的公开副本。逐题引用的路径相对于本归档目录，`sha256` 对应公开文件，`local_sha256` 保留原评测文件摘要。

此归档含公开题面、提交、评分、反馈及与结论直接相关的工具证据。原始服务商响应和采集会话留在本地。历史车票和房价只作为冻结评分参考。标准题离线复评可运行 `scripts/replay_benchmark12_v19.py`。
