# 本地 Long-run 黑屏事故记录（2026-11-11）

## 现象

在 RTX 5080 Laptop（16 GB）上连续跑 llama.cpp + 6 个 ShortTrip worker 时，**整机显示黑屏**，
随后 SSH/终端会话里的进程一起消失。不是 Python 异常，也没有 OOM 日志。

## 时间线（CST）

| 时间 | 事件 |
|---|---|
| 13:00:35 | 服务就绪，冒烟回复「就绪」，`has_think_tag=false` |
| 13:01:37 | 就绪闸门 READY，G1 第一波 6 个 worker 启动 |
| 13:03:15–13:04:11 | 6 个 `status/*.json` 落盘，`state=running`，`phase=search`，`api_calls=1..2` |
| 13:04 左右 | 黑屏；`llama-server` 进程消失、18080 端口关闭、GPU 显存回到 12 MiB |
| 之后 | G2/G3 从未开始；G1 只有 6 条 `running`，**0 题到达终态** |

## 证据

- `G1_native_v3/experiments/c_only/status/easy_001..006_C_r1.json`：`state=running`、`candidate_count=0`。
- 服务日志尾部停在模型加载完成后的正常推理，没有 CUDA error / OOM 行。
- 显存峰值 **7,946 / 16,303 MiB**（单份权重 + 6×16K KV），排除显存不够。
- GPU 利用率在崩溃前维持 77–100%，功耗墙 168 W（笔记本）。

## 判断

高概率是**显示驱动在持续高负载下 TDR/复位**（笔记本 5080 + CUDA 12.4 预编译包 + `-ngl 99` 全量卸载），
表现为黑屏而不是进程报错。数据层、闸门、模型 hash、服务别名都已验证正常，问题在硬件/驱动稳定性。

## 规避方案（按代价从低到高）

1. **降并发**：`SHORTTRIP_NP=2..4`、`SHORTTRIP_CTX=8192`，显存降到 ~6.5 GB，功耗尖峰更小。
2. **限时轮转**：每跑 20–30 题主动重启服务进程；单题墙钟从 1800 s 降到 900 s。
3. **部分卸载**：`-ngl 24..28`，把几层留给 CPU，降低板卡瞬时功耗。
4. **限功耗**：`nvidia-smi -pl 120`（部分笔记本 vBIOS 不支持）。
5. **换机器**：桌面卡/数据中心卡跑正式成绩；CPU-only 只适合冒烟，不适合 604 题。
6. **纯 CPU 校验**：先用 `-ngl 0` 跑 1–2 题验证流程，再上 GPU。

## 续跑注意

`driver.py` 会跳过已有 `status/` 或 `traces/` 的题。本次留下 6 条**假 running**，续跑前必须清掉：

```bash
RUNS=.../shorttrip-runs/G1_native_v3/experiments/c_only
rm -rf "$RUNS"/status/easy_00{1,2,3,4,5,6}_C_r1.json \
       "$RUNS"/traces/easy_00{1,2,3,4,5,6}_C_r1.jsonl \
       "$RUNS"/cache/easy_00{1,2,3,4,5,6}_C_r1 \
       "$RUNS"/logs/easy_00{1,2,3,4,5,6}_C_r1.log
```

然后重跑 `scripts/run_shorttrip_benchmark.py --all` 即从第 1 题继续。
