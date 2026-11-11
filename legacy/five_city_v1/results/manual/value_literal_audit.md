# `value_literal_in_quote` 独立审阅

## 审阅范围与复算

只读检查 `results/manual_20261101_1803/retained_evidence_triage.json`、其开发诊断输入、`scripts/strict_retained_evidence_triage.py` 以及只读打开的五城 catalog。未联网、未修改源码或数据，也没有触发抓取或来源激活。

重新从诊断队列读取 catalog 中的 claim/evidence 行，并按脚本实现逐条计算 `str(value) in quote`（仅 `type(value)` 为 `str`、`int`、`float` 且 quote 为字符串时计算），得出 555 条 claim 引用：**321 True、232 False、2 None**，与 JSON 汇总及逐行标记一致。类别总数为 555。两条 None 的 claim value 都是坐标数组（`position`），属于不支持的复合值；不是缺失的 quote 命中判定。样本中没有 Python bool 值；实现的精确类型检查也会把 bool 排除在 int 之外。直接 `claim.value` 均有值，未观察到 null/缺失值行。

同时重算输入 SHA-256，开发诊断与 catalog 哈希均与产物记录相同。行级标记为 555 个 `fetch_authorized=false`、555 个 `semantic_or_identity_verified=false`、555 个 `observed_at_present=false`；唯一 evidence ID 为 148 个。诊断队列列 120 个 entity work items，但只有 104 个 entity ID 在这 555 条 claim 引用中出现（其余队列项没有被这些 claim 行代表）。这些数字是引用/行级统计，不是独立证据件数。

## 误读风险

该值的实际含义只是“Python 字符串表示是否作为连续字符序列出现在保存的 quote 中”，不能称为 value 被 quote 证实或值与引文语义一致。对数字和文本都有明确误读路径：

- **子串假阳性：**样本中整数 `0` 的价格 claim 被标为 True，因为它的 quote 含有无关营业时间 `09:00`；这不是价格值出现在价格语境中的证据。文本值也可能碰巧出现在序列化文本的别处，与 claim 字段无关。
- **格式差异假阴性：**样本 `Cost=620.0` 的 quote 写作 `¥620`，因此 False；`Duration=1.75` 对应引用中的 `1h45m` 也为 False。数值意义可能相同，但字符串表达不同。指标也不做千分位、货币符号、单位、舍入精度或科学计数法规范化。
- **浮点与类型边界：**`str(float)` 是 Python 的格式化结果，可能与源数据文本精度/小数位数不同。数值转换本身也可能已经损失精度；指标既不还原原始数字 token，也不做精确数值比较。
- **不适用合并：**None 将不支持的类型或无法执行子串判断的场景并为一类。当前两项是列表值，但若未来数据含缺失值、null 或非字符串 quote，它们也可能落入 None；汇总没有分别计数原因。
- **文本匹配不代表字段绑定：**即使 True，quote 中的字符串可能是 entity ID、另一字段、相邻行或其他上下文；算法没有检查引文片段、字段名或来源结构是否将该值绑定到 claim。

因此，321/232/2 的算术与脚本规则相符，但 `value_literal_in_quote` 只适合弱文本盘点。引用子串命中率、未命中率都不能表示证据质量或准确率。若要升级为字段级核验，应单独设计类型感知、上下文/字段绑定的规则，保留数字原始文本与单位，并用已人工审阅的正负样例验证；不得在不变更定义的情况下把该布尔统计换名为语义支持。

## Holdout、授权与使用边界

该 JSON 的 label 是 `retained_text_triage_not_evidence_acceptance`，标注 `network_requests=0`、`formal_freeze=false`、`original_http_response_certified=false`、`identity_or_truth_certified=false`。每行都将抓取授权和语义/身份验证标为 false。文件没有 holdout 划分或独立验证集字段；因此不能称这批统计为 holdout 结果，也不能从中声称做过独立泛化验证。未发现任何来源访问授权或正式冻结证据；本次审阅本身也不授予任何授权。

## 限制

独立复算复用了同一份 SQLite catalog 和诊断队列，能确认汇总计数忠实反映这些保存内容及当前 Python 子串规则；它不是独立来源核验。catalog 内的 `raw_sha256` 与 UTF-8 重建文本哈希相等，只能说明两段本地保存值一致，不能证明对应原始 HTTP 响应、原始字节、来源身份、许可、时间新鲜度、claim 真实性或语义正确性。历史 capture method 标签也没有在本次审阅中独立验证。
