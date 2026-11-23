# ShortTrip 服务器（电脑版 + 安卓版共用）

这一版把账号、行程和旅行数据都放进 openGauss/GaussDB。电脑浏览器和安卓 App 登录同一个账号，看到同一份行程；本目录不再附带 200 多 MB 的数据快照，首次启动时从数据库还原并逐个校验 SHA-256。

## 启动

1. 确认 openGauss 在运行（Docker 容器 `opengauss`），连接信息在 `%LOCALAPPDATA%\ShortTrip\server.env`。
2. 双击 `Start-Server.cmd`（或 `python start_server.py`）。首次会建虚拟环境并安装依赖。
3. 窗口会打印两个地址：
   - 本机：`http://127.0.0.1:8790/`
   - 手机/局域网：`http://192.168.x.x:8790/` —— 填进安卓 App 的「服务器设置」。
4. 首次打开会进入登录页，可直接注册账号。

Windows 第一次弹出防火墙提示时，需要允许 Python 在「专用网络」通信，手机才能连上。

## 可选配置（写在 server.env）

| 键 | 作用 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 自然语言需求提取与模型构想 |
| `AMAP_KEY` | 高德 Web 服务路线 |
| `SHORTTRIP_ALLOW_REGISTER=0` | 关闭自助注册，改用 `python -m shorttrip_cloud create-user` |
| `SHORTTRIP_SESSION_DAYS` | 登录保持天数，默认 30 |

## 数据在哪里

| 内容 | 表 |
| --- | --- |
| 账号、登录会话、审计日志 | `st_user`、`st_session`、`st_audit_log` |
| 需求、规划任务、行程修改、评价 | `st_trip_request`、`st_trip_job`、`st_itinerary_edit`、`st_feedback` |
| 规划结果文件（按内容去重） | `st_object_file` → `st_blob` / `st_blob_chunk` |
| 旅行数据快照、可查询地点目录 | `st_snapshot`、`st_snapshot_file`、`st_catalog_record`、`st_catalog_tag` |
| 发布版本（PC 包 + APK） | `st_release` |

`combined version_personalized/result/` 和 `ShortTrip/artifacts/data/` 现在只是缓存，删掉后会按需从数据库还原。查看库内概况：`python -m shorttrip_cloud status`（在虚拟环境中、`PYTHONPATH` 指向本目录）。
