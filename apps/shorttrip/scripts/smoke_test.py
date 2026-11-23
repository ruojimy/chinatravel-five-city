"""End-to-end check of a running ShortTrip cloud server.

    python smoke_test.py --server http://127.0.0.1:8790 [--plan] [--release <release>/ShortTrip] [--keep]

Covers: login redirect, registration, cross-account isolation, CSRF rejection, lockout,
the bundled example, a real planning run (--plan), restoring a job from GaussDB after its
local folder is deleted (--release), and the Android client marker. Test accounts are
removed at the end unless --keep (needs --release to reach the database).
"""
import argparse
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
import json
from pathlib import Path
import re
import secrets
import shutil
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

PASSWORD = "Smoke" + secrets.token_hex(4) + "9a"
results = []


class Client:
    def __init__(self, server, android=False):
        self.server = server.rstrip("/")
        self.jar = CookieJar()
        # ProxyHandler({}) — never send LAN/loopback calls through HTTP(S)_PROXY.
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(self.jar), NoRedirect())
        self.agent = "Mozilla/5.0 smoke" + (" ShortTripAndroid/2.0" if android else "")

    def call(self, method, path, body=None, origin=True, headers=None):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = Request(self.server + path, data=data, method=method)
        request.add_header("User-Agent", self.agent)
        if data is not None:
            request.add_header("Content-Type", "application/json")
            if origin:
                request.add_header("Origin", self.server)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with self.opener.open(request, timeout=60) as response:
                raw = response.read()
                return response.status, _json(raw), response.headers
        except HTTPError as error:
            with error:
                return error.code, _json(error.read()), error.headers


class NoRedirect(__import__("urllib.request").request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _json(raw):
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return raw[:200].decode("utf-8", "replace")


def check(name, condition, detail=""):
    results.append((name, bool(condition)))
    print(("  PASS " if condition else "  FAIL ") + name + ("" if condition else f"  -> {detail}"))
    return condition


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://127.0.0.1:8790")
    parser.add_argument("--plan", action="store_true", help="run one real planning job (about 1-3 minutes)")
    parser.add_argument("--date", type=lambda value: datetime.fromisoformat(value).date(),
                        default=datetime.now(timezone(timedelta(hours=8))).date() + timedelta(days=1),
                        help="departure date for the planning fixture")
    parser.add_argument("--release", type=Path, help="release folder, enables restore test and cleanup")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    tag = secrets.token_hex(3)
    alice, bob = Client(args.server), Client(args.server, android=True)
    names = (f"smoke_a_{tag}", f"smoke_b_{tag}")

    print("== 基础")
    status, value, _ = alice.call("GET", "/api/health")
    check("health", status == 200 and value.get("kind") == "shorttrip-cloud", value)
    status, _, headers = alice.call("GET", "/?new=1")
    check("未登录访问首页跳转到登录页", status == 302 and headers.get("Location", "").startswith("/login"), status)
    status, _, _ = alice.call("GET", "/api/personalized/options")
    check("未登录调用接口返回 401", status == 401, status)
    status, _, _ = alice.call("GET", "/backend/server.py")
    check("后端源码不可下载", status == 404, status)

    print("== 账号")
    status, value, _ = alice.call("POST", "/api/auth/register", {"username": names[0], "password": PASSWORD})
    check("注册账号 A（电脑）", status == 201, value)
    status, value, _ = bob.call("POST", "/api/auth/register", {"username": names[1], "password": PASSWORD,
                                                                 "display_name": "测试B"})
    check("注册账号 B（安卓）", status == 201, value)
    status, value, _ = bob.call("GET", "/api/auth/me")
    check("安卓客户端被识别", status == 200 and value.get("client") == "android", value)
    status, value, _ = alice.call("POST", "/api/auth/register", {"username": names[0].upper(), "password": PASSWORD})
    check("用户名不区分大小写防重复", status == 409, value)
    status, value, _ = alice.call("POST", "/api/auth/register", {"username": "x" + tag, "password": "short"})
    check("弱密码被拒绝", status == 400, value)
    status, value, _ = alice.call("POST", "/api/auth/login", {"username": names[0], "password": PASSWORD},
                                  headers={"Origin": "http://evil.example"})
    check("跨站 POST 被拒绝", status == 403, value)

    print("== 行程隔离")
    status, options, _ = alice.call("GET", "/api/personalized/options")
    check("读取城市选项", status == 200 and options.get("cities"), options)
    cities = options.get("cities") or ["上海", "杭州"]
    origin_city = "上海" if "上海" in cities else cities[0]
    target_city = "杭州" if "杭州" in cities else cities[-1]
    new_workbench = "model_providers" in options
    if new_workbench:
        status, archives, _ = alice.call("GET", "/api/archived-trips")
        check("工作台示例归档列表", status == 200 and isinstance(archives, list) and bool(archives), status)
        query = urlencode({"city": target_city, "q": "西湖" if target_city == "杭州" else ""})
        status, places, _ = alice.call("GET", f"/api/personalized/places?{query}")
        check("新版景点搜索", status == 200 and isinstance(places.get("places"), list), places)
        status, _, _ = alice.call("GET", "/data/booking-sources.json")
        check("可读取新版订票来源配置", status == 200, status)
    form = {"start_city": origin_city, "target_city": target_city, "days": 2, "people_number": 2,
            "start_date": args.date.isoformat()}
    status, spec, _ = alice.call("POST", "/api/personalized/interpret",
                                 {"raw_text": "", "form": form, "model_provider": "program"})
    check("A 提交需求", status == 200 and spec.get("request_id"), spec)
    rid = spec.get("request_id", "0" * 32)
    status, _, _ = bob.call("GET", f"/api/personalized/request?id={rid}")
    check("B 读不到 A 的需求", status == 404, status)
    status, value, _ = alice.call("GET", f"/api/personalized/request?id={rid}")
    check("A 能读自己的需求", status == 200 and value.get("request_id") == rid, value)
    if new_workbench:
        update = {"request_id": rid, "request_revision": spec.get("request_revision"), "place_id": "", "choice": "clear"}
        status, _, _ = bob.call("POST", "/api/personalized/place-preference", update)
        check("B 无法更改 A 的景点偏好", status == 404, status)
        status, _, _ = alice.call("POST", "/api/personalized/place-preference", update)
        check("新版景点偏好请求由规划器校验", status == 400, status)
    status, value, _ = bob.call("POST", "/api/personalized/start", {
        "request_id": rid, "request_revision": spec.get("request_revision", 1), "submission_id": secrets.token_hex(16)})
    check("B 不能用 A 的需求发起规划", status == 404, value)

    job = None
    if spec.get("ready"):
        status, value, _ = alice.call("POST", "/api/personalized/start", {
            "request_id": rid, "request_revision": spec["request_revision"], "try_budget_alternatives": False,
            "submission_id": secrets.token_hex(16)})
        check("A 发起规划", status == 202 and value.get("id"), value)
        job = value.get("id")
    else:
        check("需求可直接规划", False, spec.get("issues"))
    if job:
        status, _, _ = bob.call("GET", f"/api/personalized/job?id={job}")
        check("B 读不到 A 的规划任务", status == 404, status)
        status, value, _ = bob.call("GET", f"/api/itinerary-edits/history?job={job}&original=x")
        check("B 读不到 A 的修改历史", status == 404, status)
        status, value, _ = alice.call("GET", "/api/account/trips")
        mine = [t for t in value.get("trips", []) if t["job"] == job]
        check("A 的云端行程列表含新任务", status == 200 and mine and mine[0]["client"] == "pc", value)
        status, value, _ = bob.call("GET", "/api/account/trips")
        check("B 的列表不含 A 的任务", status == 200 and all(t["job"] != job for t in value.get("trips", [])), value)
        android_alice = Client(args.server, android=True)
        status, _, _ = android_alice.call("POST", "/api/auth/login", {"username": names[0], "password": PASSWORD})
        check("PC 账号可以在安卓登录", status == 200, status)
        status, value, _ = android_alice.call("GET", "/api/account/trips")
        check("安卓同账号能看到 PC 创建的任务", status == 200 and any(t["job"] == job for t in value.get("trips", [])), value)
        if new_workbench:
            for action in ("assist", "prewarm"):
                status, _, _ = bob.call("POST", f"/api/itinerary-edits/{action}", {"job": job})
                check(f"B 无法调用 A 的新版编辑接口 {action}", status == 404, status)
            status, _, _ = alice.call("POST", "/api/itinerary-edits/assist", {"job": job})
            check("新版编辑请求由后端校验", status == 409, status)
        status, value, _ = bob.call("GET", "/api/account/trips")
        examples = [t for t in value.get("trips", []) if t.get("example")]
        if check("B 能看到随包示例", examples, value) and examples:
            status, value, _ = bob.call("GET", f"/api/personalized/job?id={examples[0]['job']}")
            check("示例任务可打开", status == 200 and value.get("state"), value)

    if job and args.plan:
        print("== 规划（等待最多 300 秒）")
        deadline, state = time.time() + 300, None
        while time.time() < deadline:
            status, value, _ = alice.call("GET", f"/api/personalized/job?id={job}")
            state = value.get("state") if isinstance(value, dict) else None
            if state not in ("starting", "planning", None):
                break
            time.sleep(4)
        check("规划结束", state not in ("starting", "planning", None), state)
        check("得到已核验行程", state == "complete" and value.get("group"), value.get("message") if isinstance(value, dict) else value)
        if args.release:
            time.sleep(3)  # background mirror to GaussDB
            manual = (args.release / "combined version_personalized/result/manual").resolve()
            folder = (manual / job).resolve()
            if not re.fullmatch(r"[a-f0-9]{32}", job) or folder.parent != manual:
                raise ValueError("Smoke test tried to remove a folder outside the disposable planning job")
            shutil.rmtree(folder, ignore_errors=True)
            check("已删除本地任务目录", not folder.exists())
            status, again, _ = alice.call("GET", f"/api/personalized/job?id={job}")
            check("从 GaussDB 还原任务并照常打开", status == 200 and again.get("state") == state
                  and bool(again.get("group")) == bool(value.get("group")), again)
            check("本地目录已重建", folder.is_dir())

    print("== 锁定与退出")
    for attempt in range(5):
        status, value, _ = bob.call("POST", "/api/auth/login", {"username": names[1], "password": "wrong-pass-1"})
    check("连续输错 5 次锁定", status == 423, value)
    status, value, _ = bob.call("POST", "/api/auth/login", {"username": names[1], "password": PASSWORD})
    check("锁定期间正确密码也不能登录", status == 423, value)
    status, _, _ = alice.call("POST", "/api/auth/logout", {})
    status, _, _ = alice.call("GET", "/api/auth/me")
    check("退出后会话失效", status == 401, status)

    if args.release and not args.keep:
        sys.path.insert(0, str(args.release))
        from shorttrip_cloud import config
        from shorttrip_cloud.db import Database
        db = Database(config.load())
        ids = [r[0] for r in db.all("SELECT j.job_id FROM st_trip_job j JOIN st_user u ON u.id = j.user_id "
                                    "WHERE u.username IN (%s, %s)", names)]
        ids += [r[0] for r in db.all("SELECT r.request_id FROM st_trip_request r JOIN st_user u ON u.id = r.user_id "
                                     "WHERE u.username IN (%s, %s)", names)]
        for oid in ids:
            db.run("DELETE FROM st_object_file WHERE object_id = %s", (oid,))
        db.run("DELETE FROM st_audit_log WHERE user_id IN (SELECT id FROM st_user WHERE username IN (%s, %s))", names)
        db.run("DELETE FROM st_user WHERE username IN (%s, %s)", names)
        db.close()
        print(f"== 已清理测试账号 {names[0]}, {names[1]}（本地 result/ 缓存中的测试任务目录保留，可手动删除）")

    failed = [name for name, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} 项通过" + (f"；失败：{', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
