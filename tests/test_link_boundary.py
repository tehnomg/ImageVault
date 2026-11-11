"""Regression tests for the registered-root boundary around symlinks and junctions."""
import os
from pathlib import Path

import pytest
from PIL import Image

from tests.util import register_and_scan, rescan


def _mkimg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), (10, 120, 200)).save(path)


def _symlink(target: Path, link: Path, *, is_dir: bool = True) -> None:
    try:
        os.symlink(target, link, target_is_directory=is_dir)
    except (OSError, NotImplementedError, AttributeError) as exc:
        pytest.skip(f"symbolic-link creation unavailable: {exc}")


def _junction(target: Path, link: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows junction test")
    import _winapi
    # On Windows CI this must run, not silently skip: it is the junction coverage.
    _winapi.CreateJunction(str(target), str(link))


def _items(client):
    return client.get("/api/images", params={"page_size": 200}).json()["items"]


def _rels(client):
    return {item["relative_path"].replace("\\", "/") for item in _items(client)}


def _names(client):
    return {item["filename"] for item in _items(client)}


def _has_suffix(paths, suffix):
    return any(path.endswith(suffix) for path in paths)


def test_multiple_plain_subdirectories_are_scanned(client, sample):
    # Also catches Windows DirEntry.stat() zero inode/device values.
    _mkimg(sample / "folder_a" / "a.png")
    _mkimg(sample / "folder_b" / "b.png")
    register_and_scan(client, sample)
    rels = _rels(client)
    assert _has_suffix(rels, "folder_a/a.png")
    assert _has_suffix(rels, "folder_b/b.png")


def test_symlink_directory_inside_registered_root_is_followed(client, sample):
    _mkimg(sample / ".store" / "inside.png")
    _symlink(sample / ".store", sample / "link_inside")
    client.app.state.cfg.follow_symlinks = True
    register_and_scan(client, sample)
    assert _has_suffix(_rels(client), "link_inside/inside.png")


def test_symlink_directory_outside_registered_root_is_skipped(client, sample, tmp_path):
    outside = tmp_path / "outside"
    _mkimg(outside / "secret.png")
    _symlink(outside, sample / "link_outside")
    client.app.state.cfg.follow_symlinks = True
    register_and_scan(client, sample)
    assert "secret.png" not in _names(client)
    assert not _has_suffix(_rels(client), "link_outside/secret.png")
    assert len(_items(client)) == 12


def test_symlink_file_outside_registered_root_is_skipped(client, sample, tmp_path):
    outside = tmp_path / "outside_file" / "secret.png"
    _mkimg(outside)
    _symlink(outside, sample / "file_link.png", is_dir=False)
    client.app.state.cfg.follow_symlinks = True
    register_and_scan(client, sample)
    assert "secret.png" not in _names(client)
    assert "file_link.png" not in _names(client)


def test_junction_directory_outside_registered_root_is_skipped(client, sample, tmp_path):
    outside = tmp_path / "outside_junction"
    _mkimg(outside / "junction_secret.png")
    _junction(outside, sample / "junction_outside")
    client.app.state.cfg.follow_symlinks = True
    register_and_scan(client, sample)
    assert "junction_secret.png" not in _names(client)
    assert not _has_suffix(_rels(client), "junction_outside/junction_secret.png")


def test_junction_directory_inside_registered_root_is_followed(client, sample):
    _mkimg(sample / ".store" / "junction_inside.png")
    _junction(sample / ".store", sample / "junction_inside")
    client.app.state.cfg.follow_symlinks = True
    register_and_scan(client, sample)
    assert _has_suffix(_rels(client), "junction_inside/junction_inside.png")


def test_link_to_parent_does_not_recurse_or_duplicate(client, sample):
    _mkimg(sample / "sub" / "nested.png")
    _symlink(sample, sample / "sub" / "parent_link")
    client.app.state.cfg.follow_symlinks = True
    register_and_scan(client, sample)
    rels = _rels(client)
    assert _has_suffix(rels, "sub/nested.png")
    assert not any("sub/parent_link/" in path for path in rels)
    assert len(_items(client)) == 13


def test_broken_symlink_does_not_break_scan(client, sample):
    _symlink(sample / "does_not_exist", sample / "broken_link")
    client.app.state.cfg.follow_symlinks = True
    register_and_scan(client, sample)
    assert len(_items(client)) == 12


def test_follow_false_preserves_rows_indexed_through_links(client, sample, tmp_path):
    _mkimg(sample / ".store" / "inside.png")
    _mkimg(sample / ".store" / "target.png")
    _symlink(sample / ".store", sample / "dir_link")
    _symlink(sample / ".store" / "target.png", sample / "file_link.png", is_dir=False)
    outside = tmp_path / "outside_follow_false"
    _mkimg(outside / "external.png")
    _symlink(outside, sample / "outside_link")
    client.app.state.cfg.follow_symlinks = True
    volume_id, _ = register_and_scan(client, sample)
    assert _has_suffix(_rels(client), "dir_link/inside.png")
    assert "file_link.png" in _names(client)
    assert "external.png" not in _names(client)

    client.app.state.cfg.follow_symlinks = False
    rescan(client, volume_id)
    rows = {item["relative_path"]: item["scan_status"] for item in _items(client)}
    assert any(path.endswith("dir_link/inside.png") and status != "missing"
               for path, status in rows.items())
    assert any(path.endswith("file_link.png") and status != "missing"
               for path, status in rows.items())
    assert "external.png" not in _names(client)
