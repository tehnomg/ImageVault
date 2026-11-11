import time

def wait_idle(client, timeout=90):
    db = client.app.state.db
    t0 = time.time()
    while time.time() - t0 < timeout:
        n = db.conn().execute(
            "SELECT COUNT(*) n FROM jobs WHERE status IN ('pending','running')").fetchone()["n"]
        if n == 0:
            return
        time.sleep(0.1)
    raise AssertionError("jobs did not finish in time")

def register_and_scan(client, path):
    r = client.post("/api/volumes", json={"path": str(path), "create_marker": False})
    assert r.status_code == 200, r.text
    vid = r.json()["id"]
    r = client.post(f"/api/volumes/{vid}/roots", json={"relative_path": ""})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    r = client.post(f"/api/roots/{rid}/scan")
    assert r.status_code == 200, r.text
    wait_idle(client)
    return vid, rid

def rescan(client, vid):
    rid = client.get(f"/api/volumes/{vid}/roots").json()["items"][0]["id"]
    r = client.post(f"/api/roots/{rid}/scan")
    assert r.status_code == 200, r.text
    wait_idle(client)
    return r.json()["job_id"]

def find_image(client, filename):
    items = client.get("/api/images", params={"q": filename, "page_size": 200}).json()["items"]
    return next(i for i in items if i["filename"] == filename)