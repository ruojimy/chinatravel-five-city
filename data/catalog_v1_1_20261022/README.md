# ChinaTravel标注侧层 v1.1

当前入口catalog.sqlite3：records保存67,612条中英文原库行，tags保存107,978条属性/派生TAG，claims追加动态证据，metadata保存构建清单。

manifest.json列出264个原始文件SHA256和各字段有效期政策；sample_records.jsonl是少量示例，完整跨类型样例在results/p11_freshness_skill/sample_all_kinds.jsonl。源码字段时间缺失都为null；catalogued_at不是源更新时间。字段TTL从已知源观察/更新时间开始计算，未知源时间不能因本次导入续期。

所有静态行可用于冻结基准和候选召回，现实事实状态均为benchmark_only/unknown_source_time，坐标系unknown。没有把研究机构来源、原始0价格或地铁网络的存在当作现实可达性证明。代码许可和数据使用权分开记录。

现实规划先运行项目travel-live-retrieval skill。动态证据逐条门控后使用；claims追加会改变SQLite文件哈希，静态源文件不改写。旧catalog_v1_20261022是保留的初始标注草稿，接续使用本v1_1目录。

完整结果与限制见../../报告/11_数据时效可信度与动态检索Skill.md。
