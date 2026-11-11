from __future__ import annotations
import logging, sqlite3, threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("imagevault.db")
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

def _migrations() -> list[tuple[int, Path]]:
    out = []
    for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
        out.append((int(f.name.split("_", 1)[0]), f))
    return out

class Database:
    """Одно соединение на поток; WAL; короткие транзакции; миграции по user_version."""
    def __init__(self, path: Path):
        self.path = Path(path)
        self._local = threading.local()

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=5, isolation_level=None)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=5000")
            c.execute("PRAGMA synchronous=NORMAL")
            self._local.c = c
        return c

    def init(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn().execute("PRAGMA journal_mode=WAL")
        self.migrate()

    def migrate(self):
        c = self.conn()
        current = c.execute("PRAGMA user_version").fetchone()[0]
        migs = _migrations()
        if [n for n, _ in migs] != list(range(1, len(migs) + 1)):
            raise RuntimeError("migration numbering must be sequential without gaps")
        for n, f in migs:
            if n <= current:
                continue
            sql = f.read_text(encoding="utf-8")
            log.info("applying migration %04d (%s)", n, f.name)
            try:
                c.executescript("BEGIN IMMEDIATE;\n" + sql
                                + f"\nPRAGMA user_version={n};\nCOMMIT;")
            except Exception:
                try:
                    c.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                log.exception("migration %04d failed, rolled back", n)
                raise

    @contextmanager
    def tx(self):
        c = self.conn()
        c.execute("BEGIN IMMEDIATE")
        try:
            yield c
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise

    def backup(self, dest: Path):
        dst = sqlite3.connect(dest)
        try:
            self.conn().backup(dst)
        finally:
            dst.close()