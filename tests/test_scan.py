import os, uuid
from PIL import Image
from tests.util import register_and_scan, find_image, rescan, wait_idle

def test_scan_counts(client, sample):
    register_and_scan(client, sample)
    data = client.get("/api/images", params={"page_size": 200}).json()
    assert data["total"] == 12
    st = {}
    for it in data["items"]:
        st[it["scan_status"]] = st.get(it["scan_status"], 0) + 1
    assert st.get("ok") == 11 and st.get("corrupt") == 1

def test_incremental_no_rework(client, sample):
    vid, _ = register_and_scan(client, sample)
    db = client.app.state.db
    jobs_before = db.conn().execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"]
    img = find_image(client, "solid.png")
    thumb = client.app.state.cfg.thumbs_dir / img["id"][:2] / (img["id"] + ".webp")
    mtime = thumb.stat().st_mtime_ns
    rescan(client, vid)
    jobs_after = db.conn().execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"]
    assert jobs_after == jobs_before + 1
    assert thumb.stat().st_mtime_ns == mtime

def test_change_invalidates(client, sample):
    vid, _ = register_and_scan(client, sample)
    db = client.app.state.db
    img = find_image(client, "gradient.png")
    db.conn().execute(
        "INSERT INTO analyses (id, image_id, profile, status, result_json) VALUES (?,?,?,?,?)",
        (uuid.uuid4().hex, img["id"], "description", "completed", "{}"))
    p = sample / "gradient.png"
    Image.new("RGB", (300, 200), (1, 2, 3)).save(p)
    st = p.stat(); os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    rescan(client, vid)
    assert db.conn().execute("SELECT stale FROM analyses WHERE image_id=?",
                             (img["id"],)).fetchone()["stale"] == 1
    meta = client.get(f"/api/images/{img['id']}").json()
    assert (meta["width"], meta["height"]) == (300, 200)

def test_missing(client, sample):
    vid, _ = register_and_scan(client, sample)
    img = find_image(client, "gradient_q40.jpg")
    (sample / "gradient_q40.jpg").unlink()
    rescan(client, vid)
    assert client.get(f"/api/images/{img['id']}").json()["scan_status"] == "missing"
    assert client.get(f"/api/images/{img['id']}/original").status_code == 404

def test_offline_not_deletable(client, sample):
    vid, _ = register_and_scan(client, sample)
    img = find_image(client, "solid.png")
    client.app.state.db.conn().execute("UPDATE volumes SET status='offline' WHERE id=?", (vid,))
    assert client.get(f"/api/images/{img['id']}/original").status_code == 409
    assert client.get("/api/images").json()["total"] == 12