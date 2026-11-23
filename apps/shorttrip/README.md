# ShortTrip 8795 · 双城参考试排 2.2

Windows 工作台与 Android 2.2 共用 openGauss 账号和行程。PC 服务访问 openGauss 容器并运行规划器，手机通过同一个服务登录。账号、会话、规划任务、修改、反馈、结果文件和数据快照保存在数据库中。

## Windows 安装与启动

1. 安装 64 位 Python 3.12 和 Docker Desktop，使用 Linux 容器。下载并解压 [Windows 安装包](https://github.com/ruojimy/chinatravel-five-city/releases/download/shorttrip-reference-2.2/ShortTrip-OpenGauss-Windows-2.2.zip)。
2. 在该目录打开 PowerShell，运行以下命令。已有 ShortTrip 的电脑请使用原 Windows 账号和原 openGauss 数据卷，新服务会沿用其中的账号和行程。

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-ShortTrip.ps1
   ```

3. 双击安装完成时提示的 `Start.cmd`，再打开 `http://127.0.0.1:8790/`。如果旧服务还在运行，请先关闭旧服务进程以释放端口。首次搭建可在页面注册自己的账号。

默认使用 enmotech 的 openGauss 镜像及其文档要求的 Docker 启动参数，新容器的数据库端口仅绑定本机。 [openGauss 镜像文档](https://hub.docker.com/r/enmotech/opengauss/)

安装程序自动下载并验证[上游 8795 工作台](https://github.com/ccc-cccst/travel-assistant/releases/tag/workbench-8795-20261123)和随附的快照。可用 `-UpstreamZip <路径>` 指定已下载的 ZIP，用 `-Out <目录>` 指定安装目录。默认目录是 `%LOCALAPPDATA%\ShortTrip\8795-r22`。可用 `-Python <python.exe 路径>` 指定 64 位 Python 3.12。已有自管 openGauss 的管理员可设置 `SHORTTRIP_ENV_FILE` 并传入 `-UseConfiguredDatabase`。连接变量见[服务端配置](server/shorttrip_cloud/config.py)。

## Android 2.2

下载 [ShortTrip-Android-2.2.apk](https://github.com/ruojimy/chinatravel-five-city/releases/download/shorttrip-reference-2.2/ShortTrip-Android-2.2.apk)。手机与电脑连上同一局域网后，将 Windows 服务窗口显示的局域网地址填入 App 的「服务器设置」，再用与电脑相同的 ShortTrip 账号登录。Windows 防火墙弹出提示时请允许 Python 在专用网络通信。

Android 应用 ID 为 `cn.shorttrip.workbench`，版本号为 2.2（versionCode 9）。同签名的较早版本可以覆盖安装，已保存的服务器地址会沿用。

## 反馈

在任意工作台页面打开右上角账号面板，选择「反馈问题」。行程页的反馈会关联该行程。打开已经生成的方案也可点「评价方案」，提交采用意向和说明。页面在 openGauss 确认保存后显示成功。

## 数据与来源

安装包导入 `5e0ee8a` 和 `6de12f4`，并将西安和厦门的景点、餐饮、住宿及交通分为正式目录、历史和补充参考、待补证记录。公园、广场、海滩和街道的可核实免费范围进入参考目录。安装结果包含按城市和类型统计的 `catalog-v20.json`。首次导入参考批次后还生成 `catalog-v20-references.json`。西安和厦门可在工作台生成试排行程。开窗和坐标可用的免费地点可参与排程。厦门历史酒店价按间夜估算，大床房按每间两位成人试排。西安采用质量符合条件的高置信估价。原始快照、证据和待补证数据保留在库中。 [数据库字段和入库规则](references/database.md)

仓库源码涵盖账号网关、openGauss schema、目录导入、Windows 安装脚本和 Android 客户端。公开安装包从公共快照建库。原用户的账号、会话、行程和密钥由各实例在本机管理。

- 工作台上游提交 `6abc9680dddbb4ab81dc48d2c369ace74529bb0b`
- 上游 ZIP SHA-256 `e16568379d614757ac4f4e2662bc20a883d45d169a91ea1bfdc1cad73831cfc1`
