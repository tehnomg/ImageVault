from __future__ import annotations
import json, logging, os, threading
from database import repository as repo

log = logging.getLogger("imagevault.jobs")

class JobCancelled(Exception):
    pass

class JobContext:
    def __init__(self, db, job_id: str):
        self.db, self.job_id = db, job_id

    def checkpoint(self):
        conn = self.db.conn()
        if repo.job_cancel_requested(conn, self.job_id):
            raise JobCancelled()
        repo.job_heartbeat(conn, self.job_id)

    def progress(self, value: float | None, msg: str | None = None):
        conn = self.db.conn()
        repo.job_progress(conn, self.job_id, value, msg)
        if repo.job_cancel_requested(conn, self.job_id):
            raise JobCancelled()

class JobManager:
    """Персистентная очередь в SQLite. Захват — атомарный UPDATE...RETURNING."""
    def __init__(self, db, workers: int = 2):
        self.db = db
        self.workers = max(1, workers)
        self._handlers: dict = {}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def register(self, kind: str, fn):
        self._handlers[kind] = fn

    def start(self):
        self.recover_stale()
        for i in range(self.workers):
            t = threading.Thread(target=self._loop, args=(f"pid{os.getpid()}-t{i}",),
                                 name=f"iv-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self):
        self._stop.set()
        for t in self._threads:
            t.join(timeout=5)

    def recover_stale(self):
        self.db.conn().execute(
            "UPDATE jobs SET status='pending', claimed_by=NULL, started_at=NULL "
            "WHERE status='running'")

    def create(self, kind, payload, priority=0) -> str:
        return repo.create_job(self.db.conn(), kind, payload, priority)

    def get(self, jid): return repo.get_job(self.db.conn(), jid)
    def list(self, status=None, limit=100): return repo.list_jobs(self.db.conn(), status, limit)

    def request_cancel(self, jid):
        with self.db.tx() as conn:
            job = repo.get_job(conn, jid)
            if not job:
                return False
            conn.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (jid,))
            if job["status"] == "pending":
                repo.finish_job(conn, jid, "cancelled")
        return True

    def pause(self): repo.set_setting(self.db.conn(), "queue_paused", True)
    def resume(self): repo.set_setting(self.db.conn(), "queue_paused", False)
    def is_paused(self) -> bool: return bool(repo.get_setting(self.db.conn(), "queue_paused", False))

    def _loop(self, worker: str):
        conn = self.db.conn()
        while not self._stop.is_set():
            if self.is_paused():
                self._stop.wait(0.5)
                continue
            job = repo.claim_job(conn, worker)
            if job is None:
                self._stop.wait(0.4)
                continue
            jid, kind = job["id"], job["kind"]
            ctx = JobContext(self.db, jid)
            handler = self._handlers.get(kind)
            try:
                if handler is None:
                    raise RuntimeError(f"no handler registered for job kind '{kind}'")
                result = handler(json.loads(job["payload_json"]), ctx)
                repo.finish_job(conn, jid, "completed", result=result)
            except JobCancelled:
                repo.finish_job(conn, jid, "cancelled")
                log.info("job %s (%s) cancelled", jid, kind)
            except Exception as e:
                log.exception("job %s (%s) failed", jid, kind)
                repo.finish_job(conn, jid, "failed", error=f"{type(e).__name__}: {e}")