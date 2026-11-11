from fastapi import APIRouter, Depends
from pydantic import BaseModel
from .deps import get_catalog

router = APIRouter(prefix="/api/volumes", tags=["volumes"])

class RegisterVolume(BaseModel):
    path: str
    create_marker: bool = False
    allow_system_marker: bool = False

class RebindVolume(BaseModel):
    path: str
    force: bool = False

class AddRoot(BaseModel):
    relative_path: str = ""

@router.get("")
def list_volumes(cat=Depends(get_catalog)):
    return {"items": cat.volumes(refresh=True)}

@router.post("")
def register_volume(body: RegisterVolume, cat=Depends(get_catalog)):
    return cat.register_volume(body.path, body.create_marker, body.allow_system_marker)

@router.post("/{vid}/rebind")
def rebind(vid: str, body: RebindVolume, cat=Depends(get_catalog)):
    return cat.rebind_volume(vid, body.path, body.force)

@router.get("/{vid}/roots")
def list_roots(vid: str, cat=Depends(get_catalog)):
    return {"items": cat.list_roots(vid)}

@router.post("/{vid}/roots")
def add_root(vid: str, body: AddRoot, cat=Depends(get_catalog)):
    return cat.add_root(vid, body.relative_path)