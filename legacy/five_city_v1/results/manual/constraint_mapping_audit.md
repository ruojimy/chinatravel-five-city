# P31 约束编译与映射边界审阅

## 审阅范围与当前版本测试

只读审阅 `strict_constraint_compiler.py`、`strict_p31_constraints.py`，沿 `diagnose_plan` 和约束 evaluator 检查消费路径；使用合成 fixture 观察单项约束与整体结果。未联网、未修改源码或测试。

在当前重读版本运行：

```powershell
$env:PYTHONPATH='src;.venv\Lib\site-packages'
& '<local-path>\.workbuddy\binaries\python\versions\3.13.12\python.exe' -m unittest tests.test_strict_constraint_compiler tests.test_strict_p31_constraints tests.test_strict_p31_bridge tests.test_strict_plan_diagnostics
```

结果：**65 tests passed**。合成路径使用的 `fact_verifier` / `scope_verifier` 是 `lambda *_: True`，只能测试控制流，不能认证事实或自然语言等价性。

## 当前 fail-closed 行为

- `compile_constraint` 的预算表达式要求 `strength='hard'`、精确 CNY/人数/包含项参数、正整数人数、CNY 总行程币种/单位 scope。未知运算符直接 `unsupported`。
- Tag 运算符把 `exclude_tag` 限为 hard 且 `quantifier='all'`；`prefer_tag` / `conditional_prefer_tag` 限为 soft。非法 scope、strength 或 tag 输入不能由 evaluator 当作 pass。
- P31 原生 `task.constraints` 没有足够字段时保留为 unknown，不推导预算单位/人数/强度。原生 hard/unknown 会展示为 `unknown_checks`；soft 显示在 `soft_checks`。P31 诊断仍通过 `planner.supported=false` 及未完成所需检查维持非完成状态。
- `count_at_least`、`arrive_by` 虽列在 P31 mapper 的 `_STRICT_OPERATORS`，**当前 compiler 并不实现**。合成 hard `count_at_least` 在 mapper 输出中被列为 mapped ID、`unresolved=[]`，但下游重新运行 compiler 时变为 `unknown / constraint_compile_validation_failed`，并有 adapter blocker；没有观察到它被判为 pass。这是 mapper 与 compiler 的算子表不一致和映射标签误导，不是 pass 漏洞。
- 当前 mapper 已拒绝 placeholder task/constraint ID；含 int 与 str 混合键的 native constraint dict 作为整体 unresolved，不再因排序异常抛出。对应现有测试已通过。

## 发现的 pass 路径

### 1. 预算 scope 的 bool/float 人数可绕过类型一致性

compiler 先要求 expression 的 `args.people` 是精确 Python int，但再用普通 dict 相等比较验证完整 scope。Python 中 `True == 1` 且 `1.0 == 1`，因此下面两个 scope 都被当作与 `people=1` 相等，compiler 返回 `supported`：

```python
scope.people = True   # supported
scope.people = 1.0    # supported
expression.args.people = 1
```

进一步的完整合成 P31 路径中，`scope.people=True` 仍被映射保留；fact 的 context 使用精确整数 `people=1`、币种 CNY、金额 90、限额 100，`constraint_fact_verifier=True` 后 `constraint:budget` 返回 **pass / verified_cost_comparison**。`evaluate_constraint` 再次检查 fact context 的人数类型和值，却不直接检查 constraint 的 scope，所以没有发现原 scope 类型不一致。`Decimal(1)` 等与 int 相等的类型也应作为同类候选负例审查。

该样例整体结果仍为 `data_block`，有其他缺失项以及 planner unsupported；因此发现的是**单项 hard constraint 被错误标成 pass**，不是整体行程通过或可执行。修复建议：预算 scope 按键逐项做精确类型验证，特别要求 `type(scope['people']) is int`，然后再比较值；不要依赖跨类型相等。

### 2. 未核实自然语言/额外语义在映射时被丢弃，结构化硬约束可单项 pass

`compile_constraint` 明确返回 `natural_language_equivalence_verified=False`，但 P31 mapper 不检查该值，也没有输入一份可验证、与结构化表达式绑定的独立审阅凭证。它把输入裁成 `id/strength/expression/scope/compiler_status` 五个字段；诸如 `natural_language`、`display_context` 或其他含义字段不会保留，也不会因此形成 unresolved。

合成例：输入硬规则的自然语言写“不要选择米其林星级餐厅”，结构化表达式却是 `exclude_tag(tag='night')`。给一条范围明确的餐厅列表和独立 callback 声明其没有 `night` tag 后，P31 的 `constraint:hard-exclusion` **返回 pass**。mapper 结果中原自然语言和附加上下文字段已消失。该 pass 只证明当前结构化 tag 断言对给定 facts 的结果；它没有证明原自然语言已被准确翻译。

另一合成预算例把自然语言限额写为 CNY 80，结构化表达式却为 CNY 100；相同类型的结构化事实金额 CNY 90 使 hard budget 单项 pass。编译器只做语法检查，因此并没有识别两种表示的语义冲突。

建议在映射边界保留并哈希绑定源自然语言/所有语义上下文字段和规范化表达式，由独立审阅器确认等价；未通过时将原约束保持 unresolved，而不是只依赖调用者提供 `compiler_status='supported'`。若结构化约束本来就是唯一权威输入，也应明确 schema 拒绝或隔离附带自然语言字段，避免它被下游误认为已覆盖。

## 没有观察到的绕过

- 只把 `compiler_status` 写成 supported 并不能令任意表达式通过；下游 `diagnose_plan` 会再次运行 `compile_constraint`。比如上面的 `count_at_least` 最后 unknown 且有 adapter blocker。
- 缺失 scope 的预算表达式不会直接 pass。编译器因 scope 不匹配返回 unsupported；下游产生 `constraint_compile_validation_failed` unknown。
- native P31 数值预算不会自动变成有金额单位/人数的 hard budget。原始值留在 unresolved 条目，state unknown。
- 当前函数链的整体计划不能据此标成完成：`diagnose_plan` 声明 planner unsupported、required checks incomplete；本次预算/Tag 合成结果中也有其他 data blocker。因此本文发现的 pass 均指单项表达式/检查，不代表 P31 整体结果 pass。

## 后续定向回归建议

1. 对预算 scope 的 people 值分别测试 `True`、`1.0`、`Decimal('1')` 和 `1`，只允许精确 int 的最后一种；同样对 CNY limit/people 的跨类型值和 bool 数量构造负例。
2. 把 `_STRICT_OPERATORS` 与 compiler 真正实现的 operator set 对齐。传入 compiler_status=supported 的 hard/soft `count_at_least`、`arrive_by` 应在 P31 mapping 阶段直接列 unresolved，或显式保留 mapping 但理由清楚；最终不得 pass。
3. 对含互相矛盾的 `natural_language` 与结构化表达式，要求映射报告 unresolved 或独立等价 verifier 明确接受；检查 callback 是否能看到原文、上下文和绑定 digest。自然语言字段被裁掉不能自动视为已编译。
4. 对额外字段、遗漏 scope 维度、budget include 项多/少/重复、币种冲突、自然语言人数/预算与 args 不同分别测试单项检查和 P31 最终 outcome；区分软偏好 satisfied 与 hard constraint pass。
5. 保留 task/constraint placeholder ID 与 native mixed-key dict 的 fail-closed 测试；混合键输入应返回结构化 unknown，而不是抛出未处理排序异常或丢掉整个约束。

## 最新修复后的复放结果

在上述初次审阅之后，最新版本收紧了预算 scope 类型比较、P31 additional-constraint 字段白名单及 compiler 复验，并让 hard unresolved 映射重分类为 adapter blocker。以下复放均针对当前文件；重新运行 compiler、P31 constraints、P31 bridge、plan diagnostics 四组定向测试：**68 tests passed**。

| 先前合成输入 | 当前 mapper/compiler 结果 | constraint 检查与 blocker |
|---|---|---|
| 预算 scope `people=True`、args.people=1 | compile validation failed；constraint unresolved | unknown，hard adapter blocker；不再 pass |
| 预算自然语言上限 CNY 80、结构式上限 CNY 100，并带自然语言/展示上下文字段 | 多余字段令 `constraint_has_unsupported_fields` | unknown，hard adapter blocker；不再 pass |
| 自然语言排除米其林餐厅、结构式 `exclude_tag('night')` | 多余 `natural_language` 字段令 `constraint_has_unsupported_fields` | unknown，hard adapter blocker；不再 pass |
| hard `count_at_least`（mapper operator allowlist 中有，但编译器不支持） | compile validation failed；被列 unresolved，而非 mapped | unknown，hard adapter blocker；不再 pass |

另外检查了没有自然语言/额外字段的规范结构表达式：P31 adapter 可以对结构化事实返回例如 `constraint:... = pass`，但结果同时带 `structured_constraints_only=true`、`natural_language_equivalence_verified=false`；当前直接 `diagnose_plan` 的单项 check 本身也带 `natural_language_equivalence_verified=false`。因此**没有发现任何输出把自然语言等价性声明为已通过**。这里的 pass 明确是结构表达式对其给定、经 callback 检查的事实所作的 predicate 结果；P31 整体仍保留 planner unsupported 和其他阻断状态。

剩余接口边界：直接调用较低层 `diagnose_plan`、绕过 P31 mapper 时，`compile_constraint` 对 top-level 多余字段本身仍可报告语法 `supported`；当前在实际 per-check 输出中会显式带 `natural_language_equivalence_verified=false`，不作等价性认证。若需要让所有入口都完全一致，可将严格的顶层字段白名单上移到 compiler，而不只放在 P31 mapper。只读复核未修改代码。
