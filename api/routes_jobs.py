from fastapi import APIRouter, Depends
from core.errors import ServiceError
from .deps import get_jobs

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

@router.get("")
def list_jobs(status: str | None = None, limit: int = 100, jm=Depends(get_jobs)):
    return {"items": jm.list(status, min(limit, 500)), "paused": jm.is_paused()}

@router.get("/{jid}")
def get_job(jid: str, jm=Depends(get_jobs)):
    job = jm.get(jid)
    if not job:
        raise ServiceError("not_found", "job not found")
    return job

@router.post("/{jid}/cancel")
def cancel(jid: str, jm=Depends(get_jobs)):
    if not jm.request_cancel(jid):
        raise ServiceError("not_found", "job not found")
    return {"ok": True}

@router.post("/pause")
def pause(jm=Depends(get_jobs)):
    jm.pause(); return {"paused": True}

@router.post("/resume")
def resume(jm=Depends(get_jobs)):
    jm.resume(); return {"paused": False}