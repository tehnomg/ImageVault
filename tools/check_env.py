"""Проверка среды ImageVault. Запуск: python tools/check_env.py [--tree]"""
import importlib.metadata, shutil, sqlite3, sys
from pathlib import Path

FAIL = []

def check(name, fn, required=True):
    try:
        print(f"[OK]   {name}: {fn()}")
    except Exception as e:
        print(f"[{'FAIL' if required else 'WARN'}] {name}: {e}")
        if required:
            FAIL.append(name)

def ver(pkg):
    return importlib.metadata.version(pkg)

def py_check():
    if sys.version_info < (3, 10):
        raise RuntimeError("Python >= 3.10 required")
    return sys.version.split()[0]

def sqlite_ver():
    if sqlite3.sqlite_version_info < (3, 35):
        raise RuntimeError(f"SQLite {sqlite3.sqlite_version} too old (need >= 3.35)")
    return sqlite3.sqlite_version

def sqlite_features():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
    c.execute("CREATE TABLE j(a TEXT)")
    c.execute("INSERT INTO j VALUES('x')")
    assert c.execute("UPDATE j SET a='y' WHERE a='x' RETURNING a").fetchone()
    assert c.execute("SELECT json_extract('{\"a\":1}','$.a')").fetchone()[0] == 1
    return "FTS5 + RETURNING + JSON1"

def webp():
    from PIL import features, Image
    assert features.check("webp"), "no WebP"
    assert features.check("webp_anim"), "no animated WebP"
    return f"Pillow {Image.__version__}, webp+anim"

def which(name):
    p = shutil.which(name)
    if not p:
        raise RuntimeError("not in PATH")
    return p

check("python", py_check)
print(f"       platform: {sys.platform}")
check("sqlite", sqlite_ver)
check("sqlite features", sqlite_features)
for pkg in ("fastapi", "uvicorn", "pillow", "httpx", "pydantic", "pytest"):
    check(pkg, lambda p=pkg: ver(p))
check("Pillow WebP", webp)
check("mcp SDK (Этап 6)", lambda: ver("mcp"), required=False)
check("numpy (Этап 2)", lambda: ver("numpy"), required=False)
check("opencv (Этап 2)", lambda: ver("opencv-python-headless"), required=False)
check("ffmpeg (Этап 7)", lambda: which("ffmpeg"), required=False)
check("ffprobe (Этап 7)", lambda: which("ffprobe"), required=False)

if "--tree" in sys.argv:
    root = Path.cwd()
    print(f"\nДерево {root} (глубина 2):")
    for p in sorted(root.iterdir()):
        print(" ", p.name + ("/" if p.is_dir() else ""))
        if p.is_dir() and p.name not in {".venv", "data", ".git", "__pycache__"}:
            for q in sorted(p.iterdir())[:40]:
                print("   ", q.name)

print("\nИТОГ:", "ВСЁ ОК" if not FAIL else f"FAIL: {', '.join(FAIL)}")
sys.exit(1 if FAIL else 0)