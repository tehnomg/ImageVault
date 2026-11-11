import os, shutil, sys
import pytest
from core import volume_manager as vm
from core.paths import safe_join, PathError
from tests.util import register_and_scan

def test_marker_roundtrip(tmp_path):
    u = vm.write_marker(str(tmp_path), "abc123")
    assert vm.read_marker(str(tmp_path)) == u
    with pytest.raises(Exception):
        vm.write_marker(str(tmp_path), "different")

def test_match_precedence():
    vols = [
        {"id": "A", "marker_uuid": "m1", "volume_guid": "g1", "fs_serial": "S1", "label": "L", "fs_type": "NTFS"},
        {"id": "B", "marker_uuid": None, "volume_guid": "g2", "fs_serial": "S2", "label": "L", "fs_type": "NTFS"},
    ]
    assert vm.match_identity(vm.Identity("X", marker_uuid="m1", volume_guid="g2"), vols)["id"] == "A"
    assert vm.match_identity(vm.Identity("X", volume_guid="g2"), vols)["id"] == "B"
    assert vm.match_identity(vm.Identity("X", fs_serial="S2", label="L"), vols)["id"] == "B"
    dup = vols + [dict(vols[1], id="C")]
    assert vm.match_identity(vm.Identity("X", fs_serial="S2", label="L"), dup) is None

def test_match_marker_ambiguous():
    rows = [
        {"id": "A", "marker_uuid": "m1", "volume_guid": None, "fs_serial": None, "label": None, "fs_type": None},
        {"id": "B", "marker_uuid": "m1", "volume_guid": None, "fs_serial": None, "label": None, "fs_type": None},
    ]
    assert vm.match_identity(vm.Identity("X", marker_uuid="m1"), rows) is None

@pytest.mark.parametrize("bad", ["../x", "a/../../b", "/etc/passwd", "C:/x", "\\srv\\share", "a\x00b"])
def test_safe_join_rejects(tmp_path, bad):
    with pytest.raises(PathError):
        safe_join(tmp_path, bad)

def test_safe_join_ok(tmp_path):
    assert safe_join(tmp_path, "a/b.png").name == "b.png"

def test_register_idempotent(client, sample):
    r1 = client.post("/api/volumes", json={"path": str(sample)}).json()
    r2 = client.post("/api/volumes", json={"path": str(sample)}).json()
    assert r1["id"] == r2["id"]

def test_marker_identity_after_move(client, sample, tmp_path):
    if sys.platform == "win32":
        pytest.skip("marker-in-dir move test is POSIX-only; on Windows use a removable disk")
    vid = client.post("/api/volumes", json={"path": str(sample), "create_marker": True}).json()["id"]
    moved = tmp_path / "moved_library"
    shutil.move(str(sample), str(moved))
    r2 = client.post("/api/volumes", json={"path": str(moved)}).json()
    assert r2["id"] == vid and r2["status"] == "online"

def test_marker_clone_conflict(client, sample, tmp_path):
    if sys.platform == "win32":
        pytest.skip("clone test needs two anchors; POSIX-only (Windows: two removable disks)")
    client.post("/api/volumes", json={"path": str(sample), "create_marker": True})
    clone = tmp_path / "clone"
    shutil.copytree(sample, clone)
    r = client.post("/api/volumes", json={"path": str(clone)})
    assert r.status_code == 409
    vols = client.get("/api/volumes").json()["items"]
    assert len(vols) == 1

def test_rebind(client, sample):
    vid, _ = register_and_scan(client, sample)
    db = client.app.state.db
    db.conn().execute("UPDATE volumes SET anchor=?, status='offline' WHERE id=?",
                      ("Z:\\nonexistent" if os.name == "nt" else "/nonexistent_iv", vid))
    img = client.get("/api/images").json()["items"][0]
    assert client.get(f"/api/images/{img['id']}/original").status_code == 409
    r = client.post(f"/api/volumes/{vid}/rebind", json={"path": str(sample)})
    assert r.status_code == 200 and r.json()["status"] == "online"
    assert client.get(f"/api/images/{img['id']}/original").status_code == 200

def _volume_base_rel(client, sample):
    response = client.post("/api/volumes", json={"path": str(sample)})
    assert response.status_code == 200, response.text
    volume = response.json()
    base_rel = os.path.relpath(
        os.path.realpath(sample),
        os.path.realpath(volume["anchor"]),
    ).replace("\\", "/")
    return volume["id"], "" if base_rel == "." else base_rel.strip("/")


def test_nested_root_rejected_when_parent_exists(client, sample):
    vid, parent = _volume_base_rel(client, sample)
    first = client.post(
        f"/api/volumes/{vid}/roots",
        json={"relative_path": parent},
    )
    assert first.status_code == 200, first.text

    child = f"{parent}/Photos".lstrip("/")
    (sample / "Photos").mkdir()
    response = client.post(
        f"/api/volumes/{vid}/roots",
        json={"relative_path": child},
    )
    assert response.status_code == 409, response.text
    assert "overlaps" in response.json()["message"]


def test_parent_root_rejected_when_nested_root_exists(client, sample):
    (sample / "Photos").mkdir()
    vid, parent = _volume_base_rel(client, sample)
    child = f"{parent}/Photos".lstrip("/")
    first = client.post(
        f"/api/volumes/{vid}/roots",
        json={"relative_path": child},
    )
    assert first.status_code == 200, first.text

    response = client.post(
        f"/api/volumes/{vid}/roots",
        json={"relative_path": parent},
    )
    assert response.status_code == 409, response.text


def test_sibling_roots_and_prefix_names_are_allowed(client, sample):
    (sample / "Photos").mkdir()
    (sample / "Photos-old").mkdir()
    vid, parent = _volume_base_rel(client, sample)
    photos = f"{parent}/Photos".lstrip("/")
    photos_old = f"{parent}/Photos-old".lstrip("/")

    first = client.post(f"/api/volumes/{vid}/roots", json={"relative_path": photos})
    second = client.post(f"/api/volumes/{vid}/roots", json={"relative_path": photos_old})
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] != second.json()["id"]


def test_exact_root_registration_remains_idempotent(client, sample):
    vid, parent = _volume_base_rel(client, sample)
    first = client.post(f"/api/volumes/{vid}/roots", json={"relative_path": parent})
    second = client.post(f"/api/volumes/{vid}/roots", json={"relative_path": parent})
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_volume_root_overlaps_every_nested_root(client, sample):
    (sample / "Photos").mkdir()
    vid, parent = _volume_base_rel(client, sample)
    child = f"{parent}/Photos".lstrip("/")
    first = client.post(f"/api/volumes/{vid}/roots", json={"relative_path": ""})
    assert first.status_code == 200, first.text
    response = client.post(f"/api/volumes/{vid}/roots", json={"relative_path": child})
    assert response.status_code == 409, response.text


@pytest.mark.skipif(os.name != "nt", reason="Windows case-insensitivity")
def test_nested_root_rejected_case_insensitively(client, sample):
    (sample / "Photos" / "subfolder").mkdir(parents=True)
    vid, parent = _volume_base_rel(client, sample)
    first = client.post(
        f"/api/volumes/{vid}/roots",
        json={"relative_path": f"{parent}/Photos".lstrip("/")},
    )
    assert first.status_code == 200, first.text
    response = client.post(
        f"/api/volumes/{vid}/roots",
        json={"relative_path": f"{parent}/photos/subfolder".lstrip("/")},
    )
    assert response.status_code == 409, response.text



def test_list_roots_passes_volume_id_to_repository(client, monkeypatch):
    captured = {}

    def fake_list_roots(conn, vid=None):
        captured["vid"] = vid
        return []

    monkeypatch.setattr("services.catalog.repo.list_roots", fake_list_roots)
    assert client.app.state.catalog.list_roots("volume-123") == []
    assert captured["vid"] == "volume-123"
