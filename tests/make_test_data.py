"""Генератор тестовых данных (не использует пользовательские архивы).
CLI: python -m tests.make_test_data <каталог>"""
import random, shutil, sys
from pathlib import Path
from PIL import Image

def build_sample_tree(root: Path) -> Path:
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    solid = Image.new("RGB", (64, 64), (128, 64, 32))
    solid.save(root / "solid.png")
    shutil.copyfile(root / "solid.png", root / "solid_copy.png")
    solid.save(root / "solid.jpg", quality=95)
    solid.save(root / "solid_lossless.webp", lossless=True)
    grad = Image.linear_gradient("L").resize((256, 256)).convert("RGB")
    grad.save(root / "gradient.png")
    grad.save(root / "gradient_q40.jpg", quality=40)
    grad.resize((128, 128)).save(root / "gradient_128.png")
    o = grad.resize((120, 60))
    exif = Image.Exif(); exif[274] = 6
    o.save(root / "orient.jpg", exif=exif)
    Image.new("RGBA", (64, 64), (200, 30, 30, 128)).save(root / "alpha.png")
    f1 = Image.new("RGB", (64, 64), (220, 20, 20))
    f2 = Image.new("RGB", (64, 64), (20, 20, 220))
    f1.save(root / "anim.webp", save_all=True, append_images=[f2], duration=100, loop=0)
    rnd = random.Random(42)
    noise = Image.frombytes("RGB", (64, 64), bytes(rnd.randrange(256) for _ in range(64 * 64 * 3)))
    noise.save(root / "noise.png")
    (root / "broken.png").write_bytes((root / "solid.png").read_bytes()[:20])
    return root

if __name__ == "__main__":
    print("created:", build_sample_tree(Path(sys.argv[1])))