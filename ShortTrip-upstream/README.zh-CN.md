# ShortTrip 当前架构

基于 ChinaTravel / LLMNeSy，包含自然语言约束翻译、数据库检索、DFS、硬约束提前剪枝、
四类软约束评分和最多20个可行候选选优。

当前版本加入灵活三餐顺序、原文依据与数据库名称对齐、确定性约束代码模板、有限次翻译修复、
交通班次过滤、费用下界、三餐乐观预检，以及具体剪枝原因记录。

安装依赖并下载固定版本数据后，可运行 C 组的 easy、human 各五例。实验入口使用单独部署的
本地 Qwen3.5-4B Q8 服务，地址为 `http://127.0.0.1:18080/v1`，模型别名为 `qwen3.5-4b-q8`。
每例运行一次，串行执行，目标20候选，单例限时30分钟。

```sh
python -m pip install -r requirements.txt
python scripts/bootstrap_data.py --lang both
python experiments/c_only/prepare.py
python experiments/c_only/driver.py
```

`prepare.py` 生成运行配置和源码哈希，`driver.py` 开始模型请求。
完整 HTML 输出到 `experiments/c_only/itineraries.html`。
源码包含离线测试和固定输入案例。数据目录、模型权重、密钥、缓存及实验结果由 Git 忽略。

架构、限制与测试说明见 `ARCHITECTURE.md`、`docs/pruning.md` 和 `VERIFICATION.md`。
英文安装说明见 `README.md`，原项目说明与许可保留在 upstream README 和 `LICENSE`。
