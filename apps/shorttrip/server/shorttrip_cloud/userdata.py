"""Which account owns which trip request / planning job / itinerary edit, and their files.

The planner keeps writing its usual folders under ``result/``. This module copies those
folders into st_object_file (content-addressed) and restores them when they are missing,
so ``result/`` on the server is only a cache and accounts work from the PC or the phone.

An object absent from the tables belongs to nobody and cannot be opened. ``user_id NULL``
marks bundled examples that every signed-in account may read.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import threading
import traceback

from .blobstore import put_file, sha256_file, write_blob

IDENTIFIER = re.compile(r"[a-f0-9]{32}")
TERMINAL = {"complete", "failed", "worker_failed", "needs_confirmation", "infeasible", "cancelled"}


def valid(identifier):
    return isinstance(identifier, str) and IDENTIFIER.fullmatch(identifier) is not None


class UserData:
    def __init__(self, db, planner_root):
        self.db = db
        self.result = Path(planner_root) / "result"
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="shorttrip-sync")
        self.pending = set()
        self.lock = threading.Lock()
        self.restore_lock = threading.Lock()

    # ------------------------------------------------------------ folders
    def files(self, scope, oid):
        if scope == "inputs":
            folder = self.result / "inputs"
            return folder, [p for p in (folder / f"{oid}.json", folder / f"{oid}.hotel.json") if p.is_file()]
        folder = self.result / {"tripspec": "tripspec", "manual": "manual", "edits": "workbench_edits"}[scope] / oid
        if not folder.is_dir():
            return folder, []
        return folder, sorted(p for p in folder.rglob("*")
                              if p.is_file() and not p.name.endswith((".tmp", ".part")) and "__pycache__" not in p.parts)

    def sync(self, scope, oid):
        """Upload new or changed files of one object. Returns the number of files written."""
        base, files = self.files(scope, oid)
        known = dict(self.db.all("SELECT path, sha256 FROM st_object_file WHERE scope = %s AND object_id = %s",
                                 (scope, oid)))
        changed = 0
        for path in files:
            relative = path.relative_to(base).as_posix()
            try:
                sha, size = sha256_file(path)
            except OSError:
                continue  # a worker is replacing the file; the next sync picks it up
            if known.get(relative) == sha:
                continue
            put_file(self.db, path, sha, size)
            with self.db.tx() as cur:
                cur.execute("UPDATE st_object_file SET sha256 = %s, size = %s, updated_at = now() "
                            "WHERE scope = %s AND object_id = %s AND path = %s", (sha, size, scope, oid, relative))
                if cur.rowcount == 0:
                    cur.execute("INSERT INTO st_object_file (scope, object_id, path, sha256, size) "
                                "VALUES (%s,%s,%s,%s,%s)", (scope, oid, relative, sha, size))
            changed += 1
        return changed

    def sync_later(self, *objects):
        for scope, oid in objects:
            key = (scope, oid)
            with self.lock:
                if key in self.pending:
                    continue
                self.pending.add(key)
            self.pool.submit(self._sync_job, key)

    def _sync_job(self, key):
        try:
            with self.lock:
                self.pending.discard(key)
            self.sync(*key)
        except Exception:  # noqa: BLE001 - the next request retries; never break the HTTP thread
            traceback.print_exc()

    def restore(self, scope, oid):
        """Rebuild a missing local folder from the database."""
        base, present = self.files(scope, oid)
        rows = self.db.all("SELECT path, sha256, size FROM st_object_file WHERE scope = %s AND object_id = %s",
                           (scope, oid))
        if not rows or (present and scope != "inputs"):
            return 0
        written = 0
        with self.restore_lock:
            root = base.resolve()
            for relative, sha, size in rows:
                target = (base / relative).resolve()
                if not target.is_relative_to(root):
                    continue
                if not target.is_file():
                    write_blob(self.db, sha, target)
                    written += 1
        return written

    # ------------------------------------------------------------ ownership
    def _owner(self, table, column, oid):
        return self.db.one(f"SELECT user_id FROM {table} WHERE {column} = %s", (oid,))

    def can_read_request(self, user, rid):
        row = valid(rid) and self._owner("st_trip_request", "request_id", rid)
        return bool(row) and row[0] in (None, user.id)

    def can_write_request(self, user, rid):
        row = valid(rid) and self._owner("st_trip_request", "request_id", rid)
        return bool(row) and row[0] == user.id

    def can_read_job(self, user, jid):
        row = valid(jid) and self._owner("st_trip_job", "job_id", jid)
        return bool(row) and row[0] in (None, user.id)

    def can_write_job(self, user, jid):
        row = valid(jid) and self._owner("st_trip_job", "job_id", jid)
        return bool(row) and row[0] == user.id

    def owns_edit(self, user, eid):
        row = valid(eid) and self._owner("st_itinerary_edit", "edit_id", eid)
        return bool(row) and row[0] == user.id

    def edits_of(self, user, jid):
        return {r[0] for r in self.db.all("SELECT edit_id FROM st_itinerary_edit WHERE user_id = %s AND job_id = %s",
                                          (user.id, jid))}

    # ------------------------------------------------------------ local cache
    def ensure_request(self, rid):
        self.restore("tripspec", rid)

    def ensure_job(self, jid):
        self.restore("manual", jid)
        self.restore("inputs", jid)
        row = self.db.one("SELECT request_id FROM st_trip_job WHERE job_id = %s", (jid,))
        if row and row[0]:
            self.ensure_request(row[0])

    def ensure_edit(self, eid):
        self.restore("edits", eid)
        row = self.db.one("SELECT job_id FROM st_itinerary_edit WHERE edit_id = %s", (eid,))
        if row:
            self.ensure_job(row[0])

    # ------------------------------------------------------------ records
    @staticmethod
    def _form(spec):
        form = (spec or {}).get("form") or {}
        return (form.get("start_city"), form.get("target_city"), form.get("days"), form.get("people_number"),
                (spec or {}).get("raw_text"), (spec or {}).get("request_revision"))

    def save_request(self, user_id, spec):
        rid = spec.get("request_id")
        if not valid(rid):
            return
        start, target, days, people, raw, revision = self._form(spec)
        days = days if isinstance(days, int) else None
        people = people if isinstance(people, int) else None
        with self.db.tx() as cur:
            cur.execute("UPDATE st_trip_request SET revision = %s, start_city = %s, target_city = %s, days = %s, "
                        "people = %s, raw_text = %s, updated_at = now() WHERE request_id = %s",
                        (revision, start, target, days, people, raw, rid))
            if cur.rowcount == 0:
                cur.execute("INSERT INTO st_trip_request (request_id, user_id, revision, start_city, target_city, "
                            "days, people, raw_text) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (rid, user_id, revision, start, target, days, people, raw))
        self.sync_later(("tripspec", rid))

    def title(self, rid):
        row = self.db.one("SELECT start_city, target_city, days, people FROM st_trip_request WHERE request_id = %s",
                          (rid,))
        if not row:
            return "行程规划"
        start, target, days, people = row
        text = f"{start or '?'} → {target or '?'}"
        if days:
            text += f" · {days}天"
        if people:
            text += f"{people}人"
        return text

    def add_job(self, user_id, jid, rid, client, state="starting"):
        if not valid(jid):
            return
        with self.db.tx() as cur:
            cur.execute("SELECT 1 FROM st_trip_job WHERE job_id = %s", (jid,))
            if cur.fetchone() is None:
                cur.execute("INSERT INTO st_trip_job (job_id, user_id, request_id, state, title, client) "
                            "VALUES (%s,%s,%s,%s,%s,%s)", (jid, user_id, rid, state, self.title(rid), client))
        self.sync_later(("inputs", jid))

    def job_state(self, jid, state):
        """Record a polled state; mirror the job folder whenever the state changes."""
        if not valid(jid) or not isinstance(state, str):
            return
        row = self.db.one("SELECT synced_state FROM st_trip_job WHERE job_id = %s", (jid,))
        if row is None or row[0] == state:
            return
        self.db.run("UPDATE st_trip_job SET state = %s, synced_state = %s, updated_at = now() WHERE job_id = %s",
                    (state, state, jid))
        self.sync_later(("manual", jid), ("inputs", jid))

    def add_edit(self, user_id, eid, jid):
        if valid(eid):
            self.db.run("INSERT INTO st_itinerary_edit (edit_id, user_id, job_id, state) VALUES (%s,%s,%s,'starting')",
                        (eid, user_id, jid))
            self.sync_later(("edits", eid))

    def edit_state(self, eid, state, adopted=False):
        if not valid(eid) or not isinstance(state, str):
            return
        row = self.db.one("SELECT synced_state, adopted FROM st_itinerary_edit WHERE edit_id = %s", (eid,))
        if row is None or (row[0] == state and row[1] == adopted):
            return
        self.db.run("UPDATE st_itinerary_edit SET state = %s, synced_state = %s, adopted = %s, updated_at = now() "
                    "WHERE edit_id = %s", (state, state, adopted, eid))
        self.sync_later(("edits", eid))

    def add_feedback(self, user_id, record):
        self.db.run("INSERT INTO st_feedback (id, user_id, job_id, candidate_id, revision_id, decision, text) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (record["id"], user_id, record.get("job"), record.get("candidate"), record.get("revision"),
                     record.get("decision"), (record.get("text") or "")[:1000]))

    def trips(self, user):
        rows = self.db.all(
            "SELECT j.job_id, j.request_id, j.state, j.title, j.client, j.created_at, j.updated_at, j.user_id IS NULL, "
            "(SELECT count(*) FROM st_itinerary_edit e WHERE e.job_id = j.job_id AND e.user_id = %s AND e.adopted) "
            "FROM st_trip_job j WHERE j.user_id = %s OR j.user_id IS NULL ORDER BY j.user_id IS NULL, j.created_at DESC "
            "LIMIT 200", (user.id, user.id))
        rows = [list(r) for r in rows]
        for row in rows:
            # A job started on one device may finish while nobody polls it; read the planner's status.
            status_file = self.result / "manual" / row[0] / "STATUS.json"
            if row[2] not in TERMINAL and not row[7] and status_file.is_file():
                try:
                    state = json.loads(status_file.read_text(encoding="utf-8")).get("state")
                except (OSError, ValueError):
                    continue
                if state and state != row[2]:
                    self.job_state(row[0], state)
                    row[2] = state
        return [{"job": r[0], "request": r[1], "state": r[2], "title": r[3], "client": r[4],
                 "created": r[5].isoformat(), "updated": r[6].isoformat(), "example": r[7], "adopted_edits": r[8]}
                for r in rows]

    # ------------------------------------------------------------ bundled examples
    def register_examples(self, jobs=(), requests=()):
        """Expose the release's bundled demo trips (read-only) to every account."""
        for rid in requests:
            spec_file = self.result / "tripspec" / rid / "latest.json"
            if valid(rid) and spec_file.is_file() and not self._owner("st_trip_request", "request_id", rid):
                self.save_request(None, json.loads(spec_file.read_text(encoding="utf-8")))
        for jid in jobs:
            status_file = self.result / "manual" / jid / "STATUS.json"
            if valid(jid) and status_file.is_file() and not self._owner("st_trip_job", "job_id", jid):
                status = json.loads(status_file.read_text(encoding="utf-8"))
                request_file = self.result / "manual" / jid / "request.json"
                rid = json.loads(request_file.read_text(encoding="utf-8")).get("request_id") if request_file.is_file() else None
                # Published archives can include a job without its editable request.
                if not valid(rid) or self._owner("st_trip_request", "request_id", rid) != (None,):
                    rid = None
                self.add_job(None, jid, rid, "example", status.get("state", "complete"))
                self.job_state(jid, status.get("state", "complete"))
            elif valid(jid) and status_file.is_file() and self._owner("st_trip_job", "job_id", jid) == (None,):
                self.sync_later(("manual", jid), ("inputs", jid))
