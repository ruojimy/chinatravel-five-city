"""Content-addressed file storage in BYTEA chunks (st_blob / st_blob_chunk)."""
import hashlib
import os
from pathlib import Path
from uuid import uuid4

import psycopg2
import psycopg2.errors

CHUNK = 4 * 1024 * 1024


def sha256_file(path):
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def has_blob(cur, sha):
    cur.execute("SELECT 1 FROM st_blob WHERE sha256 = %s", (sha,))
    return cur.fetchone() is not None


def put_file(db, path, sha=None, size=None):
    """Store a file once. Returns the number of bytes newly written (0 when already stored)."""
    if sha is None or size is None:
        sha, size = sha256_file(path)
    try:
        return _put_file(db, path, sha, size)
    except psycopg2.errors.UniqueViolation:
        return 0  # another thread stored the same content first


def _put_file(db, path, sha, size):
    with db.tx() as cur:
        if has_blob(cur, sha):
            return 0
        count = max(1, -(-size // CHUNK))
        cur.execute("INSERT INTO st_blob (sha256, size, chunk_count) VALUES (%s,%s,%s)", (sha, size, count))
        check = hashlib.sha256()
        with open(path, "rb") as file:
            for seq in range(count):
                data = file.read(CHUNK)
                check.update(data)
                cur.execute("INSERT INTO st_blob_chunk (sha256, seq, data) VALUES (%s,%s,%s)",
                            (sha, seq, psycopg2.Binary(data)))
        if check.hexdigest() != sha:
            raise IOError(f"文件在上传过程中被修改：{path}")
    return size


def temporary_path(destination, temp_dir=None):
    """A short sibling-volume temp path. Windows without LongPathsEnabled stops at 259 characters
    and the deepest snapshot files are already ~255, so temp names must not lengthen the path."""
    folder = Path(temp_dir) if temp_dir else Path(destination).parent
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{uuid4().hex[:12]}.part"


def write_blob(db, sha, destination, temp_dir=None):
    """Write a stored blob to ``destination`` atomically after checking its SHA-256."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    row = db.one("SELECT chunk_count FROM st_blob WHERE sha256 = %s", (sha,))
    if row is None:
        raise FileNotFoundError(f"数据库中没有内容 {sha}")
    temporary = temporary_path(destination, temp_dir)
    digest = hashlib.sha256()
    try:
        with open(temporary, "wb") as output:
            for seq in range(row[0]):
                data = bytes(db.one("SELECT data FROM st_blob_chunk WHERE sha256 = %s AND seq = %s", (sha, seq))[0])
                digest.update(data)
                output.write(data)
        if digest.hexdigest() != sha:
            raise IOError(f"数据库内容校验失败：{destination.name}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
