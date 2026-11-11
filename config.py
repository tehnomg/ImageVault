from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"

@dataclass
class Config:
    data_dir: Path = BASE_DIR / "data"
    host: str = "127.0.0.1"
    port: int = 8765
    thumb_size: int = 320
    workers: int = 2
    follow_symlinks: bool = False
    skip_hidden: bool = True
    extra_exclude_dirs: list = field(default_factory=list)
    auth_token: str | None = None

    @property
    def db_path(self) -> Path: return self.data_dir / "imagevault.db"
    @property
    def thumbs_dir(self) -> Path: return self.data_dir / "thumbnails"
    @property
    def logs_dir(self) -> Path: return self.data_dir / "logs"
    @property
    def backups_dir(self) -> Path: return self.data_dir / "backups"

    def save(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        d = asdict(self); d.pop("data_dir")
        (self.data_dir / "config.json").write_text(
            json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

def load_config(data_dir: Path | None = None) -> Config:
    dd = Path(data_dir) if data_dir else BASE_DIR / "data"
    cfg = Config(data_dir=dd)
    f = dd / "config.json"
    if f.exists():
        for k, v in json.loads(f.read_text(encoding="utf-8")).items():
            if hasattr(cfg, k) and k != "data_dir":
                setattr(cfg, k, v)
    for p in (cfg.data_dir, cfg.thumbs_dir, cfg.logs_dir, cfg.backups_dir):
        p.mkdir(parents=True, exist_ok=True)
    return cfg