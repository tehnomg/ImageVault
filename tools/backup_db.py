"""Онлайн-бэкап SQLite (безопасен при работающем приложении, WAL)."""
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import load_config
from database.db import Database

cfg = load_config()
name = "imagevault_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + ".db"
dest = cfg.backups_dir / name
Database(cfg.db_path).backup(dest)
print("backup:", dest)