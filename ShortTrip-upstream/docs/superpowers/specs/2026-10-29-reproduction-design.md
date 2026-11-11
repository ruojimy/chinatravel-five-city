# ChinaTravel 三案例复现方案

状态：三个固定案例已完成实际运行、原版评估、HTML 导出及 JSON 一致性验证；详见 reproduction/README.zh-CN.md。

## 目标与边界

在当前项目中配置 Python 3.12 独立环境，使用 DeepSeek V4.1 Flash，分别复现 easy、medium、human 一个官方案例。保留原始结果 JSON、约束翻译缓存、搜索日志、原版评估结果，并生成可离线打开的 HTML 完整行程。

## 架构与方案

建议采用 README 默认的 LLMNeSy：原版自然语言到 DSL 翻译与反思、LLM 候选排序、WorldEnv 沙盒检索、符号搜索、常识及硬约束验证。直接调用现有 run_exp.py 与 eval_exp.py；不启用 oracle_translation，不绕过搜索或注入预制行程。

仓库另有 ReAct、LLM-modulo、TPCAgent 等不同算法；它们改变研究对象，只有用户明确指定时才选用。

## 模型配置

官方文档 https://api-docs.deepseek.com/ 于 2026-10-29 核实：模型 ID deepseek-flash 当前对应 DeepSeek-V4.1-Flash-1017，Base URL 为 https://api.deepseek.com，使用 Chat Completions。

密钥读取 CHINATRAVEL_OPENAI_API_KEY 或本地忽略文件，不写入报告、日志或版本文件。第三方服务需要其精确 Base URL 与模型 ID。

执行中诊断确认服务端默认思考会耗尽原版 4096 输出额度而不返回正文。保留初始实验后，使用独立启动适配层，通过现有模型工厂参数明确关闭服务端思考；max_tokens 仍为 4096。所有原版核心文件、提示词、搜索与评估保持不变。

## 固定案例（建议按官方 CSV 原始顺序第一条）

| split | UID | 行程 |
| --- | --- | --- |
| easy | e20241028160248698752 | 上海至杭州，1 人 1 天，预算 1500 元 |
| medium | e20241028160842228543 | 上海至北京，2 人 3 天，预算 6000 元，地铁及房型约束 |
| human | h20241029143447759844 | 上海至苏州，父子 2 人 3 天，轻松自由行 |

固定样本不根据成功率替换。原始评估不能完整衡量“轻松”等主观需求，应在报告中保留原始需求供人工对照。

## 数据准备与可追溯性

采用 LAMDA-NeSy/ChinaTravel 官方 Query 和 ChinaTravel-Sandbox 官方中文 raw ZIP。保存数据 revision、原始文件及 SHA-256，按发布 manifest 校验沙盒。

已通过只读核对发现：CSV 的 hard_logic_py 是字符串，而当前 load_datasets.py 明确要求列表。仅在数据准备层使用安全字面量解析还原列表、正确转换数字及布尔类型，保存为本地 Query JSON 和独立 split 清单；不修改原版算法和评估逻辑。规划输入由原版加载器去除 Oracle 字段，评估读取完整原始约束。

## 输出

HTML 按案例和日期展示所有活动与关联市内交通，包括起止时间、地点、车次或航班、人数、票数、房型、房间数和费用；提供总费用与每日费用、原始需求、评估结果、运行统计和原始 JSON 查看/下载。不得省略未识别字段，可通过完整 JSON 展示。

保留失败、超时或部分满足约束的真实状态；没有实际运行结果时不生成伪造行程。

## 验证

检查沙盒校验和及环境工具可用性；运行仓库相关回归测试；对三个真实结果运行原版 schema、常识和硬约束评估；核对 HTML 中活动和交通数量、费用与 JSON 一致，并在浏览器检查版式。

## 当前前置条件

Python 3.12 和 uv 已存在；完整依赖、沙盒与 Query 尚未安装。当前进程未检测到 OpenAI/DeepSeek API 凭据。网络只读访问已通过沙盒审批验证可用。项目没有 .git 目录。
