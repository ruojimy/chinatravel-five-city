"""Import travel-data snapshots into the database and restore them as a verified local cache.

A snapshot is one folder under ``ShortTrip/artifacts/data/<id>``. Files are stored by SHA-256,
so a new data version only uploads the files that changed. When ``X`` and ``X.gz`` are both
present (the 185 MB catalog.sqlite3), only the .gz is stored and ``X`` is rebuilt on restore.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing
from uuid import uuid4

from .blobstore import put_file, sha256_file, temporary_path, write_blob
from .db import execute_batch

SKIP_DIRS = {"__pycache__", ".git"}
STAMP = ".shorttrip-materialized.json"


def _gunzip_sha(path):
    digest, size = hashlib.sha256(), 0
    with gzip.open(path, "rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def build_manifest(root):
    root = Path(root)
    files = sorted(p for p in root.rglob("*")
                   if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(root).parts)
                   and p.suffix != ".pyc" and p.name != STAMP)
    names = {p.relative_to(root).as_posix() for p in files}
    entries = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        sha, size = sha256_file(path)
        derived = None
        if relative + ".gz" in names:
            packed_sha, packed_size = _gunzip_sha(root / (relative + ".gz"))
            if (packed_sha, packed_size) == (sha, size):
                derived = "gunzip:" + relative + ".gz"
        entries.append({"path": relative, "sha256": sha, "size": size, "derived_from": derived})
    return entries


def manifest_sha(entries):
    text = "\n".join(f"{e['path']}\t{e['sha256']}\t{e['size']}" for e in entries)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def import_snapshot(db, root, snapshot_id=None, depends_on=None, note=None, catalog=True, log=print):
    root = Path(root).resolve()
    snapshot_id = snapshot_id or root.name
    info = {}
    if (root / "install.json").is_file():
        info = json.loads((root / "install.json").read_text(encoding="utf-8"))
    source = info.get("source", info)
    log(f"[{snapshot_id}] 计算文件清单…")
    entries = build_manifest(root)
    digest = manifest_sha(entries)
    existing = db.one("SELECT manifest_sha256 FROM st_snapshot WHERE id = %s", (snapshot_id,))
    if existing:
        if existing[0] == digest:
            log(f"[{snapshot_id}] 已在数据库中，内容一致，跳过。")
            return {"id": snapshot_id, "skipped": True}
        raise SystemExit(f"[{snapshot_id}] 数据库里已有同名快照但内容不同。数据快照不可覆盖，请用新的快照编号导入。")
    if depends_on and not db.one("SELECT 1 FROM st_snapshot WHERE id = %s", (depends_on,)):
        raise SystemExit(f"[{snapshot_id}] 依赖的快照 {depends_on} 还没有导入。")

    stored = 0
    uploads = [e for e in entries if not e["derived_from"]]
    for index, entry in enumerate(uploads, 1):
        stored += put_file(db, root / entry["path"], entry["sha256"], entry["size"])
        if index % 200 == 0 or index == len(uploads):
            log(f"[{snapshot_id}] 已处理 {index}/{len(uploads)} 个文件，新写入 {stored / 1048576:.1f} MB")
    total = sum(e["size"] for e in entries)
    with db.tx() as cur:
        cur.execute("INSERT INTO st_snapshot (id, commit_sha, profile, depends_on, manifest_sha256, file_count, "
                    "total_bytes, stored_bytes, note) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (snapshot_id, source.get("commit"), source.get("profile"), depends_on, digest,
                     len(entries), total, stored, note))
        execute_batch(cur, "INSERT INTO st_snapshot_file (snapshot_id, path, sha256, size, derived_from) "
                           "VALUES (%s,%s,%s,%s,%s)",
                      [(snapshot_id, e["path"], e["sha256"], e["size"], e["derived_from"]) for e in entries])
    log(f"[{snapshot_id}] 入库完成：{len(entries)} 个文件，原始 {total / 1048576:.1f} MB，本次新写入 {stored / 1048576:.1f} MB。")
    if catalog:
        for entry in entries:
            if entry["path"].endswith("catalog.sqlite3"):
                import_catalog(db, snapshot_id, root / entry["path"], log)
    return {"id": snapshot_id, "files": len(entries), "bytes": total, "stored": stored}


def import_catalog(db, snapshot_id, path, log=print):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as source:
        tables = {name for (name,) in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "records" not in tables:
            return
        count = 0
        rows = source.execute("SELECT id, lang, kind, city, name, payload FROM records ORDER BY id")
        while True:
            batch = rows.fetchmany(1000)
            if not batch:
                break
            with db.tx() as cur:
                execute_batch(cur, "INSERT INTO st_catalog_record (snapshot_id, id, lang, kind, city, name, payload) "
                                   "VALUES (%s,%s,%s,%s,%s,%s,%s)", [(snapshot_id, *row) for row in batch])
            count += len(batch)
        log(f"[{snapshot_id}] 地点目录 records 入库 {count} 行")
        if "tags" in tables:
            count = 0
            rows = source.execute("SELECT id, tag, value FROM tags")
            while True:
                batch = rows.fetchmany(5000)
                if not batch:
                    break
                with db.tx() as cur:
                    execute_batch(cur, "INSERT INTO st_catalog_tag (snapshot_id, record_id, tag, value) "
                                       "VALUES (%s,%s,%s,%s)", [(snapshot_id, *row) for row in batch], page_size=1000)
                count += len(batch)
            log(f"[{snapshot_id}] 地点目录 tags 入库 {count} 行")


def _ready(path, entry):
    return path.is_file() and path.stat().st_size == entry["size"] and sha256_file(path)[0] == entry["sha256"]


def materialize(db, snapshot_id, target_root, log=print, _seen=None):
    """Restore a snapshot (and what it depends on) to ``target_root/<id>``; verified by SHA-256."""
    _seen = _seen or set()
    if snapshot_id in _seen:
        return
    _seen.add(snapshot_id)
    row = db.one("SELECT depends_on, manifest_sha256 FROM st_snapshot WHERE id = %s", (snapshot_id,))
    if row is None:
        raise SystemExit(f"数据库中没有快照 {snapshot_id}，请先运行 import-snapshot。")
    depends_on, digest = row
    if depends_on:
        materialize(db, depends_on, target_root, log, _seen)
    destination = Path(target_root) / snapshot_id
    stamp = destination / STAMP
    entries = [dict(zip(("path", "sha256", "size", "derived_from"), r)) for r in db.all(
        "SELECT path, sha256, size, derived_from FROM st_snapshot_file WHERE snapshot_id = %s ORDER BY path",
        (snapshot_id,))]
    if stamp.is_file() and json.loads(stamp.read_text(encoding="utf-8")).get("manifest") == digest and all(
            (destination / e["path"]).is_file() and (destination / e["path"]).stat().st_size == e["size"]
            for e in entries):
        log(f"[{snapshot_id}] 本地缓存已是最新。")
        return
    log(f"[{snapshot_id}] 从数据库还原 {len(entries)} 个文件到 {destination} …")
    written = 0
    incoming = Path(target_root) / ".incoming"
    for entry in sorted(entries, key=lambda e: bool(e["derived_from"])):
        path = destination / entry["path"]
        if _ready(path, entry):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if entry["derived_from"]:
            source = destination / entry["derived_from"].split(":", 1)[1]
            temporary = temporary_path(path, incoming)
            try:
                with gzip.open(source, "rb") as packed, open(temporary, "wb") as output:
                    for block in iter(lambda: packed.read(1024 * 1024), b""):
                        output.write(block)
                if sha256_file(temporary)[0] != entry["sha256"]:
                    raise IOError(f"解压后的校验值不一致：{entry['path']}")
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        else:
            write_blob(db, entry["sha256"], path, incoming)
        written += 1
    stamp.write_text(json.dumps({"snapshot": snapshot_id, "manifest": digest}), encoding="utf-8")
    log(f"[{snapshot_id}] 还原完成，写入 {written} 个文件。")
