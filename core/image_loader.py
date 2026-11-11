from __future__ import annotations
import json, logging, os
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageOps

log = logging.getLogger("imagevault.images")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg",
               ".jpeg": "image/jpeg", ".webp": "image/webp"}
EXIF_NAMES = {271: "Make", 272: "Model", 274: "Orientation", 306: "DateTime",
              33434: "ExposureTime", 33437: "FNumber", 34855: "ISOSpeedRatings",
              37386: "FocalLength", 4082: "Flash"}

def thumb_path(cfg, image_id: str) -> Path:
    return cfg.thumbs_dir / image_id[:2] / f"{image_id}.webp"

def _exif_datetime(exif) -> str | None:
    try:
        s = exif.get_ifd(0x8769).get(36867) or exif.get(306)
        if s:
            return datetime.strptime(str(s), "%Y:%m:%d %H:%M:%S") \
                           .replace(tzinfo=timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError):
        pass
    return None

def read_metadata(path: Path) -> tuple[dict | None, str | None]:
    """Метаданные без полного декодирования. Анимированный WebP — только первый кадр."""
    try:
        st = path.stat()
        with Image.open(path) as im:
            if getattr(im, "is_animated", False):
                im.seek(0)
            exif = im.getexif()
            orientation = int(exif.get(274, 1) or 1)
            exif_json = json.dumps(
                {EXIF_NAMES.get(k, str(k)): str(v)[:200]
                 for k, v in exif.items() if k != 37500}, ensure_ascii=False)
            created = _exif_datetime(exif)
            if not created:
                ts = st.st_ctime if os.name == "nt" else st.st_mtime
                created = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            meta = {"width": im.width, "height": im.height, "format": im.format,
                    "mode": im.mode, "exif_json": exif_json,
                    "orientation": orientation, "created_at_fs": created}
            im.verify()
        return meta, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

def make_thumbnail(src: Path, dst: Path, size: int):
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        if getattr(im, "is_animated", False):
            im.seek(0)
        if (im.format or "").upper() == "JPEG":
            im.draft("RGB", (size * 2, size * 2))
        im = ImageOps.exif_transpose(im)
        im.thumbnail((size, size), Image.LANCZOS)
        has_alpha = "A" in im.getbands() or "transparency" in im.info
        im = im.convert("RGBA" if has_alpha else "RGB")
        tmp = dst.with_suffix(".tmp")
        im.save(tmp, "WEBP", quality=82, method=4)
    os.replace(tmp, dst)