import sqlite3
import time
import uuid

from core.job_manager import JobManager
from tests.util import wait_idle


def _noop(payload, ctx):
    return {"ok": True}


def _slow(payload, ctx):
    for _ in range(400):
        ctx.checkpoint()
        time.sleep(0.05)
    return {}


def test_cancel(client):
    jm = client.app.state.jobs
    jm.register("test_slow", _slow)
    jid = jm.create("test_slow", {})
    time.sleep(0.5)
    assert client.post(f"/api/jobs/{jid}/cancel").status_code == 200
    wait_idle(client)
    assert client.get(f"/api/jobs/{jid}").json()["status"] == "cancelled"


def test_pause_resume(client):
    jm = client.app.state.jobs
    jm.register("test_noop", _noop)
    client.post("/api/jobs/pause")
    jid = jm.create("test_noop", {})
    time.sleep(1.0)
    assert client.get(f"/api/jobs/{jid}").json()["status"] == "pending"
    client.post("/api/jobs/resume")
    wait_idle(client)
    assert client.get(f"/api/jobs/{jid}").json()["status"] == "completed"


def test_crash_recovery(client):
    jm = client.app.state.jobs
    jm.register("test_noop", _noop)
    conn = client.app.state.db.conn()
    jid = uuid.uuid4().hex
    conn.execute("INSERT INTO jobs (id, kind, status, claimed_by) VALUES (?,?, 'running','dead')",
                 (jid, "test_noop"))
    jm.recover_stale()
    wait_idle(client)
    assert client.get(f"/api/jobs/{jid}").json()["status"] == "completed"


def test_unknown_kind_fails_not_hangs(client):
    jid = client.app.state.jobs.create("no_such_kind", {})
    wait_idle(client)
    j = client.get(f"/api/jobs/{jid}").json()
    assert j["status"] == "failed" and "no handler" in j["error"]


def test_worker_recovers_after_transient_claim_error(client, monkeypatch):
    # Stop fixture workers so this test controls exactly one worker thread.
    client.app.state.jobs.stop()
    jm = JobManager(client.app.state.db, workers=1)
    jm.register("test_retry_noop", _noop)

    import core.job_manager as job_manager_module
    real_claim_job = job_manager_module.repo.claim_job
    calls = 0

    def fail_once(conn, worker):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise sqlite3.OperationalError("database is locked")
        return real_claim_job(conn, worker)

    monkeypatch.setattr(job_manager_module.repo, "claim_job", fail_once)
    jm.start()
    try:
        jid = jm.create("test_retry_noop", {})
        wait_idle(client)
        job = jm.get(jid)
        assert job["status"] == "completed"
        assert calls >= 2
    finally:
        jm.stop()
