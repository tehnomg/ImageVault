from __future__ import annotations
import argparse, logging, secrets
from contextlib import asynccontextmanager
from urllib.parse import urlparse
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from config import Config, WEB_DIR, load_config
from core.auth import AuthService
from core.errors import ServiceError, HTTP_CODES
from core.job_manager import JobManager
from database.db import Database
from services.catalog import CatalogService
from api import routes_auth, routes_volumes, routes_images, routes_jobs

log = logging.getLogger("imagevault.app")
AUTH_EXEMPT = {"/api/auth/login", "/api/auth/logout", "/api/auth/status"}

def setup_logging(cfg: Config):
    logger = logging.getLogger("imagevault")
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)
    logger.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.FileHandler(cfg.logs_dir / "imagevault.log", encoding="utf-8")
    sh = logging.StreamHandler()
    for h in (fh, sh):
        h.setFormatter(fmt)
        logger.addHandler(h)

def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or load_config()
    setup_logging(cfg)
    db = Database(cfg.db_path)
    db.init()
    jm = JobManager(db, workers=cfg.workers)
    catalog = CatalogService(db, cfg)
    auth = AuthService(db, cfg)
    jm.register("scan_root", catalog.run_scan)
    jm.register("thumbnail", catalog.run_thumbnail)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        jm.start()
        log.info("ImageVault started (data_dir=%s)", cfg.data_dir)
        yield
        jm.stop()

    app = FastAPI(title="ImageVault", version="0.2.0", lifespan=lifespan,
                  docs_url=None if cfg.auth_token else "/docs")
    app.state.cfg, app.state.db, app.state.jobs = cfg, db, jm
    app.state.catalog, app.state.auth = catalog, auth

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError):
        return JSONResponse({"error": exc.code, "message": exc.message},
                            status_code=HTTP_CODES.get(exc.code, 400))

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        if cfg.auth_token and path.startswith("/api") and path not in AUTH_EXEMPT:
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.url.netloc:
                return JSONResponse({"error": "forbidden_origin"}, status_code=403)
            if not auth.request_authorized(request):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    for r in (routes_auth.router, routes_volumes.router,
              routes_images.router, routes_jobs.router):
        app.include_router(r)

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app

def main():
    parser = argparse.ArgumentParser(description="ImageVault — local media catalog")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--show-token", action="store_true",
                        help="print access token to console and exit")
    args = parser.parse_args()
    cfg = load_config()
    if args.show_token:
        print(cfg.auth_token or "auth token is not set (localhost mode)")
        return
    if args.host: cfg.host = args.host
    if args.port: cfg.port = args.port
    if cfg.host not in ("127.0.0.1", "localhost", "::1") and not cfg.auth_token:
        cfg.auth_token = secrets.token_urlsafe(32)
        cfg.save()
        print("\n[ImageVault] LAN mode. Access token (console only, never logged):")
        print("  " + cfg.auth_token)
        print("  Enter it in the browser login form. Token is NOT passed via URL.\n")
    print(f"[ImageVault] http://{cfg.host}:{cfg.port}/")
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, log_level="info")

if __name__ == "__main__":
    main()