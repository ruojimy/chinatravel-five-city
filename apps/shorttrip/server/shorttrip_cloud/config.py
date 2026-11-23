"""Settings come from environment variables, then from the private server.env file.

The default file is %LOCALAPPDATA%/ShortTrip/server.env so that database passwords and
API keys never live inside a release folder or a skill folder.
"""
from dataclasses import dataclass
import os
from pathlib import Path

# Keys copied into the planner's environment when they are only present in server.env.
SERVICE_KEYS = ("DEEPSEEK_API_KEY", "AMAP_KEY")


def default_env_file():
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".config")
    return Path(base) / "ShortTrip" / "server.env"


def load_env_file(path=None):
    path = Path(path or os.environ.get("SHORTTRIP_ENV_FILE") or default_env_file())
    values = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    db_schema: str
    session_days: int
    cookie_secure: bool
    allow_register: bool


def load(env_file=None):
    file = load_env_file(env_file)

    def get(key, default=None):
        return os.environ.get(key) or file.get(key) or default

    for key in SERVICE_KEYS:
        if file.get(key) and not os.environ.get(key):
            os.environ[key] = file[key]
    password = get("SHORTTRIP_DB_PASSWORD")
    if not password:
        raise SystemExit("缺少数据库密码：请在 %s 或环境变量中设置 SHORTTRIP_DB_PASSWORD。" % default_env_file())
    return Settings(
        db_host=get("SHORTTRIP_DB_HOST", "127.0.0.1"),
        db_port=int(get("SHORTTRIP_DB_PORT", "8888")),
        db_name=get("SHORTTRIP_DB_NAME", "shorttrip"),
        db_user=get("SHORTTRIP_DB_USER", "shorttrip"),
        db_password=password,
        db_schema=get("SHORTTRIP_DB_SCHEMA", "shorttrip"),
        session_days=int(get("SHORTTRIP_SESSION_DAYS", "30")),
        cookie_secure=get("SHORTTRIP_COOKIE_SECURE", "0") == "1",
        allow_register=get("SHORTTRIP_ALLOW_REGISTER", "1") == "1",
    )
