from __future__ import annotations
import hmac, logging, secrets, time
from datetime import datetime, timedelta, timezone
from database import repository as repo
from database.db import utcnow

log = logging.getLogger("imagevault.auth")
SESSION_COOKIE = "iv_session"
SESSION_TTL_DAYS = 30

def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

class AuthService:
    """Bearer-токен для API-клиентов + cookie-сессии для браузера (img не шлёт заголовки)."""
    def __init__(self, db, cfg):
        self.db, self.cfg = db, cfg

    def login(self, token: str, user_agent: str | None = None) -> str | None:
        if not self.cfg.auth_token:
            return "auth-disabled"
        if not hmac.compare_digest((token or "").encode(), self.cfg.auth_token.encode()):
            time.sleep(0.5)
            log.warning("failed login attempt")  # сам токен не логируется
            return None
        conn = self.db.conn()
        repo.purge_expired_sessions(conn)
        sid = secrets.token_urlsafe(32)
        expires = _fmt(datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS))
        repo.create_session(conn, sid, expires, user_agent)
        return sid

    def logout(self, sid: str | None):
        if sid:
            repo.delete_session(self.db.conn(), sid)

    def session_valid(self, sid: str | None) -> bool:
        if not sid:
            return False
        conn = self.db.conn()
        row = repo.get_session(conn, sid)
        if not row:
            return False
        if row["expires_at"] < utcnow():
            repo.delete_session(conn, sid)
            return False
        repo.touch_session(conn, sid)
        return True

    def request_authorized(self, request) -> bool:
        if not self.cfg.auth_token:
            return True
        h = request.headers.get("authorization", "")
        if h.startswith("Bearer ") and hmac.compare_digest(
                h[7:].encode(), self.cfg.auth_token.encode()):
            return True
        return self.session_valid(request.cookies.get(SESSION_COOKIE))

    def status(self, request) -> dict:
        return {"auth_required": bool(self.cfg.auth_token),
                "authenticated": self.request_authorized(request)}