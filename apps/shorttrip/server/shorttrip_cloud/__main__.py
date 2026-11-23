"""ShortTrip cloud command line.

    python -m shorttrip_cloud init-db
    python -m shorttrip_cloud import-snapshot <data>/5e0ee8a
    python -m shorttrip_cloud import-snapshot <data>/6de12f4 --depends-on 5e0ee8a
    python -m shorttrip_cloud materialize 6de12f4 --to <release>/ShortTrip/artifacts/data
    python -m shorttrip_cloud create-user alice --admin          (password read from SHORTTRIP_NEW_PASSWORD or prompt)
    python -m shorttrip_cloud register-release P042 --snapshots 5e0ee8a,6de12f4 [--apk app.apk]
    python -m shorttrip_cloud status
    python -m shorttrip_cloud serve --release <release>/ShortTrip [--host 0.0.0.0 --port 8790]
"""
import argparse
import getpass
import os
from pathlib import Path
import sys

from . import config
from .db import Database


def connect():
    settings = config.load()
    db = Database(settings)
    db.ensure_schema()
    return settings, db


def main(argv=None):
    parser = argparse.ArgumentParser(prog="shorttrip_cloud", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db", help="create or upgrade the tables")
    imp = commands.add_parser("import-snapshot", help="store a data snapshot folder in the database")
    imp.add_argument("folder", type=Path)
    imp.add_argument("--id")
    imp.add_argument("--depends-on")
    imp.add_argument("--note")
    imp.add_argument("--no-catalog", action="store_true", help="skip the queryable catalog tables")
    mat = commands.add_parser("materialize", help="restore a snapshot from the database")
    mat.add_argument("snapshot")
    mat.add_argument("--to", type=Path, required=True)
    user = commands.add_parser("create-user")
    user.add_argument("username")
    user.add_argument("--display-name")
    user.add_argument("--admin", action="store_true")
    rel = commands.add_parser("register-release", help="record a PC/Android release")
    rel.add_argument("version")
    rel.add_argument("--snapshots", required=True)
    rel.add_argument("--apk", type=Path)
    rel.add_argument("--version-code", type=int)
    rel.add_argument("--server-url")
    rel.add_argument("--notes")
    commands.add_parser("status", help="show database contents")
    serve = commands.add_parser("serve", help="run the shared PC/Android server")
    serve.add_argument("--release", type=Path, default=Path(__file__).resolve().parents[1])
    serve.add_argument("--host", default=os.environ.get("SHORTTRIP_HOST", "0.0.0.0"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("SHORTTRIP_PORT", "8790")))
    serve.add_argument("--planner-port", type=int, default=int(os.environ.get("SHORTTRIP_PLANNER_PORT", "8781")))
    args = parser.parse_args(argv)

    settings, db = connect()
    try:
        if args.command == "init-db":
            print("数据库表已就绪（schema %s）。" % settings.db_schema)
        elif args.command == "import-snapshot":
            from .snapshots import import_snapshot
            import_snapshot(db, args.folder, args.id, args.depends_on, args.note, catalog=not args.no_catalog)
        elif args.command == "materialize":
            from .snapshots import materialize
            materialize(db, args.snapshot, args.to)
        elif args.command == "create-user":
            from .auth import Accounts, AuthError
            password = os.environ.get("SHORTTRIP_NEW_PASSWORD") or getpass.getpass("新账号密码：")
            try:
                created = Accounts(db, settings).create_user(args.username, password, args.display_name,
                                                             "admin" if args.admin else "user")
            except AuthError as error:
                raise SystemExit(error.message)
            print(f"已创建账号 {created.username}（{created.role}）")
        elif args.command == "register-release":
            register_release(db, args)
        elif args.command == "status":
            status(db)
        elif args.command == "serve":
            from .gateway import Gateway
            Gateway(args.release, settings, db, host=args.host, port=args.port,
                    planner_port=args.planner_port).serve()
    finally:
        db.close()


def register_release(db, args):
    from .blobstore import sha256_file
    apk_sha = apk_size = None
    if args.apk:
        apk_sha, apk_size = sha256_file(args.apk)
    for snapshot in args.snapshots.split(","):
        if not db.one("SELECT 1 FROM st_snapshot WHERE id = %s", (snapshot,)):
            raise SystemExit(f"快照 {snapshot} 尚未入库。")
    with db.tx() as cur:
        if args.apk is None:
            cur.execute("UPDATE st_release SET snapshot_ids = %s, notes = %s WHERE version = %s",
                        (args.snapshots, args.notes, args.version))
            if cur.rowcount:
                print(f"已登记发布 {args.version}")
                return
        cur.execute("DELETE FROM st_release WHERE version = %s", (args.version,))
        cur.execute("INSERT INTO st_release (version, snapshot_ids, android_version_code, apk_sha256, apk_size, "
                    "server_url, notes) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (args.version, args.snapshots, args.version_code, apk_sha, apk_size, args.server_url, args.notes))
    print(f"已登记发布 {args.version}")


def status(db):
    def show(title, sql):
        rows = db.all(sql)
        print(f"\n== {title}")
        for row in rows:
            print("  " + " | ".join("" if v is None else str(v) for v in row))
        if not rows:
            print("  （无）")

    show("数据快照", "SELECT id, commit_sha, depends_on, file_count, round(total_bytes/1048576.0,1) || ' MB', "
                 "round(stored_bytes/1048576.0,1) || ' MB 新写入', imported_at FROM st_snapshot ORDER BY imported_at")
    show("存储占用", "SELECT count(*) || ' 个内容块', round(sum(size)/1048576.0,1) || ' MB' FROM st_blob")
    show("地点目录", "SELECT snapshot_id, count(*) FROM st_catalog_record GROUP BY snapshot_id")
    show("发布版本", "SELECT version, snapshot_ids, android_version_code, apk_size, server_url, created_at "
                 "FROM st_release ORDER BY created_at")
    show("账号", "SELECT username, role, created_at, last_login_at, "
               "(SELECT count(*) FROM st_trip_job j WHERE j.user_id = u.id) || ' 个规划' FROM st_user u ORDER BY id")
    show("规划任务", "SELECT coalesce(u.username, '(示例)'), j.title, j.state, j.client, j.created_at FROM st_trip_job j "
                 "LEFT JOIN st_user u ON u.id = j.user_id ORDER BY j.created_at DESC LIMIT 20")


if __name__ == "__main__":
    sys.exit(main())
