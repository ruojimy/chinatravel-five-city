"""Thread-safe psycopg2 access to openGauss / GaussDB (also works on PostgreSQL).

openGauss differences handled here and in the SQL of this package:
- no ``INSERT ... ON CONFLICT``: use UPDATE-then-INSERT or ``INSERT ... SELECT ... WHERE NOT EXISTS``;
- a new user has no writable schema in a new database: everything lives in ``SHORTTRIP_DB_SCHEMA``;
- CHAR(n) pads with spaces, so identifiers are VARCHAR.
"""
from contextlib import contextmanager
from pathlib import Path
import re

import psycopg2
import psycopg2.errors
import psycopg2.extras
import psycopg2.pool

SCHEMA_FILE = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 3
UniqueViolation = psycopg2.errors.UniqueViolation


class Database:
    def __init__(self, settings, *, max_connections=12):
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", settings.db_schema):
            raise ValueError("SHORTTRIP_DB_SCHEMA 只能包含小写字母、数字和下划线。")
        self.schema = settings.db_schema
        self.pool = psycopg2.pool.ThreadedConnectionPool(
            1, max_connections,
            host=settings.db_host, port=settings.db_port, dbname=settings.db_name,
            user=settings.db_user, password=settings.db_password,
            client_encoding="UTF8", connect_timeout=8, application_name="shorttrip",
            options=f"-c search_path={self.schema}",
        )

    @contextmanager
    def tx(self):
        """Yield a cursor inside one transaction; commit on success, roll back on error."""
        conn = self.pool.getconn()
        if conn.closed:
            self.pool.putconn(conn, close=True)
            conn = self.pool.getconn()
        broken = False
        try:
            with conn.cursor() as cur:
                yield cur
            conn.commit()
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            broken = True
            raise
        except BaseException:
            if not conn.closed:
                conn.rollback()
            raise
        finally:
            self.pool.putconn(conn, close=broken or bool(conn.closed))

    def one(self, sql, params=()):
        with self.tx() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def all(self, sql, params=()):
        with self.tx() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def run(self, sql, params=()):
        with self.tx() as cur:
            cur.execute(sql, params)
            return cur.rowcount

    def close(self):
        self.pool.closeall()

    # ------------------------------------------------------------------ schema
    def ensure_schema(self):
        with self.tx() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")
            cur.execute("CREATE TABLE IF NOT EXISTS st_meta (key VARCHAR(64) PRIMARY KEY, value TEXT NOT NULL)")
            cur.execute("SELECT value FROM st_meta WHERE key = 'schema_version'")
            row = cur.fetchone()
            if row and int(row[0]) >= SCHEMA_VERSION:
                return False
            for statement in split_sql(SCHEMA_FILE.read_text(encoding="utf-8")):
                cur.execute(statement)
            put_meta(cur, "schema_version", str(SCHEMA_VERSION))
        return True


def put_meta(cur, key, value):
    cur.execute("UPDATE st_meta SET value = %s WHERE key = %s", (value, key))
    if cur.rowcount == 0:
        cur.execute("INSERT INTO st_meta (key, value) VALUES (%s, %s)", (key, value))


def split_sql(text):
    statements, buffer = [], []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(buffer).rstrip().rstrip(";"))
            buffer = []
    if buffer:
        statements.append("\n".join(buffer))
    return statements


def execute_batch(cur, sql, rows, page_size=500):
    psycopg2.extras.execute_batch(cur, sql, rows, page_size=page_size)
