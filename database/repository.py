from __future__ import annotations
import json, os, uuid
from .db import utcnow

def _row(r): return dict(r) if r is not None else None
def _rows(rs): return [dict(r) for r in rs]

NOCASE = " COLLATE NOCASE" if os.name == "nt" else ""

_IMAGE_COLS = {"file_size","mtime_ns","width","height","format","mode","exif_json",
               "orientation","created_at_fs","scanned_at","scan_status"}
_VOL_COLS = {"marker_uuid","volume_guid","fs_serial","label","fs_type","media_type",
             "anchor","status","last_seen_at","last_scan_at","identity_warning"}

def _update(conn, table, pk, id_, fields, allowed):
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields: return
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE {table} SET {sets} WHERE {pk}=?", (*fields.values(), id_))

def insert_volume(conn, vol: dict) -> str:
    vid = vol.get("id") or uuid.uuid4().hex
    cols = ["id"] + [k for k in _VOL_COLS if k in vol]
    conn.execute(f"INSERT INTO volumes ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",
                 [vid] + [vol[k] for k in cols[1:]])
    return vid

def update_volume(conn, vid, **f): _update(conn, "volumes", "id", vid, f, _VOL_COLS)
def get_volume(conn, vid): return _row(conn.execute("SELECT * FROM volumes WHERE id=?", (vid,)).fetchone())
def list_volumes(conn): return _rows(conn.execute("SELECT * FROM volumes ORDER BY label, anchor"))

def insert_root(conn, vid, rel) -> str:
    rid = uuid.uuid4().hex
    conn.execute("INSERT INTO roots (id, volume_id, relative_path) VALUES (?,?,?)", (rid, vid, rel))
    return rid

def get_root(conn, rid): return _row(conn.execute("SELECT * FROM roots WHERE id=?", (rid,)).fetchone())
def list_roots(conn, vid=None):
    if vid: return _rows(conn.execute("SELECT * FROM roots WHERE volume_id=?", (vid,)))
    return _rows(conn.execute("SELECT * FROM roots"))

def set_root_scanned(conn, rid):
    conn.execute("UPDATE roots SET last_scan_at=? WHERE id=?", (utcnow(), rid))

def insert_image(conn, row: dict) -> str:
    iid = row.get("id") or uuid.uuid4().hex
    cols = list(row.keys())
    if "id" not in cols: cols = ["id"] + cols
    vals = [iid] + [row[k] for k in cols if k != "id"]
    conn.execute(f"INSERT INTO images ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})", vals)
    return iid

def update_image(conn, iid, **f): _update(conn, "images", "id", iid, f, _IMAGE_COLS)

def get_image(conn, iid):
    return _row(conn.execute(
        "SELECT i.*, v.status AS volume_status, v.label AS volume_label, v.anchor AS volume_anchor "
        "FROM images i JOIN volumes v ON v.id=i.volume_id WHERE i.id=?", (iid,)).fetchone())

def get_image_by_path(conn, vid, rel):
    return _row(conn.execute(
        f"SELECT * FROM images WHERE volume_id=? AND relative_path=?{NOCASE}",
        (vid, rel)).fetchone())

def images_under_root(conn, vid):
    return _rows(conn.execute(
        "SELECT id, relative_path FROM images WHERE volume_id=? AND scan_status!='missing'", (vid,)))

_ORDERS = {"name": "filename COLLATE NOCASE", "mtime": "mtime_ns",
           "size": "file_size", "scanned": "scanned_at"}

def list_images(conn, volume_id=None, status=None, q=None, prefix=None,
                order="name", direction="asc", page=1, page_size=60):
    where, params = ["1=1"], []
    if volume_id: where.append("i.volume_id=?"); params.append(volume_id)
    if status: where.append("i.scan_status=?"); params.append(status)
    if q:
        where.append("i.filename LIKE ? ESCAPE '\\'")
        params.append("%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if prefix:
        where.append("(i.relative_path=? OR i.relative_path LIKE ? ESCAPE '\\')")
        params += [prefix, prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"]
    w = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) n FROM images i WHERE {w}", params).fetchone()["n"]
    col = _ORDERS.get(order, _ORDERS["name"])
    d = "DESC" if direction == "desc" else "ASC"
    page, page_size = max(1, page), min(200, max(1, page_size))
    rows = _rows(conn.execute(
        f"SELECT i.*, v.status AS volume_status, v.label AS volume_label FROM images i "
        f"JOIN volumes v ON v.id=i.volume_id WHERE {w} ORDER BY {col} {d}, i.id LIMIT ? OFFSET ?",
        (*params, page_size, (page - 1) * page_size)))
    return {"total": total, "page": page, "page_size": page_size, "items": rows}

def delete_fingerprints(conn, iid):
    conn.execute("DELETE FROM fingerprints WHERE image_id=?", (iid,))

def mark_analyses_stale(conn, iid):
    conn.execute("UPDATE analyses SET stale=1 WHERE image_id=?", (iid,))

def create_job(conn, kind, payload: dict, priority=0) -> str:
    jid = uuid.uuid4().hex
    conn.execute("INSERT INTO jobs (id, kind, payload_json, priority) VALUES (?,?,?,?)",
                 (jid, kind, json.dumps(payload), priority))
    return jid

def claim_job(conn, worker: str):
    now = utcnow()
    return _row(conn.execute(
        "UPDATE jobs SET status='running', claimed_by=?, started_at=?, heartbeat_at=? "
        "WHERE id=(SELECT id FROM jobs WHERE status='pending' AND pause_requested=0 "
        "          ORDER BY priority DESC, created_at ASC LIMIT 1) "
        "AND status='pending' RETURNING *", (worker, now, now)).fetchone())

def get_job(conn, jid): return _row(conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())

def list_jobs(conn, status=None, limit=100):
    if status:
        return _rows(conn.execute("SELECT * FROM jobs WHERE status=? ORDER BY created_at DESC LIMIT ?",
                                  (status, limit)))
    return _rows(conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)))

def job_progress(conn, jid, value, msg):
    conn.execute("UPDATE jobs SET progress=?, progress_msg=?, heartbeat_at=? WHERE id=?",
                 (value, msg, utcnow(), jid))

def job_heartbeat(conn, jid):
    conn.execute("UPDATE jobs SET heartbeat_at=? WHERE id=?", (utcnow(), jid))

def job_cancel_requested(conn, jid) -> bool:
    r = conn.execute("SELECT cancel_requested FROM jobs WHERE id=?", (jid,)).fetchone()
    return bool(r and r["cancel_requested"])

def finish_job(conn, jid, status, error=None, result=None):
    conn.execute("UPDATE jobs SET status=?, error=?, result_json=?, finished_at=?, heartbeat_at=? "
                 "WHERE id=?", (status, error, json.dumps(result) if result is not None else None,
                                utcnow(), utcnow(), jid))

def has_active_scan(conn, root_id) -> bool:
    r = conn.execute("SELECT 1 FROM jobs WHERE kind='scan_root' AND status IN ('pending','running') "
                     "AND json_extract(payload_json,'$.root_id')=? LIMIT 1", (root_id,)).fetchone()
    return r is not None

def get_setting(conn, key, default=None):
    r = conn.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(r["value_json"]) if r else default

def set_setting(conn, key, value):
    conn.execute("INSERT INTO settings (key, value_json, updated_at) VALUES (?,?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, "
                 "updated_at=excluded.updated_at", (key, json.dumps(value), utcnow()))

def create_session(conn, sid, expires_at, user_agent):
    conn.execute("INSERT INTO auth_sessions (id, expires_at, user_agent) VALUES (?,?,?)",
                 (sid, expires_at, (user_agent or "")[:300]))

def get_session(conn, sid):
    return _row(conn.execute("SELECT * FROM auth_sessions WHERE id=?", (sid,)).fetchone())

def delete_session(conn, sid):
    conn.execute("DELETE FROM auth_sessions WHERE id=?", (sid,))

def touch_session(conn, sid):
    conn.execute("UPDATE auth_sessions SET last_seen_at=? WHERE id=?", (utcnow(), sid))

def purge_expired_sessions(conn):
    conn.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (utcnow(),))