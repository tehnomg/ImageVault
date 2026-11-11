import json, os, shutil, sys
import pytest
import core.scanner as scanner_mod
from database.db import Database, MIGRATIONS_DIR
from tests.util import register_and_scan, find_image, rescan

def test_migrations_fresh(tmp_path):
    db = Database(tmp_path / "x.db")
    db.init()
    assert db.conn().execute("PRAGMA user_version").fetchone()[0] == 2

def test_migrations_upgrade_from_v1(tmp_path):
    db = Database(tmp_path / "x.db")
    c = db.conn()
    c.executescript((MIGRATIONS_DIR / "0001_initial.sql").read_text(encoding="utf-8"))
    c.execute("PRAGMA user_version=1")
    db.migrate()
    assert c.execute("PRAGMA user_version").fetchone()[0] == 2
    assert c.execute("SELECT name FROM sqlite_master WHERE name='auth_sessions'").fetchone()
    cols = [r["name"] for r in c.execute("PRAGMA table_info(volumes)")]
    assert "identity_warning" in cols

def test_incomplete_walk_no_missing(client, sample, monkeypatch):
    sub = sample / "sub"
    sub.mkdir()
    shutil.copyfile(sample / "solid.png", sub / "x.png")
    vid, _ = register_and_scan(client, sample)
    real = os.scandir
    def fake(p):
        if os.path.normcase(str(p)) == os.path.normcase(str(sub)):
            raise PermissionError("denied")
        return real(p)
    monkeypatch.setattr(scanner_mod.os, "scandir", fake)
    jid = rescan(client, vid)
    job = client.get(f"/api/jobs/{jid}").json()
    assert json.loads(job["result_json"])["missing_check"] == "skipped_incomplete_walk"
    assert find_image(client, "x.png")["scan_status"] == "ok"

def test_excluded_dir_not_missing(client, sample):
    sub = sample / "sub"
    sub.mkdir()
    shutil.copyfile(sample / "solid.png", sub / "x.png")
    vid, _ = register_and_scan(client, sample)
    (sample / "sub").rename(sample / ".sub")
    rescan(client, vid)
    assert find_image(client, "x.png")["scan_status"] == "ok"

def test_symlink_follow_no_loop(client, sample):
    try:
        os.symlink(sample, sample / "loop", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation requires privileges on this system")
    client.app.state.cfg.follow_symlinks = True
    register_and_scan(client, sample)
    assert client.get("/api/images", params={"page_size": 200}).json()["total"] == 12

def test_symlink_skip_default_no_missing(client, sample):
    vid, _ = register_and_scan(client, sample)
    try:
        os.symlink(sample, sample / "loop", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation requires privileges on this system")
    rescan(client, vid)
    data = client.get("/api/images", params={"page_size": 200}).json()
    assert data["total"] == 12
    assert all(i["scan_status"] != "missing" for i in data["items"])

@pytest.mark.skipif(os.name != "nt", reason="Windows case-insensitivity")
def test_windows_case_insensitive_roots(client, sample):
    (sample / "Photos").mkdir()
    shutil.copyfile(sample / "solid.png", sample / "Photos" / "p.png")
    vid = client.post("/api/volumes", json={"path": str(sample)}).json()["id"]
    r1 = client.post(f"/api/volumes/{vid}/roots", json={"relative_path": "photos"})
    r2 = client.post(f"/api/volumes/{vid}/roots", json={"relative_path": "PHOTOS"})
    assert r1.status_code == 200 and r1.json()["id"] == r2.json()["id"]
    client.post(f"/api/roots/{r1.json()['id']}/scan")
    from tests.util import wait_idle
    wait_idle(client)
    assert find_image(client, "p.png")["scan_status"] == "ok"