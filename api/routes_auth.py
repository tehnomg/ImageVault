from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from core.auth import SESSION_COOKIE, SESSION_TTL_DAYS
from core.errors import ServiceError
from .deps import get_auth

router = APIRouter(prefix="/api/auth", tags=["auth"])

class LoginBody(BaseModel):
    token: str

@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, svc=Depends(get_auth)):
    sid = svc.login(body.token, request.headers.get("user-agent"))
    if sid is None:
        raise ServiceError("forbidden", "invalid token")
    if sid != "auth-disabled":
        response.set_cookie(SESSION_COOKIE, sid, max_age=SESSION_TTL_DAYS * 86400,
                            httponly=True, samesite="strict", path="/",
                            secure=request.url.scheme == "https")
    return {"ok": True}

@router.post("/logout")
def logout(request: Request, response: Response, svc=Depends(get_auth)):
    svc.logout(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}

@router.get("/status")
def status(request: Request, svc=Depends(get_auth)):
    return svc.status(request)