import io
from PIL import Image
from tests.util import register_and_scan, find_image

def test_thumbnail_ok(client, sample):
    register_and_scan(client, sample)
    img = find_image(client, "solid.png")
    r = client.get(f"/api/images/{img['id']}/thumbnail")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    im = Image.open(io.BytesIO(r.content))
    assert max(im.size) <= 320

def test_exif_orientation_applied(client, sample):
    register_and_scan(client, sample)
    img = find_image(client, "orient.jpg")
    assert img["orientation"] == 6 and img["width"] == 120 and img["height"] == 60
    im = Image.open(io.BytesIO(client.get(f"/api/images/{img['id']}/thumbnail").content))
    assert im.height > im.width

def test_animated_webp_first_frame(client, sample):
    register_and_scan(client, sample)
    img = find_image(client, "anim.webp")
    im = Image.open(io.BytesIO(client.get(f"/api/images/{img['id']}/thumbnail").content)).convert("RGB")
    r, g, b = im.getpixel((im.width // 2, im.height // 2))
    assert r > 150 and b < 100

def test_thumb_autoregenerate(client, sample):
    register_and_scan(client, sample)
    img = find_image(client, "solid.png")
    cfg = client.app.state.cfg
    (cfg.thumbs_dir / img["id"][:2] / (img["id"] + ".webp")).unlink()
    assert client.get(f"/api/images/{img['id']}/thumbnail").status_code == 200