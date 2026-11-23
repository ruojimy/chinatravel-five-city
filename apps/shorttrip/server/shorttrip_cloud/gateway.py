"""One server for the PC browser and the Android app.

* starts the planner (``chinatravel.personalization.web``) on 127.0.0.1 only;
* hosts the original Workbench (``webui/backend/server.py``) behind account sign-in;
* checks that every request/job/edit ID in an API call belongs to the signed-in account;
* mirrors planner results into GaussDB and restores them when the local cache is missing.
"""
from http.cookies import CookieError, SimpleCookie
from http.server import ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import ProxyHandler, build_opener

from .auth import Accounts, AuthError
from .snapshots import materialize
from .userdata import UserData, valid

COOKIE = "st_session"
WEB_ASSETS = Path(__file__).with_name("web")
PUBLIC_ASSETS = {"/login": "login.html", "/login.html": "login.html", "/account.js": "account.js",
                 "/account.css": "account.css"}
STATIC_SUFFIXES = {".html", ".css", ".js", ".png", ".svg", ".ico", ".webp", ".jpg", ".woff2"}
STATIC_DATA = {"/data/trips.js", "/data/road-reference.js", "/data/booking-sources.json"}
_UNSET = object()


class Release:
    """Paths of an assembled release (see shorttrip_release.json)."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        manifest = self.root / "shorttrip_release.json"
        if not manifest.is_file():
            raise SystemExit(f"{self.root} 不是 ShortTrip 发布目录（缺少 shorttrip_release.json）。")
        self.info = json.loads(manifest.read_text(encoding="utf-8-sig"))  # PowerShell 5.1 writes a BOM
        self.planner = self.root / "combined version_personalized"
        self.webui = self.root / "shorttrip-webui/shorttrip-webui/webui"
        self.data = self.root / "ShortTrip/artifacts/data"
        self.archive = self.planner / self.info["archive"] if self.info.get("archive") else None


def client_kind(headers):
    return "android" if "ShortTripAndroid/" in (headers.get("User-Agent") or "") else "pc"


def make_handler(base, gateway):
    """Subclass the original Workbench handler with sign-in and ownership checks."""

    class GatewayHandler(base):
        server_version = "ShortTrip"
        sys_version = ""

        def setup(self):
            super().setup()
            self._cached_body = _UNSET
            self._filter = None
            self._captured = None
            self.user = None

        # ------------------------------------------------------------ plumbing
        def _body(self):
            if self._cached_body is _UNSET:
                size = int(self.headers.get("Content-Length") or 0)
                if not 0 <= size <= 256_000:
                    raise ValueError("请求内容过长。")
                self._cached_body = json.loads(self.rfile.read(size).decode("utf-8")) if size else {}
            return self._cached_body

        def _json(self, obj, status=200, cookie=None):
            if self._filter is not None and status < 300:
                obj = self._filter(obj)
            self._captured = (status, obj)
            body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            if cookie is not None:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(body)

        def send_header(self, keyword, value):
            if not keyword.lower().startswith("access-control-allow-"):
                super().send_header(keyword, value)

        def end_headers(self):
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            super().end_headers()

        def log_message(self, fmt, *args):
            if args and "/api/" in str(args[0]):
                who = self.user.username if self.user else "-"
                sys.stderr.write(f"[api] {who} {fmt % args}\n")

        def _token(self):
            try:
                morsel = SimpleCookie(self.headers.get("Cookie", "")).get(COOKIE)
            except CookieError:
                return None
            return morsel.value if morsel else None

        def _authenticate(self):
            self.user = gateway.accounts.session(self._token())
            return self.user

        def _cookie(self, token, max_age):
            secure = "; Secure" if gateway.settings.cookie_secure else ""
            return f"{COOKIE}={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax{secure}"

        def _same_origin(self):
            origin = self.headers.get("Origin")
            if origin in (None, "null") and self.headers.get("Sec-Fetch-Site") in (None, "same-origin", "none"):
                return True
            return origin is not None and urlsplit(origin).netloc == self.headers.get("Host")

        def _asset(self, name, content_type):
            body = (WEB_ASSETS / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _redirect(self, location):
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        # ------------------------------------------------------------ HTTP verbs
        def do_OPTIONS(self):
            self.send_error(405)

        def do_GET(self):
            url = urlsplit(self.path)
            path = url.path
            if path in PUBLIC_ASSETS:
                name = PUBLIC_ASSETS[path]
                kind = {"html": "text/html; charset=utf-8", "js": "application/javascript; charset=utf-8",
                        "css": "text/css; charset=utf-8"}[name.rsplit(".", 1)[1]]
                return self._asset(name, kind)
            if path == "/api/health":
                return self._json({"ok": True, "kind": "shorttrip-cloud", "version": gateway.release.info.get("version")})
            user = self._authenticate()
            if path.startswith("/api/"):
                if path == "/api/auth/me":
                    return self._me()
                if not user:
                    return self._json({"message": "请先登录。", "login": True}, 401)
                return self._api_call("GET")
            if path in ("/", "/index.html"):
                if not user:
                    target = path + ("?" + url.query if url.query else "")
                    return self._redirect("/login?next=" + quote(target, safe=""))
                self.path = "/index.html" + ("?" + url.query if url.query else "")
                return super().do_GET()
            if path == "/config.js":
                return self._config()
            if ((Path(path).suffix in STATIC_SUFFIXES or path in STATIC_DATA) and not path.startswith(("/backend/", "/samples/"))
                    and (not path.startswith("/data/") or path in STATIC_DATA) and ".." not in path):
                return super().do_GET()
            self.send_error(404)

        def do_POST(self):
            return self._write("POST")

        def do_PUT(self):
            return self._write("PUT")

        def _write(self, method):
            path = urlsplit(self.path).path
            if not path.startswith("/api/"):
                return self.send_error(404)
            if not self._same_origin():
                return self._json({"message": "跨站请求已被拒绝。"}, 403)
            try:
                if path.startswith("/api/auth/"):
                    return self._auth(path[len("/api/auth/"):])
                if not self._authenticate():
                    return self._json({"message": "登录已过期，请重新登录。", "login": True}, 401)
                return self._api_call(method)
            except (ValueError, KeyError) as error:
                return self._json({"message": f"请求无效：{error}"}, 400)

        def _config(self):
            app = self.app
            config = 'window.SHORTTRIP_API = "";\n' if not app.demo_routes else 'window.SHORTTRIP_ROUTE_LOOKUP = true;\n'
            if app.archive:
                config += "window.SHORTTRIP_ARCHIVE = true;\n"
            if app.personalized:
                config += "window.SHORTTRIP_PERSONALIZED = true;\n"
            config += "window.SHORTTRIP_CLOUD = true;\n"
            config += ("(function(){var s=document.createElement('script');s.src='/account.js';"
                       "document.head.appendChild(s);})();\n")
            body = config.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # ------------------------------------------------------------ accounts
        def _me(self):
            if not self.user:
                return self._json({"message": "未登录。", "login": True,
                                   "register": gateway.settings.allow_register}, 401)
            return self._json({"user": self.user.public(), "client": client_kind(self.headers),
                               "version": gateway.release.info.get("version")})

        def _auth(self, action):
            body = self._body()
            client = client_kind(self.headers)
            agent, remote = self.headers.get("User-Agent"), self.client_address[0]
            try:
                if action in ("login", "register"):
                    if action == "login":
                        user, token = gateway.accounts.login(body.get("username"), body.get("password"),
                                                             client, agent, remote)
                    else:
                        user, token = gateway.accounts.register(body.get("username"), body.get("password"),
                                                                body.get("display_name"), client, agent, remote)
                    max_age = gateway.settings.session_days * 86400
                    return self._json({"user": user.public()}, 201 if action == "register" else 200,
                                      cookie=self._cookie(token, max_age))
                if action == "logout":
                    gateway.accounts.logout(self._token())
                    return self._json({"ok": True}, cookie=self._cookie("", 0))
                if action == "password":
                    user = self._authenticate()
                    if not user:
                        return self._json({"message": "请先登录。", "login": True}, 401)
                    gateway.accounts.change_password(user, body.get("old"), body.get("new"), self._token())
                    return self._json({"ok": True})
            except AuthError as error:
                return self._json({"message": error.message}, error.status)
            return self._json({"message": "找不到账号接口。"}, 404)

        # ------------------------------------------------------------ ownership gate
        def _api_call(self, method):
            url = urlsplit(self.path)
            parts = [p for p in url.path.split("/")[2:] if p]
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            user, data = self.user, gateway.userdata
            if parts == ["account", "trips"] and method == "GET":
                return self._json({"trips": data.trips(user)})
            try:
                denied = self._guard(method, parts, query)
            except (ValueError, KeyError) as error:
                return self._json({"message": f"请求无效：{error}"}, 400)
            if denied:
                return self._json({"message": denied}, 404)
            self._route(method)
            if self._captured:
                try:
                    self._after(method, parts, query, *self._captured)
                except Exception as error:  # noqa: BLE001 - bookkeeping must not break the response
                    sys.stderr.write(f"[gateway] 记录失败: {error!r}\n")

        def _guard(self, method, parts, query):
            """Return an error message when the call touches an object of another account."""
            user, data = self.user, gateway.userdata
            missing = "找不到这份行程，或它属于其他账号。"
            body = self._body() if method in ("POST", "PUT") else {}
            if not isinstance(body, dict):
                raise ValueError("请求体必须是对象")
            key = tuple(parts)
            if method == "GET" and key in {
                    ("workbench-status",), ("archived-trip",), ("archived-trips",), ("route",), ("pois",),
                    ("personalized", "options"), ("personalized", "places"),
                    ("day-facts", "place"), ("day-facts", "weather")}:
                return None
            if method == "POST" and key == ("personalized", "interpret"):
                return None
            if key == ("personalized", "request"):
                rid = query.get("id")
                if not data.can_read_request(user, rid):
                    return missing
                data.ensure_request(rid)
                return None
            if method == "POST" and key in {("personalized", "resolve"), ("personalized", "place-preference"), ("personalized", "start")}:
                rid = body.get("request_id")
                if not data.can_write_request(user, rid):
                    return missing
                data.ensure_request(rid)
                return None
            if key == ("personalized", "job"):
                jid = query.get("id")
                if not data.can_read_job(user, jid):
                    return missing
                data.ensure_job(jid)
                return None
            if key == ("personalized", "adopt"):
                jid = body.get("job_id")
                if not data.can_write_job(user, jid):
                    return missing
                data.ensure_job(jid)
                return None
            if method == "POST" and key in {
                    ("personalized", "feedback"), ("itinerary-edits", "preview"), ("itinerary-edits", "places"),
                    ("itinerary-edits", "assist"), ("itinerary-edits", "prewarm")}:
                jid = body.get("job")
                if not data.can_read_job(user, jid):
                    return missing
                data.ensure_job(jid)
                for edit in (body.get("revision"), body.get("parent")):
                    if edit:
                        if not data.owns_edit(user, edit):
                            return missing
                        data.ensure_edit(edit)
                return None
            if key == ("itinerary-edits", "history"):
                jid = query.get("job")
                if not data.can_read_job(user, jid):
                    return missing
                mine = data.edits_of(user, jid)
                for eid in mine:
                    data.ensure_edit(eid)
                self._filter = lambda versions: [v for v in versions if v.get("id") in mine]
                return None
            if key in {("itinerary-edits", "state"), ("itinerary-edits", "adopt")}:
                eid = query.get("id") if key[1] == "state" else body.get("id")
                if not data.owns_edit(user, eid):
                    return missing
                data.ensure_edit(eid)
                return None
            return "当前版本不提供这个接口。"

        def _after(self, method, parts, query, status, value):
            user, data = self.user, gateway.userdata
            key = tuple(parts)
            body = self._body() if method in ("POST", "PUT") else {}
            if status >= 300 or not isinstance(value, (dict, list)):
                return
            if key in {("personalized", "interpret"), ("personalized", "resolve"), ("personalized", "place-preference")} and value.get("request_id"):
                data.save_request(user.id, value)
            elif key == ("personalized", "start") and valid(value.get("id")):
                data.add_job(user.id, value["id"], body.get("request_id"), client_kind(self.headers))
            elif key == ("personalized", "job"):
                if data.can_write_job(user, query.get("id")):
                    data.job_state(query["id"], value.get("state"))
            elif key == ("personalized", "adopt"):
                data.save_request(user.id, value) if value.get("request_id") else None
                data.sync_later(("manual", body["job_id"]))
            elif key == ("itinerary-edits", "preview") and valid(value.get("id")):
                data.add_edit(user.id, value["id"], body.get("job"))
            elif key in {("itinerary-edits", "state"), ("itinerary-edits", "adopt")}:
                group = value.get("group") or {}
                versions = group.get("versions") or [{}]
                adopted = bool((versions[0].get("revision") or {}).get("adopted"))
                data.edit_state(value.get("id"), value.get("state"), adopted)
            elif key == ("personalized", "feedback") and valid(value.get("id")):
                data.add_feedback(user.id, {"id": value["id"], **body})

    return GatewayHandler


class Gateway:
    def __init__(self, release_root, settings, db, *, host, port, planner_port):
        self.release = Release(release_root)
        self.settings = settings
        self.db = db
        self.host, self.port, self.planner_port = host, port, planner_port
        self.accounts = Accounts(db, settings)
        self.userdata = UserData(db, self.release.planner)
        self.planner_process = None

    # ------------------------------------------------------------ startup
    def prepare_data(self):
        for snapshot in self.release.info["snapshots"]:
            materialize(self.db, snapshot, self.release.data)
        self.userdata.register_examples(self.release.info.get("public_jobs", ()),
                                        self.release.info.get("public_requests", ()))

    def start_planner(self):
        opener = build_opener(ProxyHandler({}))
        address = f"http://127.0.0.1:{self.planner_port}/options"
        try:
            with socket.create_connection(("127.0.0.1", self.planner_port), timeout=1):
                pass
        except (ConnectionRefusedError, TimeoutError):
            pass
        else:
            raise SystemExit(f"规划端口 {self.planner_port} 已占用。请用 --planner-port 选择空闲端口。")
        logs = self.release.planner / "result/workbench_runtime"
        logs.mkdir(parents=True, exist_ok=True)
        log = open(logs / f"planner-{time.strftime('%Y%m%d-%H%M%S')}.log", "w", encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": str(self.release.planner), "PYTHONUTF8": "1"}
        self.planner_process = subprocess.Popen(
            [sys.executable, "-B", "-X", "utf8", "-m", "chinatravel.personalization.web",
             "--port", str(self.planner_port), "--data", str(self.release.data / self.release.info["snapshots"][-1])],
            cwd=self.release.planner, stdout=log, stderr=subprocess.STDOUT, env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        deadline = time.time() + 120
        while time.time() < deadline:
            if self.planner_process.poll() is not None:
                raise SystemExit(f"规划服务启动失败，日志：{log.name}")
            try:
                with opener.open(address, timeout=3) as response:
                    if "cities" in json.load(response) and self.planner_process.poll() is None:
                        print(f"[gateway] 规划服务已就绪 :{self.planner_port}")
                        return
            except OSError:
                time.sleep(0.6)
        raise SystemExit(f"等待规划服务超过 120 秒，日志：{log.name}")

    def build_server(self):
        backend = self.release.webui / "backend"
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        from server import App, Handler  # the original Workbench backend

        args = SimpleNamespace(
            demo_routes=True, five_city=None, python=sys.executable, amap_key=os.environ.get("AMAP_KEY"),
            llm=os.environ.get("SHORTTRIP_LLM", "http://127.0.0.1:18080"),
            model=os.environ.get("SHORTTRIP_MODEL", "qwen3.5-4b-q8"),
            max_evaluations=60, plan_timeout=600, snapshot_roots=self.release.data,
            planner_root=self.release.planner, personalized_archive=self.release.archive,
            personalized_port=self.planner_port,
        )
        handler = make_handler(Handler, self)
        handler.app = App(args)
        return ThreadingHTTPServer((self.host, self.port), handler)

    def serve(self):
        self.prepare_data()
        self.start_planner()
        server = self.build_server()
        threading.Thread(target=self._housekeeping, daemon=True).start()
        print(f"[gateway] ShortTrip {self.release.info.get('version')} 已启动")
        print(f"[gateway] 本机访问 http://127.0.0.1:{self.port}/")
        if self.host in ("0.0.0.0", "::"):
            for address in lan_addresses():
                print(f"[gateway] 手机/局域网访问 http://{address}:{self.port}/")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            if self.planner_process and self.planner_process.poll() is None:
                self.planner_process.terminate()

    def _housekeeping(self):
        while True:
            try:
                self.accounts.purge_expired()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(3600)


def lan_addresses():
    found = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # no packet is sent; selects the outgoing interface
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        found.extend(addr[4][0] for addr in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    tunnel = ipaddress.IPv4Network("198.18.0.0/15")
    return [value for value in dict.fromkeys(found)
            if (addr := ipaddress.IPv4Address(value)).is_private
            and not addr.is_loopback and not addr.is_link_local and addr not in tunnel]
