# Intercity 时长与时间精度只读审阅

## 范围与测试

只读审阅 `src/shorttrip/strict_fields.py::intercity_duration_minutes`、`src/shorttrip/strict_intercity.py::check_intercity` 及其定向测试；未联网、未改源码/测试。运行命令：

```powershell
$env:PYTHONPATH='src;.venv\Lib\site-packages'
& '<local-path>\.workbuddy\binaries\python\versions\3.13.12\python.exe' -m unittest tests.test_strict_fields tests.test_strict_intercity
```

最新文件上的 intercity 定向结果：**14 tests passed**。追加跨日期合约后，三组定向测试合计 **23 tests passed**。另用隔离输入直接探测边界，不写入文件。

## 已确认的性质

- **小时转分钟使用精确 Decimal。** `exact_money` 只接收非负 Python int 或受限长度的规范十进制字符串；binary float、bool、科学计数法、负值和含糊单位均拒绝。`Duration_unit` 必须严格为 `hours`。乘以 60 时提高 Decimal context precision；整数分钟返回 int，分数分钟以十进制文本保留，不走浮点舍入。
- 复算 `2.5` 小时得 150 分钟；`2.0000000000000001` 小时得 `120.0000000000000060` 分钟，和 2 小时时刻表严格冲突，没有容差放行。极小值 `0.0000000000000000001` 也保留成 `0.0000000000000000060` 分钟。
- **日期最大值的跨日溢出 fail closed。** `9999-12-31` 加 arrival offset 1 返回 `unknown / intercity_time_invalid`；offset 2 同样不能跨出 datetime 支持范围。相同最大日期、offset 0、22:00→23:00、Duration=1 小时则可通过，说明是溢出输入被拒绝而非该日期一律不可用。
- **六位以内微秒进入精确比较。** 起止时间均为 `.000001` 秒、相差整 2 小时可通过；实际秒数由 timedelta 的 days、seconds、microseconds 精确构成 Decimal，再与声明时长精确相等比较。
- **旧浮点兼容是 fail closed。** `Duration=2.0`（Python float）经转换返回 None，check_intercity 结果 unknown；同值文本 `"2.0"` 可精确处理，Python int `2` 也可处理。旧客户端如果把 JSON 小数解码成 float，将失去兼容，需在上游保留原始数值文本或发字符串/整数。该行为不会静默近似。

## 边界输入复核与最新结果

首次只读探测发现，当时版本直接把时刻拼接给 `datetime.fromisoformat`，因此 `2300`、逗号小数和超过 6 位的小数秒都能进入解析器；7 位以上的小数会被 Python 截断到微秒。例如 `23:00:00.0000009` 与 `01:00:00.0000001` 加次日 offset 1、`Duration="2"` 曾被解析成整 2 小时并 pass，尽管输入端点相差应比整 2 小时短 0.8 微秒。这是精度语义可被丢弃的边界漏洞。

在本次复核期间，最新实现新增了 ASCII 锚定时刻模式 `HH:MM[:SS[.1-6 digits]]`、ASCII offset 模式，并拒绝 `-00:00` 未知偏移。按最新文件重测，上述超精度输入、紧凑 `2300`、逗号小数、Unicode offset 均返回 unknown；6 位微秒对齐的合法输入仍可通过。最大日期 offset 1 和 2 均返回 `unknown / intercity_time_invalid`，同日 offset 0 的有效用例可通过。原先识别到的精度漏洞在当前读取版本中已关闭。

跨日期独立合约 `strict_cross_date_event._offset` 当前也显式拒绝 `-00:00`，并使用 ASCII offset 表达式；负例已在 `tests/test_strict_cross_date_event.py` 覆盖。建议保留/确认两处对 `-00:00`、7 位以上小数秒、紧凑时刻、逗号小数和 ASCII 边界的回归测试，防止后续改回宽松的 `fromisoformat` 单独解析。

## 限制及判定边界

日期和时刻目前由固定数值 UTC offset 解释，不解析 IANA 时区/DST；这是明确限制。无论测试 callback 返回 True 还是函数返回 pass，callback 才是独立班次、来源、身份与范围验证的信任边界；本次合成 callback 不提供真实性证据。输出仍明确 `execution_confirmed=false`，不能证明可订票、实际运行、来源授权或行程可行性。此次按要求只审阅字段转换及 intercity 时间函数；极大乘客数路径不在此函数范围内，未作结论。
