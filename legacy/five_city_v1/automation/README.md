# 自动化采集闭环

## 目标

在**已授权的本地项目**内定时推进 ChinaTravel 五城静态参考采集与严格诊断：读 v4、找缺口、做受控补采、保存证据、更新断点；不绕过来源访问限制，不自建账本，不自动购买额度。

## 组成

| 文件 | 作用 |
| --- | --- |
| `collector_agent/README.md` | 采集闭环的设计与边界 |
| `collector_agent/PROMPT.md` | 单轮执行指令（状态、预算、停止条件） |
| `collector_agent/AUTOMATION_PROMPT.md` | 定时唤醒的自动化提示 |
| `collector_agent/SOURCES.md` | 来源清单与暂停家族 |
| `collector_agent/config.example.json` | 配置模板（已移除 project_id） |
| `code/scripts/collection_agent.py` | bootstrap / begin-run / 阶段推进 / checkpoint |
| `code/scripts/collection_session.py` | 运行锁、配额门、begin/check/end |
| `code/src/shorttrip/collection_session.py` | 共享会话与锁的底层实现 |

## 单轮流程

```
读 CORE/HANDOFF/state/config/PROMPT/lessons
  → 检查是否有未完成的旧 worker/锁（有则保留现场退出）
  → 读真实用量，判断 5h/周/时间门
  → begin(run_id) + begin-run
  → 离线诊断：data / context / access / adapter / solver / pipeline 分类
  → 合并缺口：实体 + 字段 + 范围 + 政策
  → 最多 1 批、≤2 worker、合计 60 次 web 动作
  → 逐字段证据门：原文、URL、hash、quote、TAG、时间、身份、房型、票种、许可
  → 新不可变候选快照 + 对同一冻结开发题集重跑
  → checkpoint + 重读用量 + 下一独立步骤
  → 时间/额度边界：end(run_id, --workers-stopped)
```

## 硬边界

- 单轮最多 1 批、≤2 个 worker、合计 60 次 web 动作；每缺口 ≤3 个来源；
- 历史暂停/验证码/403/429/限流：保持暂停，不换工具、子域、镜像、UA、Key；
- 不调用高德/API 计费通道（`api_http=0`）；
- 不修改 `ChinaTravel/` 原基准、v4 原库、旧证据与 P31 归档；
- 结束只接受 `time_budget_reached / usage_budget_reached / batch_goal_complete / no_safe_work_remaining / runtime_blocked`；
- 没有真实用量文件时不得编造 `fresh_usage.json`。

## 已知状态

- 本轮 manual 开发集 60/60 `data_block`；身份 120/120 未核验；65 个实体受 paused 来源影响；
- 下一步是身份核验、来源授权、观察时间与引文/金额门修复，然后再进入真实补采。
