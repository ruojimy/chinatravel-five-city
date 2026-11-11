# 两条 LLM 基线：纯 LLM 与「NeSy 换 DeepSeek-V4.1-Flash」

**日期**：2026-10-29　**模型**：`deepseek-flash`（DeepSeek-V4.1-Flash，端点 `https://api.deepseek.com`）
**题量**：`easy_short` 8 题（`chinatravel/evaluation/default_splits/easy_short.txt`）
**评测**：官方 `eval_exp.py`（**未做任何修改**）
**产物**：`results/llm_pure/`（含 README、runs.json）、`results/llm_nesy/`（含 README、runs.json、logs）

---

## 0. 结论

| 方法 | 说明 | schema | commonsense（整题） | hard DSL（整题） | **三关全过** |
| --- | --- | ---: | ---: | ---: | ---: |
| **纯 LLM**（`Act_deepseek-flash`） | LLM 直接调工具产出计划 | 100.0% | 0/8 | 3/8（37.5%） | **0/8 = 0.00%** |
| **NeSy × flash**（`LLMNeSy_deepseek-flash`） | LLM 只做 NL→DSL + 候选排序，符号搜索求解 | 100.0% | 8/8 | 8/8 | **8/8 = 100%** |
| RuleNeSy（对照，不调 LLM） | 规则翻译 + 符号搜索 | 100.0% | 7/8 | 7/8 | 7/8 = 87.5% |
| 我们的 P34 规则规划器（对照） | 纯规则、无 LLM | 100.0% | 8/8 | 8/8 | 8/8 = 100% |

**一句话**：同一批 8 题、同一套沙箱与评测，**纯 LLM 0%**、**NeSy 换成 flash 后 100%**（且比不调 LLM 的 RuleNeSy 高 12.5 个百分点，零损失）。
这与论文的形态一致：论文 easy 上纯 LLM 0–5.33%，NeSy（DeepSeek-V3）52.6%。

⚠️ **切片警告**：8 题是饱和切片（连我们无 LLM 的规则规划器也是 8/8），**只能证明“替换可行、方向一致”**，不能替代论文 300 题的数字，也不能据此说“flash 比 DeepSeek-V3 强”。

---

## 1. 测试一：纯 LLM（官方 Act agent）

**命令**：`run_exp.py --splits easy_short --index <uid> --agent Act --llm deepseek-flash`（循环 8 题）
**数字**：schema 8/8、commonsense micro 79.91% 但**整题 0/8**、hard micro 87.5% 整题 3/8、三关全过 **0/8**。

### 1.1 失败结构（Top5，来自 runs.json）

| 排名 | 次数 | 失败项 | 原因 |
| --- | ---: | --- | --- |
| 1 | 7 | Incorrect Information of Inner-City Transport on price/distance/duration | 模型自编市内接驳（distance 0.0、站名不在沙箱地铁图里） |
| 2 | 6 | Unavailable Inner-City Transport | 引用沙箱里不存在的站点/地点 |
| 3 | 4 | Unavailable Restaurants / Visiting Restaurants in their closed time | 选了不存在的餐馆、或在其关门时段到访 |
| 4 | — | Repeated attraction/meal choices | 同一天重复选同一个点 |
| 5 | 1 | Commonsense Evaluator Exception | 官方评测器内部异常（被捕获计为失败），如实记录 |

**判读**：模型确实会调工具（`intercity_transport_select`、`attractions_keys`、`goto`、`notedown` 都出现并被 `WorldEnv` 正常执行），但**它不会为每一段接驳去调 `goto` 拿真实数据**，而是自己编距离与时耗——所以 schema 能过（格式对），commonsense 全灭（事实错）。

### 1.2 之前那个 `TypeError: 'str' object does not support item assignment` 的真实原因

不是动作解析，而是**推理模型的 token 预算**：

1. `llms.py` 原 `DEFAULT_MAX_TOKENS=4096`，`deepseek-flash` 的 CoT（reasoning_tokens）也计入 max_tokens，实测被 4096 打满 → `finish_reason="length"`、`content` 为空（content_len=0，reasoning_len=14674）；
2. `repair_json("")` 返回的是 JSON **字符串标量** `""`，不是 `{}`；
3. runner 的 `isinstance(plan, str)` 守卫在 `json.loads` **之前**，`json.loads('""')` 合法返回 `str` → 绕过守卫 → 下一行赋值崩。

修复：`DEFAULT_MAX_TOKENS` → 8192（可用 `CHINATRAVEL_OPENAI_MAX_TOKENS` 覆盖）+ `ActAgent.plan()` 校验返回值必须解析成 dict，否则带纠正提示重试一次。

### 1.3 成本

8 题：input 936,220 + output 173,161 tokens；单题 89–178 s，两批并行墙钟 ≈324 s。

---

## 2. 测试二：把 NeSy 里的 LLM 换成 flash

**方法名**：`LLMNeSy_deepseek-flash`
**命令**：`run_exp.py --splits easy_short --agent LLMNeSy --llm "deepseek-flash"` → `eval_exp.py --splits easy_short --method LLMNeSy_deepseek-flash --lang zh`

### 2.1 结果与同题配对

| 关卡 | LLMNeSy_deepseek-flash | RuleNeSy_rule（同 8 题） |
| --- | ---: | ---: |
| schema | 100.0%（8/8） | 100.0%（8/8） |
| commonsense 整题 | **100.0%（8/8）** | 87.5%（7/8） |
| hard DSL 整题 | **100.0%（8/8）** | 87.5%（7/8） |
| **三关全过** | **8/8** | 7/8 |

配对：两边都过 7 题；**只有 LLMNeSy 过 1 题**（`e20241028160301887545`，RuleNeSy 在它上面撞了 `Repeated Meal Types in One Day` + 1 条 hard）；只有 RuleNeSy 过 0 题 → **净 +12.5 pp，零损失**。

### 2.2 关键坑：不加别名会“静默丢掉全部约束”

`deepseek-flash` 若不注册别名，会走「任意 OpenAI 兼容名」分支，`default_request_args` 为空 → 温度取服务端默认值 → **NL→DSL 第二步漂成空列表**，被 `get_first_list_in_str()` 兜成 `"[]"`、`json.loads("[]")` 成功 → 于是 **`hard_logic_py=[]` 且无任何异常、无日志**，符号搜索退化成“无约束搜索”（实测：0 条约束，plan 的 schema/commonsense 仍然全过，看起来像好结果）。

修复（唯一改动，`chinatravel/agent/llms.py` 195–207 行）：

```python
"deepseek-flash": ModelAlias(name="deepseek-flash", model="deepseek-flash",
    base_url="https://api.deepseek.com", api_key_env="DEEPSEEK_API_KEY",
    default_request_args={"temperature": 0, "top_p": 0.00000001}),
```

加上后同题翻译出 5 条 NL 约束 → **7 条合法 DSL、7 条全 passed**，8 题全部一次过 AST 检查（`reflect_cnt=0`）。

### 2.3 成本与规模

8 题墙钟 ≈ **25 分钟**（3.1 分钟/题）；input 113,259 + output 204,271 = **317,530 tokens**（39.7k/题）；搜索 17–5,455 节点、7–2,183 次回溯；单题 search 段 124–218 s，`TIME_CUT=300s` 最慢一题已用 72%。

---

## 3. 怎么解读这三组数字

1. **纯 LLM 的瓶颈不是“会不会规划”，而是“愿不愿意查”**：它把接驳当作文本补全（自编 0.0 km 的市内段），而沙盒要求每段接驳与 `goto` 完全一致。schema 100% / commonsense 0% 这个组合本身就说明“格式对、事实错”。
2. **NeSy 的价值在“把 LLM 关进翻译层”**：LLM 只输出约束（DSL），剩下由符号搜索在沙箱里枚举、回溯、校验。同一个模型，从 0/8 变成 8/8，差别不在模型能力，而在**它被允许做什么**。
3. **flash 够用**：NL→DSL 这一步对模型要求不高（7 条约束、一次通过 AST 检查、零反思），V4.1-Flash 已经能胜任；这与论文“NeSy 的增益主要来自结构，不是模型大小”的判断一致。
4. **和我们 P34 规则规划器的关系**：8 题上两者都 8/8，说明在“约束已明确”的切片上规则够用；真正拉开差距的是语义理解（300 题上我们还落后论文 NeSy 3.9 个百分点），而这次实验正好给出了接口——**用 flash 做 NL→DSL，把规则规划器接到它后面**。

---

## 4. 复现与改动清单

```powershell
cd reproduction\ChinaTravel
$env:PYTHONUTF8='1'
Remove-Item Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:ALL_PROXY,Env:NO_PROXY,Env:http_proxy,Env:https_proxy,Env:all_proxy,Env:no_proxy -ErrorAction SilentlyContinue
$env:OPENAI_API_KEY = (Get-Content ..\.secrets\deepseek.key -Raw).Trim()
$env:OPENAI_BASE_URL='https://api.deepseek.com'

# 纯 LLM（逐题循环，run_exp 没有 --limit）
..\.venv\Scripts\python.exe run_exp.py --splits easy_short --index <uid> --agent Act --llm deepseek-flash
..\.venv\Scripts\python.exe eval_exp.py --splits easy_short --method Act_deepseek-flash --lang zh

# NeSy × flash
..\.venv\Scripts\python.exe run_exp.py --splits easy_short --agent LLMNeSy --llm deepseek-flash
..\.venv\Scripts\python.exe eval_exp.py --splits easy_short --method LLMNeSy_deepseek-flash --lang zh
```

**代码改动（仅 agent 侧，评测与沙箱零改动）**

| 文件 | 改动 | 归属 | 作用 |
| --- | --- | --- | --- |
| `chinatravel/agent/llms.py:25` | `DEFAULT_MAX_TOKENS` 4096 → 8192（env 可覆盖） | 纯 LLM 线 | 推理模型的 CoT 不再吃掉 JSON 预算 |
| `chinatravel/agent/pure_neuro_agent/pure_neuro_agent.py` | `plan()` 校验返回必须为 dict，否则重试一次 | 纯 LLM 线 | 防止字符串标量绕过守卫 |
| `chinatravel/agent/llms.py:195–207` | 新增 `deepseek-flash` 别名（temperature=0, top_p=1e-8） | NeSy 线 | 否则 NL→DSL 静默返回空约束 |

> 两条线**并行**改同一个文件（`llms.py`），已核实互不冲突：别名只影响 `deepseek-flash`，`DEFAULT_MAX_TOKENS` 是全局兜底。复跑时 `--llm deepseek-flash` 会命中别名（确定性采样），与纯 LLM 首轮（无别名、服务端默认温度）**不完全同参**，已在两边 README 中注明。

---

## 5. 局限与下一步

- **8 题太少**：两边都只有 8 题，且是饱和切片。扩到 30 题的成本：纯 LLM ≈ 20 分钟；NeSy ≈ 90–100 分钟（3.1 分钟/题）。
- **NeSy 的搜索成本是硬约束**：单题 124–218 s、最慢已用 72% 的 `TIME_CUT`；扩量前应先调 `search_width` 与 `TIME_CUT`（`run_exp.py` 未暴露，需要小改）。
- **纯 LLM 还能救一点**：把 `goto` 强制成“每段接驳必调”，理论上能把 `Incorrect Information of Inner-City Transport`（7/8）消掉；但这已经变成“LLM + 工具约束”，不再是纯 LLM 基线。
- **建议的下一个实验**：用 flash 做 NL→DSL，接我们 P34 规则规划器，在 300 题 easy 上跑——正好补上“语义理解”这 3.9 个百分点的缺口。
