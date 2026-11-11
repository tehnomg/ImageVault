from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from core import image_loader
from .deps import get_catalog

router = APIRouter(prefix="/api", tags=["images"])

@router.get("/images")
def list_images(volume_id: str | None = None, status: str | None = None,
                q: str | None = None, order: str = "name", direction: str = "asc",
                page: int = 1, page_size: int = Query(60, le=200),
                cat=Depends(get_catalog)):
    return cat.list_images(volume_id=volume_id, status=status, q=q, order=order,
                           direction=direction, page=page, page_size=page_size)

@router.get("/images/{iid}")
def get_image(iid: str, cat=Depends(get_catalog)):
    return cat.get_image(iid)

@router.get("/images/{iid}/thumbnail")
def thumbnail(iid: str, cat=Depends(get_catalog)):
    return FileResponse(cat.thumb_file(iid), media_type="image/webp",
                        headers={"Cache-Control": "private, max-age=86400"})

@router.get("/images/{iid}/original")
def original(iid: str, cat=Depends(get_catalog)):
    row = cat.get_image(iid)
    p = cat.image_file(iid)
    mt = image_loader.MEDIA_TYPES.get(row["extension"], "application/octet-stream")
    return FileResponse(p, media_type=mt, filename=row["filename"],
                        headers={"Cache-Control": "no-store"})

@router.post("/roots/{root_id}/scan")
def scan_root(root_id: str, cat=Depends(get_catalog)):
    return {"job_id": cat.request_scan(root_id)}