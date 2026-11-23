# 网关接口归属规则（P042 与 8795）

未登录：`/login`、`/account.js`、`/account.css`、`/api/health`、`/api/auth/*` 可访问；`/` 跳转登录页；其他 `/api/*` 返回 401。
静态文件只放行 webui 下的 html/css/js/图片，`/backend/`、`/samples/`、`/data/`（除 `trips.js`、`road-reference.js`、`booking-sources.json`）一律 404。
所有 POST/PUT 要求 `Origin` 与 `Host` 一致（防 CSRF），Cookie 为 `HttpOnly; SameSite=Lax`。

| 方法 | 接口 | 检查 | 之后 |
| --- | --- | --- | --- |
| GET | workbench-status, archived-trip, archived-trips, route, pois, personalized/options, personalized/places, day-facts/place, day-facts/weather | 已登录 | — |
| POST | personalized/interpret | 已登录 | 记录需求归属，镜像 `result/tripspec/<id>` |
| GET | personalized/request?id= | 可读需求（本人或示例） | 缺失则从库还原 |
| POST | personalized/resolve, personalized/place-preference, personalized/start {request_id} | 本人需求 | resolve 和 place-preference：更新需求；start：记录任务归属（含客户端 pc/android），镜像 `result/inputs/<job>.json` |
| GET | personalized/job?id= | 可读任务 | 状态变化时镜像 `result/manual/<job>` |
| POST | personalized/adopt {job_id} | 本人任务 | 更新需求、镜像任务 |
| POST | personalized/feedback {job, revision?} | 可读任务 + 本人修改 | 写 `st_feedback` |
| POST | itinerary-edits/preview, places, assist, prewarm {job, parent?} | 可读任务 + 本人修改 | preview：记录修改归属 |
| GET | itinerary-edits/history?job= | 可读任务 | 响应只保留本人修改（上游会扫描全部用户的修改） |
| GET/POST | itinerary-edits/state?id= / adopt {id} | 本人修改 | 记录状态/采用，镜像 `result/workbench_edits/<id>` |
| GET | account/trips | 已登录 | 本人任务 + 示例 |
| 其他 | — | 返回"当前版本不提供这个接口" | — |

示例行程：发布时 `result/manual`、`result/tripspec` 里已有的目录写入 `shorttrip_release.json` 的 `public_jobs`/`public_requests`，以 `user_id NULL` 入库，所有账号只读。不在表里的目录（例如旧版单机时期的数据）任何账号都打不开。
