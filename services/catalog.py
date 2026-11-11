from __future__ import annotations
import logging
from pathlib import Path
from core import image_loader, scanner, volume_manager as vm
from core.errors import ServiceError
from core.paths import safe_join, path_key
from database import repository as repo
from database.db import utcnow

log = logging.getLogger("imagevault.catalog")


def _root_paths_overlap(a: str, b: str) -> bool:
    """True when either registered root is equal to or inside the other."""
    a, b = path_key(a), path_key(b)

    def contains(parent: str, child: str) -> bool:
        return not parent or child == parent or child.startswith(parent + "/")

    return contains(a, b) or contains(b, a)


class CatalogService:
    """Единый сервисный слой: Web UI, REST и (позже) MCP вызывают только его."""
    def __init__(self, db, cfg):
        self.db, self.cfg = db, cfg

    def volumes(self, refresh=True):
        return vm.refresh_volumes(self.db) if refresh else repo.list_volumes(self.db.conn())

    def register_volume(self, path, create_marker=False, allow_system_marker=False):
        return vm.register_volume(self.db, path, create_marker, allow_system_marker)

    def rebind_volume(self, vid, path, force=False):
        return vm.rebind_volume(self.db, vid, path, force)

    def add_root(self, vid, relative_path: str):
        conn = self.db.conn()
        v = repo.get_volume(conn, vid)
        if not v:
            raise ServiceError("not_found", "volume not found")
        raw = (relative_path or "").replace("\\", "/")
        if raw:
            p = safe_join(Path(v["anchor"]), raw)
            if not p.is_dir():
                raise ServiceError("bad_request", f"not a directory: {relative_path}")
            rel = "/".join(part for part in raw.split("/") if part not in ("", "."))
        else:
            rel = ""

        roots = repo.list_roots(conn, vid)
        for r in roots:
            existing = r["relative_path"]
            if path_key(existing) == path_key(rel):
                return r
            if _root_paths_overlap(existing, rel):
                raise ServiceError(
                    "conflict",
                    f"root overlaps an existing registered root: {existing or '.'}",
                )

        rid = repo.insert_root(conn, vid, rel)
        return repo.get_root(conn, rid)

    def list_roots(self, vid): return repo.list_roots(self.db.conn())

    def request_scan(self, root_id) -> str:
        conn = self.db.conn()
        root = repo.get_root(conn, root_id)
        if not root:
            raise ServiceError("not_found", "root not found")
        v = repo.get_volume(conn, root["volume_id"])
        if not v or v["status"] != "online":
            raise ServiceError("offline", "volume is offline")
        if repo.has_active_scan(conn, root_id):
            raise ServiceError("conflict", "scan already queued or running for this root")
        return repo.create_job(conn, "scan_root", {"root_id": root_id}, priority=10)

    def run_scan(self, payload, ctx):
        conn = self.db.conn()
        root = repo.get_root(conn, payload["root_id"])
        if not root:
            raise ServiceError("not_found", "root not found")
        volume = repo.get_volume(conn, root["volume_id"])
        if not volume or volume["status"] != "online":
            raise ServiceError("offline", "volume went offline")
        stats = scanner.scan_root(self.db, self.cfg, volume, root, ctx)
        repo.set_root_scanned(conn, root["id"])
        repo.update_volume(conn, volume["id"], last_scan_at=utcnow())
        return stats

    def run_thumbnail(self, payload, ctx):
        iid = payload["image_id"]
        row = repo.get_image(self.db.conn(), iid)
        if not row or row["scan_status"] == "missing":
            return {"skipped": "missing"}
        src = self.image_file(iid)
        dst = image_loader.thumb_path(self.cfg, iid)
        try:
            image_loader.make_thumbnail(src, dst, self.cfg.thumb_size)
        except Exception as e:
            repo.update_image(self.db.conn(), iid, scan_status="corrupt")
            log.warning("thumbnail failed for %s: %s", iid, e)
            return {"skipped": "corrupt"}
        return {"thumbnail": str(dst)}

    def list_images(self, **kw): return repo.list_images(self.db.conn(), **kw)

    def get_image(self, iid):
        row = repo.get_image(self.db.conn(), iid)
        if not row:
            raise ServiceError("not_found", "image not found")
        return row

    def image_file(self, iid) -> Path:
        row = self.get_image(iid)
        if row["volume_status"] != "online":
            raise ServiceError("offline", "volume is offline; file is indexed but not accessible")
        if row["scan_status"] == "missing":
            raise ServiceError("not_found", "file is missing on disk")
        p = safe_join(Path(row["volume_anchor"]), row["relative_path"])
        if not p.is_file():
            repo.update_image(self.db.conn(), iid, scan_status="missing")
            raise ServiceError("not_found", "file disappeared; marked missing")
        return p

    def thumb_file(self, iid) -> Path:
        row = self.get_image(iid)
        dst = image_loader.thumb_path(self.cfg, iid)
        if not dst.exists():
            if row["scan_status"] != "ok":
                raise ServiceError("not_found", "no thumbnail for corrupt/missing image")
            image_loader.make_thumbnail(self.image_file(iid), dst, self.cfg.thumb_size)
        return dst
