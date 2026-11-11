from fastapi.testclient import TestClient
from app import create_app
from tests.conftest import make_cfg
from tests.util import register_and_scan, find_image

def test_cookie_flow(tmp_path, sample):
    cfg = make_cfg(tmp_path / "authdata", auth_token="secret")
    with TestClient(create_app(cfg)) as c:
        assert c.get("/api/volumes").status_code == 401
        assert c.post("/api/auth/login", json={"token": "bad"}).status_code == 403
        s = c.get("/api/auth/status").json()
        assert s == {"auth_required": True, "authenticated": False}
        r = c.post("/api/auth/login", json={"token": "secret"})
        assert r.status_code == 200 and "iv_session" in c.cookies
        assert c.get("/api/volumes").status_code == 200
        register_and_scan(c, sample)
        img = find_image(c, "solid.png")
        # img-запросы: только cookie, без заголовка Authorization
        assert c.get(f"/api/images/{img['id']}/thumbnail").status_code == 200
        assert c.get(f"/api/images/{img['id']}/original").status_code == 200
        assert c.post("/api/auth/logout").status_code == 200
        assert c.get("/api/volumes").status_code == 401

def test_bearer_and_origin(tmp_path, sample):
    cfg = make_cfg(tmp_path / "authdata2", auth_token="secret")
    with TestClient(create_app(cfg)) as c:
        h = {"Authorization": "Bearer secret"}
        assert c.get("/api/volumes", headers=h).status_code == 200
        assert c.get("/api/volumes", headers={**h, "Origin": "http://evil.example"}).status_code == 403
        assert c.get("/api/volumes", headers={"Authorization": "Bearer wrong"}).status_code == 401

def test_no_auth_localhost(tmp_path):
    cfg = make_cfg(tmp_path / "noauth")
    with TestClient(create_app(cfg)) as c:
        assert c.get("/api/volumes").status_code == 200
        assert c.get("/api/auth/status").json() == {"auth_required": False, "authenticated": True}