# 十一城主沙盒：动态证据与多段接驳

主环境代码位于 `ShortTrip-upstream/chinatravel/`，规则规划器位于 `src/shorttrip/`。默认仍为原生十城；通过 `scripts/g3_sandbox.py` 可显式启用 `data/sandbox_profiles/xian_n16v2`。公开快照包含西安与原十城的场所及城际数据、字段级来源和哈希清单。

```bash
python -X utf8 scripts/g3_sandbox.py --profile data/sandbox_profiles/xian_n16v2
```

写一个 UTF-8 的 `route.json`，例如 `{"from_city":"南京","to_city":"西安","mode":"train"}`，然后运行：

```bash
python -X utf8 scripts/g3_sandbox.py --profile data/sandbox_profiles/xian_n16v2 --tool intercity_search --args-file route.json
```

可用方法包括 `catalog_list`、`catalog_search`、`catalog_entity`、`catalog_preflight`、`reference_search`、`intercity_search` 和 `goto`。静态参考中的价格或班次没有指定旅行日，不能用于证明可购票。高德来源只接入有原始证据、唯一车次和席别的直达记录；换乘总价不能当作单段车票。景点在实际搜索后仍查不到价格时，可以使用标记清楚的零元规划假设，不等于确认免费。

本地接驳检查支持连续步行、出租及完整步行—地铁—步行段，逐段核对时间、距离、费用和人数；无可靠路线时为 unknown。南京南站别名仅在快照、高德原始响应、唯一站点身份和坐标等证据匹配时成立，不普遍放宽站点距离。

## 日期限定数据和隐私边界

`data/observations/train_20261116/xian_11city_reference.json` 是 2026-11-16 采集的西安与原十城铁路观察摘要，保留 20 个方向、776 条可核对的展示价和 4 条隔离记录。为避免公开预订令牌和本地会话材料，原始 12306 响应不包含在公开包中；该摘要是参考，不是可通过公开包独立重解析的原始证据，也不证明当前有票。`CT_OFFICIAL_FARE_SIDECAR` 和 `CT_OFFICIAL_DISPLAY_SIDECAR` 支持由使用者自行提供完整、本地安全保存的带日期来源证据；需显式指定每段日期及席别，缺项时不会套用数据。

`data/observations/flight_20261116/` 包含 18 个方向的单来源历史航班页面和原文哈希；将该目录设置为 `CT_FLIGHT_REFERENCE_ROOT`，指定 `travel_date=2026-11-16` 可作为参考读取。税费、库存及购买状态未知，不作为已确认预订。

公开快照为本地冻结评测快照的脱敏导出，删除了与本版本范围无关的一条地图查询、12 条航班记录并移除了本机路径，因此其哈希不同。公开快照 `dynamic_snapshot_v2.json` SHA-256 为 `a36125283631e2a730025ad0739090c957e775eaafbdf49a78aae57a507645b1`；本地评测原快照为 `6c3d34f6c233db1919a78b78bbd2eb9abd78340b7bbcf5728b07a40f30b66be2`。不要把公开副本作为冻结评测的逐字节重放输入。

如需在线高德检索，可使用 `--live-dir` 创建新的独立日志目录，并在本地配置密钥；拒绝或限流后暂停，不轮换密钥。仓库不包含密钥、登录 cookie 或模型权重。

## 评测结果

2026-11-16 冻结的十一城 18 题 Luna 与 60 题规则器结果、逐题脱敏记录、原文件和公开副本哈希见 [`results/g3-20261116/RESULTS.md`](../results/g3-20261116/RESULTS.md)。规则器可读取硬约束和检查器反馈，Luna 不可，比较不能视为完全同信息条件。数据阻塞、未成案、unknown 与评分失败分开统计。
