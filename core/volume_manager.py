from __future__ import annotations
import json, logging, os, sys, uuid
from dataclasses import dataclass
from pathlib import Path
from database import repository as repo
from database.db import utcnow
from .errors import ServiceError

log = logging.getLogger("imagevault.volumes")
MARKER_NAME = ".imagevault_volume.json"
IS_WIN = sys.platform == "win32"

@dataclass
class Identity:
    anchor: str
    volume_guid: str | None = None
    fs_serial: str | None = None
    label: str | None = None
    fs_type: str | None = None
    media_type: str | None = None
    marker_uuid: str | None = None

def read_marker(anchor: str) -> str | None:
    try:
        data = json.loads((Path(anchor) / MARKER_NAME).read_text(encoding="utf-8"))
        v = data.get("imagevault_volume_uuid")
        return str(v) if v else None
    except (OSError, ValueError):
        return None

def write_marker(anchor: str, marker_uuid: str) -> str:
    p = Path(anchor) / MARKER_NAME
    existing = read_marker(anchor)
    if existing and existing != marker_uuid:
        raise ServiceError("conflict", "volume already has a different ImageVault marker")
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"imagevault_volume_uuid": marker_uuid, "schema_version": 1}),
                   encoding="utf-8")
    os.replace(tmp, p)
    return marker_uuid

def _probe_windows(anchor: str) -> Identity:
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    guid_buf = ctypes.create_unicode_buffer(512)
    guid = guid_buf.value if k32.GetVolumeNameForVolumeMountPointW(anchor, guid_buf, 512) else None
    serial, maxcomp, flags = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
    fs_buf, label_buf = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(256)
    ok = k32.GetVolumeInformationW(anchor, label_buf, 256, ctypes.byref(serial),
                                   ctypes.byref(maxcomp), ctypes.byref(flags), fs_buf, 256)
    if not ok and not guid:
        raise OSError(f"volume not ready: {anchor}")
    drive_types = {2: "removable", 3: "fixed", 4: "network", 5: "cdrom", 6: "ramdisk"}
    return Identity(anchor=anchor, volume_guid=guid or None,
                    fs_serial=f"{serial.value:08X}" if ok else None,
                    label=(label_buf.value or None) if ok else None,
                    fs_type=(fs_buf.value or None) if ok else None,
                    media_type=drive_types.get(k32.GetDriveTypeW(anchor), "unknown"),
                    marker_uuid=read_marker(anchor))

def probe(path: str | Path) -> Identity:
    p = Path(path).resolve()
    if IS_WIN:
        drive = os.path.splitdrive(str(p))[0]
        if not drive:
            raise ServiceError("bad_request", f"cannot determine drive for {path}")
        return _probe_windows(drive + "\\")
    if not p.is_dir():
        raise OSError(f"not a directory: {p}")
    st = p.stat()
    return Identity(anchor=str(p), fs_serial=str(st.st_dev), label=p.name,
                    media_type="unknown", marker_uuid=read_marker(str(p)))

def enumerate_anchors() -> list[str]:
    if not IS_WIN:
        return []
    import ctypes
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return [f"{chr(65 + i)}:\\" for i in range(26) if mask >> i & 1]

def is_system_drive(anchor: str) -> bool:
    if not IS_WIN:
        return False
    sysdrive = os.environ.get("SystemDrive", "C:") + "\\"
    return os.path.normcase(anchor) == os.path.normcase(sysdrive)

def match_identity(ident: Identity, volumes: list[dict]) -> dict | None:
    """marker -> GUID -> serial+label/fs. Любая неоднозначность => None (ручной rebind)."""
    if ident.marker_uuid:
        c = [v for v in volumes if v["marker_uuid"] == ident.marker_uuid]
        if len(c) == 1:
            return c[0]
        if len(c) > 1:
            log.warning("ambiguous marker %s...: %d registry rows; manual rebind required",
                        ident.marker_uuid[:8], len(c))
            return None
    if ident.volume_guid:
        c = [v for v in volumes if v["volume_guid"] == ident.volume_guid]
        if len(c) == 1:
            return c[0]
        if len(c) > 1:
            log.warning("ambiguous GUID match for %s; manual rebind required", ident.anchor)
            return None
    if ident.fs_serial:
        c = [v for v in volumes if v["fs_serial"] == ident.fs_serial
             and (v["label"] == ident.label or v["fs_type"] == ident.fs_type)]
        if len(c) == 1:
            return c[0]
        if len(c) > 1:
            log.warning("ambiguous serial match for %s; manual rebind required", ident.anchor)
    return None

def _ident_fields(ident: Identity) -> dict:
    return {"anchor": ident.anchor, "volume_guid": ident.volume_guid,
            "fs_serial": ident.fs_serial, "label": ident.label, "fs_type": ident.fs_type,
            "media_type": ident.media_type, "marker_uuid": ident.marker_uuid}

def register_volume(db, path: str, create_marker=False, allow_system_marker=False) -> dict:
    conn = db.conn()
    ident = probe(path)
    if create_marker and not ident.marker_uuid:
        if is_system_drive(ident.anchor) and not allow_system_marker:
            raise ServiceError("bad_request",
                               "marker on system drive requires allow_system_marker=true")
        ident.marker_uuid = write_marker(ident.anchor, uuid.uuid4().hex)
    volumes = repo.list_volumes(conn)
    m = match_identity(ident, volumes)
    now = utcnow()
    if m:
        # Защита от клонированного диска: маркер уже привязан, а старый якорь ещё жив.
        if (ident.marker_uuid and m["marker_uuid"] == ident.marker_uuid
                and os.path.normcase(m["anchor"] or "") != os.path.normcase(ident.anchor)):
            try:
                old = probe(m["anchor"])
            except (OSError, ServiceError):
                old = None
            if old and old.marker_uuid == ident.marker_uuid:
                raise ServiceError("conflict",
                                   "marker present on two mounts (cloned disk?); rebind manually")
        repo.update_volume(conn, m["id"], **_ident_fields(ident),
                           status="online", last_seen_at=now, identity_warning=None)
        return repo.get_volume(conn, m["id"])
    if ident.marker_uuid and any(v["marker_uuid"] == ident.marker_uuid for v in volumes):
        raise ServiceError("conflict", "ambiguous marker in registry; rebind manually")
    vid = repo.insert_volume(conn, {"id": uuid.uuid4().hex, **_ident_fields(ident),
                                    "status": "online", "last_seen_at": now})
    return repo.get_volume(conn, vid)

def refresh_volumes(db) -> list[dict]:
    conn = db.conn()
    volumes = repo.list_volumes(conn)
    matched: dict[str, str] = {}
    anchors = enumerate_anchors() or [v["anchor"] for v in volumes if v["anchor"]]
    for anchor in anchors:
        try:
            ident = probe(anchor)
        except (OSError, ServiceError):
            continue
        m = match_identity(ident, volumes)
        if not m:
            continue
        if m["id"] in matched:
            msg = f"identity seen on multiple mounts: {matched[m['id']]} and {ident.anchor}"
            repo.update_volume(conn, m["id"], identity_warning=msg)
            log.warning("volume %s: %s", m["id"], msg)
            continue
        repo.update_volume(conn, m["id"], **_ident_fields(ident),
                           status="online", last_seen_at=utcnow(), identity_warning=None)
        matched[m["id"]] = ident.anchor
    for v in volumes:
        if v["id"] not in matched and v["status"] != "offline":
            repo.update_volume(conn, v["id"], status="offline")
    return repo.list_volumes(conn)

def rebind_volume(db, volume_id: str, path: str, force=False) -> dict:
    conn = db.conn()
    v = repo.get_volume(conn, volume_id)
    if not v:
        raise ServiceError("not_found", "volume not found")
    ident = probe(path)
    if ident.marker_uuid and v["marker_uuid"] and ident.marker_uuid != v["marker_uuid"] and not force:
        raise ServiceError("conflict", "marker mismatch; use force=true only if you are sure")
    others = [x for x in repo.list_volumes(conn) if x["id"] != volume_id]
    if match_identity(ident, others):
        raise ServiceError("conflict", "path matches another registered volume")
    if ident.marker_uuid and any(x["marker_uuid"] == ident.marker_uuid for x in others):
        raise ServiceError("conflict", "ambiguous marker in registry; rebind manually")
    fields = _ident_fields(ident)
    if not ident.marker_uuid:
        fields.pop("marker_uuid")
    repo.update_volume(conn, volume_id, **fields, status="online",
                       last_seen_at=utcnow(), identity_warning=None)
    return repo.get_volume(conn, volume_id)