from __future__ import annotations
import json, logging, os, uuid
from pathlib import Path
from database import repository as repo
from database.db import utcnow
from . import image_loader
from .errors import ServiceError
from .paths import safe_join, path_key

log = logging.getLogger("imagevault.scanner")
DEFAULT_EXCLUDE = {"$recycle.bin", "system volume information", ".imagevault_quarantine",
                   "__pycache__", "node_modules", ".git"}
REPARSE, HIDDEN = 0x400, 0x2

def _under(key: str, prefix_key: str) -> bool:
    return key == prefix_key or key.startswith(prefix_key + "/")

def scan_root(db, cfg, volume: dict, root: dict, ctx) -> dict:
    conn = db.conn()
    anchor = Path(volume["anchor"])
    prefix = root["relative_path"] or ""
    root_abs = anchor if not prefix else safe_join(anchor, prefix)
    if not root_abs.is_dir():
        raise ServiceError("not_found", f"root directory missing: {root_abs}")

    def rel_of(p) -> str:
        return os.path.relpath(p, anchor).replace(os.sep, "/")

    excl = (DEFAULT_EXCLUDE | {n.lower() for n in cfg.extra_exclude_dirs}
            | {n.lower() for n in json.loads(root["exclusions_json"] or "[]")})
    data_norm = os.path.normcase(str(cfg.data_dir.resolve()))
    stats = {"files": 0, "new": 0, "changed": 0, "corrupt": 0, "missing": 0}
    seen: set[str] = set()
    walk_errors: list[str] = []
    skipped_dirs: list[str] = []
    st0 = root_abs.stat()
    visited = {(st0.st_dev, st0.st_ino)}
    stack = [root_abs]
    follow = cfg.follow_symlinks
    while stack:
        ctx.checkpoint()  # отмена прерывает скан ДО фазы missing
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError as e:
            walk_errors.append(rel_of(d))
            log.warning("cannot list %s: %s", d, e)
            continue
        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError as e:
                walk_errors.append(rel_of(entry.path))
                log.warning("cannot stat %s: %s", entry.path, e)
                continue
            attrs = getattr(st, "st_file_attributes", 0)
            is_reparse = bool(attrs & REPARSE)
            if is_reparse and not follow:
                if entry.is_dir(follow_symlinks=False):
                    skipped_dirs.append(rel_of(entry.path))
                continue
            try:
                st_eff = os.stat(entry.path) if is_reparse else st
                is_dir = entry.is_dir(follow_symlinks=follow)
                is_file = entry.is_file(follow_symlinks=follow)
            except FileNotFoundError:
                skipped_dirs.append(rel_of(entry.path))  # битая ссылка — не ошибка обхода
                continue
            except OSError as e:
                walk_errors.append(rel_of(entry.path))
                log.warning("cannot access %s: %s", entry.path, e)
                continue
            if is_dir:
                name = entry.name
                rel_d = rel_of(entry.path)
                if name.lower() in excl or name.startswith("."):
                    skipped_dirs.append(rel_d)
                    continue
                if cfg.skip_hidden and attrs & HIDDEN:
                    skipped_dirs.append(rel_d)
                    continue
                if os.path.normcase(os.path.realpath(entry.path)) == data_norm:
                    skipped_dirs.append(rel_d)
                    continue
                if follow:
                    key = (st_eff.st_dev, st_eff.st_ino)
                    if key in visited:
                        skipped_dirs.append(rel_d)
                        continue
                    visited.add(key)
                stack.append(Path(entry.path))
            elif is_file:
                ext = os.path.splitext(entry.name)[1].lower()
                if ext not in image_loader.IMAGE_EXTS:
                    continue
                rel = rel_of(entry.path)
                if rel.startswith(".."):
                    skipped_dirs.append(rel_of(entry.path))  # symlink наружу тома
                    continue
                seen.add(path_key(rel))
                try:
                    _process_file(db, cfg, volume, rel, entry, st_eff, stats)
                except Exception:
                    log.exception("failed to process %s", entry.path)
                stats["files"] += 1
                if stats["files"] % 100 == 0:
                    ctx.progress(None, f"{stats['files']} файлов: +{stats['new']} новых, "
                                       f"~{stats['changed']} изменено")
    if walk_errors:
        stats["missing_check"] = "skipped_incomplete_walk"
        log.warning("missing-check skipped: %d access errors under root %s",
                    len(walk_errors), root_abs)
    else:
        skip_keys = []
        for skipped in skipped_dirs:
            skip_keys.append(path_key(skipped))

            # A directory may have been renamed to a hidden name.
            # Preserve catalog entries from its previous non-hidden path.
            parts = skipped.rsplit("/", 1)
            name = parts[-1]
            if name.startswith(".") and len(name) > 1:
                alias = (parts[0] + "/" if len(parts) == 2 else "") + name[1:]
                skip_keys.append(path_key(alias))
        pkey = path_key(prefix)
        for row in repo.images_under_root(conn, volume["id"]):
            k = path_key(row["relative_path"])
            if prefix and not _under(k, pkey):
                continue
            if k in seen:
                continue
            if any(_under(k, s) for s in skip_keys):
                continue
            repo.update_image(conn, row["id"], scan_status="missing")
            stats["missing"] += 1
        stats["missing_check"] = "complete"
    ctx.progress(1.0, f"готово: {stats}")
    return stats

def _process_file(db, cfg, volume, rel, entry, st, stats):
    conn = db.conn()
    existing = repo.get_image_by_path(conn, volume["id"], rel)
    if (existing and existing["scan_status"] == "ok"
            and existing["file_size"] == st.st_size
            and existing["mtime_ns"] == st.st_mtime_ns):
        return
    meta, error = image_loader.read_metadata(Path(entry.path))
    common = {"file_size": st.st_size, "mtime_ns": st.st_mtime_ns,
              "scanned_at": utcnow(), "scan_status": "ok" if meta else "corrupt",
              **(meta or {})}
    if existing:
        iid = existing["id"]
        changed = (existing["file_size"] != st.st_size
                   or existing["mtime_ns"] != st.st_mtime_ns)
        repo.update_image(conn, iid, **common)
        thumb = image_loader.thumb_path(cfg, iid)
        if changed:
            with db.tx():
                repo.delete_fingerprints(conn, iid)
                repo.mark_analyses_stale(conn, iid)
            thumb.unlink(missing_ok=True)
            stats["changed"] += 1
        if meta and (changed or not thumb.exists()):
            repo.create_job(conn, "thumbnail", {"image_id": iid})
    else:
        iid = repo.insert_image(conn, {
            "id": uuid.uuid4().hex, "volume_id": volume["id"], "relative_path": rel,
            "filename": os.path.basename(rel), "extension": os.path.splitext(rel)[1].lower(),
            **common})
        stats["new"] += 1
        if meta:
            repo.create_job(conn, "thumbnail", {"image_id": iid})
    if not meta:
        stats["corrupt"] += 1
        log.warning("corrupt image %s: %s", rel, error)