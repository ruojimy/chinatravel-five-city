"""Accounts and sessions shared by the PC browser and the Android app.

Password hashes use the same format as the database course project
(``pbkdf2:sha256:600000$salt$hex``, compatible with werkzeug), but are computed with hashlib
so the server needs no extra dependency. Failed logins and lockouts are stored in the
database, so they survive restarts and apply to both clients.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets

ITERATIONS = 600_000
MAX_FAILURES = 5
LOCK_MINUTES = 15
USERNAME = re.compile(r"[A-Za-z0-9_]{3,32}")
_DUMMY = None


class AuthError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class User:
    id: int
    username: str
    display_name: str
    role: str

    def public(self):
        return {"username": self.username, "display_name": self.display_name, "role": self.role}


def hash_password(password):
    salt = secrets.token_urlsafe(12)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), ITERATIONS).hex()
    return f"pbkdf2:sha256:{ITERATIONS}${salt}${digest}"


def verify_password(password, stored):
    try:
        method, salt, expected = stored.split("$", 2)
        kind, algorithm, rounds = method.split(":")
        if kind != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(algorithm, password.encode("utf-8"), salt.encode("utf-8"), int(rounds)).hex()
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(digest, expected)


def _dummy_hash():
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password(secrets.token_hex(8))
    return _DUMMY


def check_new_password(password):
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise AuthError("密码长度需为 8–128 位。")
    if not (re.search(r"[A-Za-z]", password) and re.search(r"[0-9]", password)):
        raise AuthError("密码需同时包含字母和数字。")


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Accounts:
    def __init__(self, db, settings):
        self.db = db
        self.session_days = settings.session_days
        self.allow_register = settings.allow_register

    # ------------------------------------------------------------- audit
    def audit(self, user_id, action, detail=None, client=None, remote=None):
        self.db.run("INSERT INTO st_audit_log (user_id, action, detail, client, remote_addr) VALUES (%s,%s,%s,%s,%s)",
                    (user_id, action, (detail or "")[:2000] or None, client, remote))

    # ------------------------------------------------------------- accounts
    def create_user(self, username, password, display_name=None, role="user"):
        if not isinstance(username, str) or not USERNAME.fullmatch(username):
            raise AuthError("用户名需为 3–32 位字母、数字或下划线。")
        check_new_password(password)
        display_name = (display_name or username).strip()[:32] or username
        try:
            with self.db.tx() as cur:
                cur.execute("SELECT 1 FROM st_user WHERE lower(username) = lower(%s)", (username,))
                if cur.fetchone():
                    raise AuthError("该用户名已被注册。", 409)
                cur.execute("INSERT INTO st_user (username, display_name, password_hash, role) "
                            "VALUES (%s,%s,%s,%s) RETURNING id",
                            (username, display_name, hash_password(password), role))
                user_id = cur.fetchone()[0]
        except self._unique_violation():
            raise AuthError("该用户名已被注册。", 409) from None
        return User(user_id, username, display_name, role)

    @staticmethod
    def _unique_violation():
        from .db import UniqueViolation
        return UniqueViolation

    def register(self, username, password, display_name, client, user_agent, remote):
        if not self.allow_register:
            raise AuthError("服务器未开放注册，请联系管理员创建账号。", 403)
        user = self.create_user(username, password, display_name)
        self.audit(user.id, "register", None, client, remote)
        return user, self._new_session(user, client, user_agent)

    def login(self, username, password, client, user_agent, remote):
        if not isinstance(username, str) or not isinstance(password, str) or len(password) > 128:
            raise AuthError("请输入用户名和密码。")
        row = self.db.one("SELECT id, username, display_name, role, password_hash, is_active, failed_logins, "
                          "locked_until, now() FROM st_user WHERE lower(username) = lower(%s)", (username.strip(),))
        if row is None:
            verify_password(password, _dummy_hash())  # keep timing similar for unknown names
            self.audit(None, "login_failed", f"unknown user {username[:32]}", client, remote)
            raise AuthError("用户名或密码错误。", 401)
        user_id, name, display, role, stored, active, failures, locked_until, now = row
        if not active:
            raise AuthError("账号已停用。", 403)
        if locked_until and locked_until > now:
            minutes = max(1, int((locked_until - now).total_seconds() // 60) + 1)
            raise AuthError(f"连续输错密码，账号已临时锁定，请 {minutes} 分钟后再试。", 423)
        if not verify_password(password, stored):
            failures += 1
            if failures >= MAX_FAILURES:
                self.db.run("UPDATE st_user SET failed_logins = 0, locked_until = now() + interval '1 minute' * %s "
                            "WHERE id = %s", (LOCK_MINUTES, user_id))
                self.audit(user_id, "locked", None, client, remote)
                raise AuthError(f"连续输错 {MAX_FAILURES} 次，账号锁定 {LOCK_MINUTES} 分钟。", 423)
            self.db.run("UPDATE st_user SET failed_logins = %s WHERE id = %s", (failures, user_id))
            self.audit(user_id, "login_failed", None, client, remote)
            raise AuthError(f"用户名或密码错误（还可尝试 {MAX_FAILURES - failures} 次）。", 401)
        self.db.run("UPDATE st_user SET failed_logins = 0, locked_until = NULL, last_login_at = now() WHERE id = %s",
                    (user_id,))
        user = User(user_id, name, display, role)
        self.audit(user_id, "login", None, client, remote)
        return user, self._new_session(user, client, user_agent)

    def change_password(self, user, old, new, keep_token):
        row = self.db.one("SELECT password_hash FROM st_user WHERE id = %s", (user.id,))
        if not row or not verify_password(old or "", row[0]):
            raise AuthError("原密码不正确。", 401)
        check_new_password(new)
        with self.db.tx() as cur:
            cur.execute("UPDATE st_user SET password_hash = %s WHERE id = %s", (hash_password(new), user.id))
            # Sign out every other device that used the old password.
            cur.execute("DELETE FROM st_session WHERE user_id = %s AND token_hash <> %s",
                        (user.id, token_hash(keep_token)))
        self.audit(user.id, "password_changed")

    # ------------------------------------------------------------- sessions
    def _new_session(self, user, client, user_agent):
        token = secrets.token_urlsafe(32)
        self.db.run("INSERT INTO st_session (token_hash, user_id, client, user_agent, expires_at) "
                    "VALUES (%s,%s,%s,%s, now() + interval '1 day' * %s)",
                    (token_hash(token), user.id, client, (user_agent or "")[:256], self.session_days))
        return token

    def session(self, token):
        if not token or len(token) > 128:
            return None
        hashed = token_hash(token)
        row = self.db.one("SELECT u.id, u.username, u.display_name, u.role, s.last_seen_at, now() "
                          "FROM st_session s JOIN st_user u ON u.id = s.user_id "
                          "WHERE s.token_hash = %s AND s.expires_at > now() AND u.is_active", (hashed,))
        if row is None:
            return None
        user_id, name, display, role, seen, now = row
        if now - seen > timedelta(minutes=5):
            # Sliding expiry, written at most every five minutes per session.
            self.db.run("UPDATE st_session SET last_seen_at = now(), expires_at = now() + interval '1 day' * %s "
                        "WHERE token_hash = %s", (self.session_days, hashed))
        return User(user_id, name, display, role)

    def logout(self, token):
        if token:
            self.db.run("DELETE FROM st_session WHERE token_hash = %s", (token_hash(token),))

    def purge_expired(self):
        return self.db.run("DELETE FROM st_session WHERE expires_at < now()")

    @staticmethod
    def utcnow():
        return datetime.now(timezone.utc)
