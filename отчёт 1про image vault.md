# ImageVault — Этап 0 + Этап 1

## 0. Честные рамки (обязательно к прочтению)

В этом чате у меня **нет доступа к файловой системе и нет возможности запускать код**. Значит:

- «Проверить рабочую директорию» физически не могу. Допущение: **проект создаётся с нуля (greenfield)**. Если каталог `ImageVault/` уже существует — не перезаписывай ничего вслепую; приложенный `tools/check_env.py --tree` покажет дерево, пришли мне вывод.
- По твоим же правилам §25.3–25.5 я **не имею права объявить этап завершённым без фактического прогона тестов**. Поэтому статус всего нижеследующего: **CODE DELIVERED / UNVERIFIED**. Код полный, не заглушки; тестовый набор приложен; после твоего прогона `pytest` и `check_env.py` я по результатам переведу этапы в READY или починю точечно.

Это единственный способ выполнить ТЗ честно в данной среде. Дальше — работа.

---

## 1. Анализ ТЗ: архитектурные решения и найденные проблемы

ТЗ зрелое, противоречий мало. Ниже — решения, которые я принял там, где ТЗ допускает выбор, и реальные риски (§25.14 — минимальное обоснованное решение):

1. **Очередь задач в SQLite + несколько воркеров.** Гонки при захвате задачи решаются одним атомарным `UPDATE … WHERE id=(SELECT …) AND status='pending' RETURNING …` (SQLite ≥ 3.35). WAL + `busy_timeout=5000` + короткие транзакции. Состояние задач — только в БД, не в глобальных переменных (§25.7). Восстановление после падения: при старте `running → pending`.
2. **Идентификация томов — трёхуровневая.** Только GUID/серийник ненадёжны (форматирование, другой ПК, коллизии серийников). Добавляю opt-in **маркер-файл** `.imagevault_volume.json` в корне носителя (UUID). Приоритет сопоставления: marker → Volume GUID → (serial + label + fs_type), при неоднозначности — только ручной rebind. Маркер **не пишется на системный диск без явного флага** (иначе тесты/невнимательный клик загадят `C:\`). Это новый файл, оригиналы не изменяются.
3. **`sqlite3` вместо SQLAlchemy.** Полный контроль над WAL/транзакциями/claim-протоколом, минус одна тяжёлая зависимость, схема — plain SQL (§4 разрешает оба варианта).
4. **ImageHash предлагаю убрать на Этапе 2.** Он тянет SciPy + PyWavelets (~50 МБ). pHash/dHash реализуются на NumPy + OpenCV (OpenCV всё равно нужен для SSIM), алгоритм побитово совместим с ImageHash. Решение зафиксируем на Этапе 2; схема БД уже готова под оба варианта.
5. **Пауза** в v1 — на уровне очереди (новые задачи не захватываются) + кооперативная отмена конкретной задачи. Пауза уже выполняющейся задачи — кооперативная, добавим позже; статусы строго по ТЗ.
6. **Windows-first, POSIX-fallback.** Идентичность тома через `ctypes`/kernel32 (без pywin32). На POSIX — `st_dev` + маркер, чтобы тесты можно было гонять где угодно. Полная точность — только Windows, это документировано.
7. **FAT/exFAT: гранулярность mtime 2 секунды** — теоретически можно пропустить изменение. На Этапе 1 — size+mtime_ns (по ТЗ), опциональная hash-верификация — флаг позже.
8. **Безопасность раньше Этапа 8:** приложение откажется слушать не-loopback без Bearer-токена. Минимальный auth-middleware + проверка Origin уже в Этапе 0–1, чтобы случайный `--host 0.0.0.0` не открыл библиотеку.
9. **Миниатюры keyed by `image_id`** (не fingerprint): проще инвалидация при изменении файла; общий кэш для дубликатов — оптимизация позже. Формат WebP, атомарная запись, авторегенерация при отсутствии.
10. **FTS5 — отдельная синхронизируемая таблица** (не external-content с триггерами по JOIN'ам): заполняется сервисом при сохранении анализа (Этап 5). Токенизатор `unicode61 remove_diacritics 2`; porter — только английский, для русского — синонимы + префиксные запросы. Ограничение документировано.

---

## 2. Финальная структура

Отличия от предложенной: добавлен слой `services/` (единая бизнес-логика для Web/REST/MCP — §3.2), `core/errors.py` и `core/paths.py` (общие ошибки и безопасные пути, без циклических импортов), `tests/`, `tools/`. Остальное — по ТЗ; модули Этапов 2–8 создаются на своих этапах, пустых «искусственных» файлов нет.

```text
ImageVault/
├── app.py                  # вход: create_app() + python app.py
├── config.py
├── requirements.txt
├── README.md
├── core/
│   ├── errors.py
│   ├── paths.py            # safe_join, защита от выхода за корень
│   ├── volume_manager.py   # ctypes-идентичность, маркеры, refresh, rebind
│   ├── scanner.py          # инкрементальный обход
│   ├── image_loader.py     # метаданные, EXIF, миниатюры
│   └── job_manager.py      # SQLite-очередь, воркеры, cancel/pause/recovery
├── services/
│   └── catalog.py          # единый сервисный слой (Этап 1)
├── database/
│   ├── db.py               # соединения, WAL, tx, backup
│   ├── schema.sql          # полная схема (все таблицы ТЗ)
│   └── repository.py
├── api/
│   ├── deps.py
│   ├── routes_volumes.py
│   ├── routes_images.py
│   └── routes_jobs.py
├── web/
│   ├── index.html
│   ├── app.js              # Gallery + Viewer + Volumes + Jobs
│   └── style.css
├── tools/
│   ├── check_env.py        # проверка среды/зависимостей/SQLite
│   └── backup_db.py
├── tests/
│   ├── util.py
│   ├── conftest.py
│   ├── make_test_data.py
│   ├── test_volumes.py
│   ├── test_scan.py
│   ├── test_thumbnails.py
│   ├── test_jobs.py
│   └── test_api_auth.py
└── data/                   # создаётся при запуске: db, thumbnails, logs
```

Во всех пакетах (`core`, `services`, `database`, `api`, `tests`) — пустые `__init__.py`.

---

## 3. Совместимость зависимостей

**Python:** рекомендую **3.12 или 3.13** (у тебя уже стоит 3.13 — колёса для всего стека Этапа 0–1 под неё есть: pydantic-core, Pillow, numpy≥2.1, opencv≥4.11, scipy≥1.14.1). Окружение — отдельный venv, чужие окружения не трогаются (§2).

| Зависимость | Когда | Обоснование |
|---|---|---|
| fastapi (тянет pydantic v2) | Этап 0–1 | REST, валидация |
| uvicorn | Этап 0–1 | HTTP-сервер |
| Pillow | Этап 1 | декодирование, EXIF, миниатюры, WebP |
| httpx | Этап 1 | TestClient; позже — AI-адаптер |
| pytest | Этап 0–1 | тесты (dev) |
| numpy, opencv-python-headless | Этап 2 | pixel/SSIM/pHash/dHash; headless — без GUI-зависимостей |
| mcp (official SDK, ≥1.9, <2) | Этап 6 | требует Python ≥3.10, pydantic v2, anyio, httpx, starlette — **тот же стек, что FastAPI, конфликтов нет**; STDIO + Streamable HTTP в 1.x есть |
| FFmpeg/FFprobe | Этап 7 | внешние бинарники, не Python-пакеты |

Точные версии на ноябрь 2026 я в этой среде проверить не могу — для этого `tools/check_env.py`: он проверяет версии, FTS5, JSON1, RETURNING, WAL, WebP/анимированный WebP в Pillow, наличие ffmpeg, опционально `mcp`. **Запусти его первым делом и пришли вывод, если что-то FAIL.**

---

## 4. Код

### `requirements.txt`
```text
# ImageVault — Этапы 0–1. Этап 2 добавит numpy + opencv-python-headless.
fastapi>=0.115,<1.0
uvicorn>=0.30,<1.0
pillow>=10.4
httpx>=0.27
pytest>=8.0
```

### `config.py`
```python
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
```

### `database/schema.sql` — полная схема (все обязательные таблицы ТЗ §17)
```sql
PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS volumes (
  id            TEXT PRIMARY KEY,
  marker_uuid   TEXT,
  volume_guid   TEXT,
  fs_serial     TEXT,
  label         TEXT,
  fs_type       TEXT,
  media_type    TEXT,
  anchor        TEXT,                          -- последний известный корень ("E:\" / POSIX-каталог)
  status        TEXT NOT NULL DEFAULT 'offline' CHECK(status IN ('online','offline')),
  first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  last_seen_at  TEXT,
  last_scan_at  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_volumes_marker ON volumes(marker_uuid) WHERE marker_uuid IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_volumes_guid   ON volumes(volume_guid);
CREATE INDEX IF NOT EXISTS ix_volumes_serial ON volumes(fs_serial);

CREATE TABLE IF NOT EXISTS roots (
  id              TEXT PRIMARY KEY,
  volume_id       TEXT NOT NULL REFERENCES volumes(id) ON DELETE CASCADE,
  relative_path   TEXT NOT NULL,               -- '' = весь носитель; POSIX-разделители
  exclusions_json TEXT NOT NULL DEFAULT '[]',
  enabled         INTEGER NOT NULL DEFAULT 1,
  last_scan_at    TEXT,
  UNIQUE(volume_id, relative_path)
);

CREATE TABLE IF NOT EXISTS images (
  id            TEXT PRIMARY KEY,
  volume_id     TEXT NOT NULL REFERENCES volumes(id) ON DELETE CASCADE,
  relative_path TEXT NOT NULL,
  filename      TEXT NOT NULL,
  extension     TEXT NOT NULL,
  file_size     INTEGER,
  mtime_ns      INTEGER,
  width         INTEGER,
  height        INTEGER,
  format        TEXT,
  mode          TEXT,
  exif_json     TEXT,
  orientation   INTEGER DEFAULT 1,
  created_at_fs TEXT,
  scanned_at    TEXT,
  scan_status   TEXT NOT NULL DEFAULT 'ok' CHECK(scan_status IN ('ok','corrupt','missing')),
  UNIQUE(volume_id, relative_path)
);
CREATE INDEX IF NOT EXISTS ix_images_filename ON images(filename);
CREATE INDEX IF NOT EXISTS ix_images_size     ON images(file_size);
CREATE INDEX IF NOT EXISTS ix_images_status   ON images(volume_id, scan_status);

CREATE TABLE IF NOT EXISTS fingerprints (
  image_id     TEXT PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
  sha256       TEXT,
  pixel_hash   TEXT,
  pixel_width  INTEGER,
  pixel_height INTEGER,
  pixel_mode   TEXT,
  phash        INTEGER,                        -- 64 бит, знаковое INTEGER
  dhash        INTEGER,
  algo_version INTEGER NOT NULL DEFAULT 1,
  computed_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_fp_sha   ON fingerprints(sha256);
CREATE INDEX IF NOT EXISTS ix_fp_pixel ON fingerprints(pixel_hash);
CREATE INDEX IF NOT EXISTS ix_fp_phash ON fingerprints(phash);
CREATE INDEX IF NOT EXISTS ix_fp_dhash ON fingerprints(dhash);

CREATE TABLE IF NOT EXISTS duplicate_groups (
  id                 TEXT PRIMARY KEY,
  kind               TEXT NOT NULL CHECK(kind IN ('byte','pixel','visual')),
  params_json        TEXT,
  status             TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved','ignored')),
  preferred_image_id TEXT REFERENCES images(id) ON DELETE SET NULL,
  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at         TEXT
);
CREATE TABLE IF NOT EXISTS duplicate_members (
  group_id    TEXT NOT NULL REFERENCES duplicate_groups(id) ON DELETE CASCADE,
  image_id    TEXT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
  similarity  REAL,
  metrics_json TEXT,
  PRIMARY KEY(group_id, image_id)
);
CREATE INDEX IF NOT EXISTS ix_dm_image ON duplicate_members(image_id);

CREATE TABLE IF NOT EXISTS analyses (
  id             TEXT PRIMARY KEY,
  image_id       TEXT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
  profile        TEXT NOT NULL,
  schema_version INTEGER NOT NULL DEFAULT 1,
  model          TEXT,
  backend        TEXT,
  prompt_version TEXT,
  source_sha256  TEXT,
  status         TEXT NOT NULL CHECK(status IN ('completed','failed','uncertain')),
  result_json    TEXT,
  error          TEXT,
  stale          INTEGER NOT NULL DEFAULT 0,
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_analyses_image ON analyses(image_id, profile, created_at);

CREATE TABLE IF NOT EXISTS tags (
  id        INTEGER PRIMARY KEY,
  canonical TEXT NOT NULL UNIQUE,
  category  TEXT
);
CREATE TABLE IF NOT EXISTS tag_synonyms (
  id      INTEGER PRIMARY KEY,
  tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  synonym TEXT NOT NULL,
  lang    TEXT NOT NULL DEFAULT 'ru',
  UNIQUE(tag_id, synonym, lang)
);
CREATE INDEX IF NOT EXISTS ix_syn ON tag_synonyms(synonym);
CREATE TABLE IF NOT EXISTS image_tags (
  image_id   TEXT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
  tag_id     INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  source     TEXT NOT NULL DEFAULT 'ai' CHECK(source IN ('ai','user','import')),
  confidence REAL,
  PRIMARY KEY(image_id, tag_id)
);

CREATE TABLE IF NOT EXISTS videos (
  id                    TEXT PRIMARY KEY,
  volume_id             TEXT NOT NULL REFERENCES volumes(id) ON DELETE CASCADE,
  relative_path         TEXT NOT NULL,
  filename              TEXT NOT NULL,
  extension             TEXT NOT NULL,
  file_size             INTEGER,
  mtime_ns              INTEGER,
  duration_s            REAL,
  width                 INTEGER,
  height                INTEGER,
  fps                   REAL,
  video_codec           TEXT,
  audio_codec           TEXT,
  bitrate               INTEGER,
  audio_streams_json    TEXT,
  created_at_fs         TEXT,
  sha256                TEXT,
  sidecar_relative_path TEXT,
  index_status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK(index_status IN ('pending','indexed','failed','missing','stale')),
  scanned_at            TEXT,
  UNIQUE(volume_id, relative_path)
);
CREATE TABLE IF NOT EXISTS video_frames (
  id            TEXT PRIMARY KEY,
  video_id      TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  ts_ms         INTEGER NOT NULL,
  relative_path TEXT NOT NULL,                 -- относительно папки кадров sidecar
  width         INTEGER,
  height        INTEGER,
  kind          TEXT NOT NULL DEFAULT 'interval' CHECK(kind IN ('first','interval','scene','manual')),
  description   TEXT
);
CREATE INDEX IF NOT EXISTS ix_vf_video ON video_frames(video_id, ts_ms);
CREATE TABLE IF NOT EXISTS video_analyses (
  id             TEXT PRIMARY KEY,
  video_id       TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  frame_id       TEXT REFERENCES video_frames(id) ON DELETE CASCADE,
  profile        TEXT NOT NULL,
  model          TEXT,
  backend        TEXT,
  prompt_version TEXT,
  status         TEXT NOT NULL,
  result_json    TEXT,
  error          TEXT,
  stale          INTEGER NOT NULL DEFAULT 0,
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS jobs (
  id               TEXT PRIMARY KEY,
  kind             TEXT NOT NULL,
  payload_json     TEXT NOT NULL DEFAULT '{}',
  status           TEXT NOT NULL DEFAULT 'pending'
                   CHECK(status IN ('pending','running','completed','failed','cancelled')),
  priority         INTEGER NOT NULL DEFAULT 0,
  progress         REAL,
  progress_msg     TEXT,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  pause_requested  INTEGER NOT NULL DEFAULT 0,
  claimed_by       TEXT,
  error            TEXT,
  result_json      TEXT,
  created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  started_at       TEXT,
  heartbeat_at     TEXT,
  finished_at      TEXT
);
CREATE INDEX IF NOT EXISTS ix_jobs_claim ON jobs(status, priority DESC, created_at);

CREATE TABLE IF NOT EXISTS file_actions (
  id                TEXT PRIMARY KEY,
  image_id          TEXT REFERENCES images(id) ON DELETE SET NULL,
  video_id          TEXT REFERENCES videos(id) ON DELETE SET NULL,
  volume_id         TEXT REFERENCES volumes(id) ON DELETE SET NULL,
  action            TEXT NOT NULL CHECK(action IN
                    ('mark_delete','unmark_delete','quarantine','restore','final_delete')),
  src_relative_path TEXT NOT NULL,
  dst_relative_path TEXT,
  sha256            TEXT,
  status            TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','done','failed','cancelled')),
  actor             TEXT NOT NULL DEFAULT 'user' CHECK(actor IN ('user','api','mcp')),
  details_json      TEXT,
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  executed_at       TEXT
);
CREATE INDEX IF NOT EXISTS ix_fa_image ON file_actions(image_id, created_at);

CREATE TABLE IF NOT EXISTS settings (
  key        TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Заполняется сервисом на Этапе 5 (Reference Search).
CREATE VIRTUAL TABLE IF NOT EXISTS images_fts USING fts5(
  image_id UNINDEXED,
  short_description, full_description, tags, objects, scene, style, colors, notes,
  tokenize = "unicode61 remove_diacritics 2"
);
```

### `database/db.py`
```python
from __future__ import annotations
import sqlite3, threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

class Database:
    """Одно соединение на поток; WAL; короткие транзакции. Состояние — только в БД."""
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
        c = self.conn()
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

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
```

### `database/repository.py`
```python
from __future__ import annotations
import json, sqlite3, uuid
from .db import utcnow

def _row(r): return dict(r) if r is not None else None
def _rows(rs): return [dict(r) for r in rs]

_IMAGE_COLS = {"file_size","mtime_ns","width","height","format","mode","exif_json",
               "orientation","created_at_fs","scanned_at","scan_status"}
_VOL_COLS = {"marker_uuid","volume_guid","fs_serial","label","fs_type","media_type",
             "anchor","status","last_seen_at","last_scan_at"}

def _update(conn, table, pk, id_, fields, allowed):
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields: return
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE {table} SET {sets} WHERE {pk}=?", (*fields.values(), id_))

# ---- volumes ----
def insert_volume(conn, vol: dict) -> str:
    vid = vol.get("id") or uuid.uuid4().hex
    cols = ["id"] + [k for k in _VOL_COLS if k in vol]
    conn.execute(f"INSERT INTO volumes ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",
                 [vid] + [vol[k] for k in cols[1:]])
    return vid

def update_volume(conn, vid, **f): _update(conn, "volumes", "id", vid, f, _VOL_COLS)
def get_volume(conn, vid): return _row(conn.execute("SELECT * FROM volumes WHERE id=?", (vid,)).fetchone())
def list_volumes(conn): return _rows(conn.execute("SELECT * FROM volumes ORDER BY label, anchor"))

# ---- roots ----
def insert_root(conn, vid, rel) -> str:
    rid = uuid.uuid4().hex
    conn.execute("INSERT INTO roots (id, volume_id, relative_path) VALUES (?,?,?)", (rid, vid, rel))
    return rid

def get_root(conn, rid): return _row(conn.execute("SELECT * FROM roots WHERE id=?", (rid,)).fetchone())
def list_roots(conn, vid=None):
    if vid: return _rows(conn.execute("SELECT * FROM roots WHERE volume_id=?", (vid,)))
    return _rows(conn.execute("SELECT * FROM roots"))

def set_root_scanned(conn, rid):
    conn.execute("UPDATE roots SET last_scan_at=? WHERE id=?", (utcnow(), rid))

# ---- images ----
def insert_image(conn, row: dict) -> str:
    iid = row.get("id") or uuid.uuid4().hex
    cols = list(row.keys())
    if "id" not in cols: cols = ["id"] + cols
    vals = [iid] + [row[k] for k in cols if k != "id"]
    conn.execute(f"INSERT INTO images ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})", vals)
    return iid

def update_image(conn, iid, **f): _update(conn, "images", "id", iid, f, _IMAGE_COLS)

def get_image(conn, iid):
    return _row(conn.execute(
        "SELECT i.*, v.status AS volume_status, v.label AS volume_label, v.anchor AS volume_anchor "
        "FROM images i JOIN volumes v ON v.id=i.volume_id WHERE i.id=?", (iid,)).fetchone())

def get_image_by_path(conn, vid, rel):
    return _row(conn.execute("SELECT * FROM images WHERE volume_id=? AND relative_path=?",
                             (vid, rel)).fetchone())

def images_under_root(conn, vid):
    return _rows(conn.execute(
        "SELECT id, relative_path FROM images WHERE volume_id=? AND scan_status!='missing'", (vid,)))

_ORDERS = {"name": "filename COLLATE NOCASE", "mtime": "mtime_ns",
           "size": "file_size", "scanned": "scanned_at"}

def list_images(conn, volume_id=None, status=None, q=None, prefix=None,
                order="name", direction="asc", page=1, page_size=60):
    where, params = ["1=1"], []
    if volume_id: where.append("i.volume_id=?"); params.append(volume_id)
    if status: where.append("i.scan_status=?"); params.append(status)
    if q:
        where.append("i.filename LIKE ? ESCAPE '\\'")
        params.append("%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if prefix:
        where.append("(i.relative_path=? OR i.relative_path LIKE ? ESCAPE '\\')")
        params += [prefix, prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"]
    w = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) n FROM images i WHERE {w}", params).fetchone()["n"]
    col = _ORDERS.get(order, _ORDERS["name"])
    d = "DESC" if direction == "desc" else "ASC"
    page, page_size = max(1, page), min(200, max(1, page_size))
    rows = _rows(conn.execute(
        f"SELECT i.*, v.status AS volume_status, v.label AS volume_label FROM images i "
        f"JOIN volumes v ON v.id=i.volume_id WHERE {w} ORDER BY {col} {d}, i.id LIMIT ? OFFSET ?",
        (*params, page_size, (page - 1) * page_size)))
    return {"total": total, "page": page, "page_size": page_size, "items": rows}

# ---- fingerprints / analyses ----
def delete_fingerprints(conn, iid):
    conn.execute("DELETE FROM fingerprints WHERE image_id=?", (iid,))

def mark_analyses_stale(conn, iid):
    conn.execute("UPDATE analyses SET stale=1 WHERE image_id=?", (iid,))

# ---- jobs ----
def create_job(conn, kind, payload: dict, priority=0) -> str:
    jid = uuid.uuid4().hex
    conn.execute("INSERT INTO jobs (id, kind, payload_json, priority) VALUES (?,?,?,?)",
                 (jid, kind, json.dumps(payload), priority))
    return jid

def claim_job(conn, worker: str):
    now = utcnow()
    return _row(conn.execute(
        "UPDATE jobs SET status='running', claimed_by=?, started_at=?, heartbeat_at=? "
        "WHERE id=(SELECT id FROM jobs WHERE status='pending' AND pause_requested=0 "
        "          ORDER BY priority DESC, created_at ASC LIMIT 1) "
        "AND status='pending' RETURNING *", (worker, now, now)).fetchone())

def get_job(conn, jid): return _row(conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())

def list_jobs(conn, status=None, limit=100):
    if status:
        return _rows(conn.execute("SELECT * FROM jobs WHERE status=? ORDER BY created_at DESC LIMIT ?",
                                  (status, limit)))
    return _rows(conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)))

def job_progress(conn, jid, value, msg):
    conn.execute("UPDATE jobs SET progress=?, progress_msg=?, heartbeat_at=? WHERE id=?",
                 (value, msg, utcnow(), jid))

def job_heartbeat(conn, jid):
    conn.execute("UPDATE jobs SET heartbeat_at=? WHERE id=?", (utcnow(), jid))

def job_cancel_requested(conn, jid) -> bool:
    r = conn.execute("SELECT cancel_requested FROM jobs WHERE id=?", (jid,)).fetchone()
    return bool(r and r["cancel_requested"])

def finish_job(conn, jid, status, error=None, result=None):
    conn.execute("UPDATE jobs SET status=?, error=?, result_json=?, finished_at=?, heartbeat_at=? "
                 "WHERE id=?", (status, error, json.dumps(result) if result is not None else None,
                                utcnow(), utcnow(), jid))

def requeue_running(conn):
    conn.execute("UPDATE jobs SET status='pending', claimed_by=NULL, started_at=NULL "
                 "WHERE status='running'")

def has_active_scan(conn, root_id) -> bool:
    r = conn.execute("SELECT 1 FROM jobs WHERE kind='scan_root' AND status IN ('pending','running') "
                     "AND json_extract(payload_json,'$.root_id')=? LIMIT 1", (root_id,)).fetchone()
    return r is not None

# ---- settings ----
def get_setting(conn, key, default=None):
    r = conn.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(r["value_json"]) if r else default

def set_setting(conn, key, value):
    conn.execute("INSERT INTO settings (key, value_json, updated_at) VALUES (?,?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, "
                 "updated_at=excluded.updated_at", (key, json.dumps(value), utcnow()))
```

### `core/errors.py`
```python
class ServiceError(Exception):
    """Бизнес-ошибка с HTTP-кодом. Единая для API/MCP/UI."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

HTTP_CODES = {"bad_request": 400, "forbidden": 403, "not_found": 404,
              "offline": 409, "conflict": 409}
```

### `core/paths.py`
```python
from __future__ import annotations
import os, re
from pathlib import Path
from .errors import ServiceError

class PathError(ServiceError):
    def __init__(self, message: str): super().__init__("bad_request", message)

def safe_join(base: Path, rel: str) -> Path:
    """Никаких абсолютных путей, дисков, '..', NUL; результат строго внутри base."""
    if not isinstance(rel, str) or "\x00" in rel:
        raise PathError("invalid relative path")
    r = rel.replace("\\", "/")
    if r.startswith("/") or re.match(r"^[A-Za-z]:", r):
        raise PathError("absolute paths are not allowed")
    parts = [p for p in r.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise PathError("parent traversal is not allowed")
    b = Path(os.path.normcase(str(base.resolve())))
    p = Path(os.path.normcase(str(base.joinpath(*parts).resolve())))
    if os.path.commonpath([str(p), str(b)]) != str(b):
        raise PathError("path escapes registered root")
    return p
```

### `core/volume_manager.py`
```python
from __future__ import annotations
import json, logging, os, sys, uuid
from dataclasses import dataclass
from pathlib import Path
from database import repository as repo
from database.db import utcnow
from .errors import ServiceError

log = logging.getLogger("imagevault.volumes")
MARKER_NAME = ".imagevault_volume.json"
IS_WIN = sys.platform == "win32"

@dataclass
class Identity:
    anchor: str
    volume_guid: str | None = None
    fs_serial: str | None = None
    label: str | None = None
    fs_type: str | None = None
    media_type: str | None = None
    marker_uuid: str | None = None

# ---------- маркер ----------
def read_marker(anchor: str) -> str | None:
    try:
        data = json.loads((Path(anchor) / MARKER_NAME).read_text(encoding="utf-8"))
        v = data.get("imagevault_volume_uuid")
        return str(v) if v else None
    except (OSError, ValueError):
        return None

def write_marker(anchor: str, marker_uuid: str) -> str:
    p = Path(anchor) / MARKER_NAME
    existing = read_marker(anchor)
    if existing and existing != marker_uuid:
        raise ServiceError("conflict", "volume already has a different ImageVault marker")
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"imagevault_volume_uuid": marker_uuid, "schema_version": 1}),
                   encoding="utf-8")
    os.replace(tmp, p)
    return marker_uuid

# ---------- платформенные пробы ----------
def _probe_windows(anchor: str) -> Identity:
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    guid_buf = ctypes.create_unicode_buffer(512)
    guid = guid_buf.value if k32.GetVolumeNameForVolumeMountPointW(anchor, guid_buf, 512) else None
    serial, maxcomp, flags = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
    fs_buf, label_buf = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(256)
    ok = k32.GetVolumeInformationW(anchor, label_buf, 256, ctypes.byref(serial),
                                   ctypes.byref(maxcomp), ctypes.byref(flags), fs_buf, 256)
    if not ok and not guid:
        raise OSError(f"volume not ready: {anchor}")
    drive_types = {2: "removable", 3: "fixed", 4: "network", 5: "cdrom", 6: "ramdisk"}
    return Identity(anchor=anchor, volume_guid=guid or None,
                    fs_serial=f"{serial.value:08X}" if ok else None,
                    label=label_buf.value or None if ok else None,
                    fs_type=fs_buf.value or None if ok else None,
                    media_type=drive_types.get(k32.GetDriveTypeW(anchor), "unknown"),
                    marker_uuid=read_marker(anchor))

def probe(path: str | Path) -> Identity:
    p = Path(path).resolve()
    if IS_WIN:
        drive = os.path.splitdrive(str(p))[0]
        if not drive:
            raise ServiceError("bad_request", f"cannot determine drive for {path}")
        return _probe_windows(drive + "\\")
    # POSIX: dev/тестовый режим. Якорь = зарегистрированный каталог, маркер внутри него.
    if not p.is_dir():
        raise OSError(f"not a directory: {p}")
    st = p.stat()
    return Identity(anchor=str(p), fs_serial=str(st.st_dev), label=p.name,
                    media_type="unknown", marker_uuid=read_marker(str(p)))

def enumerate_anchors() -> list[str]:
    if not IS_WIN:
        return []
    import ctypes
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return [f"{chr(65 + i)}:\\" for i in range(26) if mask >> i & 1]

def is_system_drive(anchor: str) -> bool:
    if not IS_WIN:
        return False
    sysdrive = os.environ.get("SystemDrive", "C:") + "\\"
    return os.path.normcase(anchor) == os.path.normcase(sysdrive)

# ---------- сопоставление ----------
def match_identity(ident: Identity, volumes: list[dict]) -> dict | None:
    if ident.marker_uuid:
        for v in volumes:
            if v["marker_uuid"] == ident.marker_uuid:
                return v
    if ident.volume_guid:
        c = [v for v in volumes if v["volume_guid"] == ident.volume_guid]
        if len(c) == 1: return c[0]
        if len(c) > 1:
            log.warning("ambiguous GUID match for %s — manual rebind required", ident.anchor)
            return None
    if ident.fs_serial:
        c = [v for v in volumes if v["fs_serial"] == ident.fs_serial
             and (v["label"] == ident.label or v["fs_type"] == ident.fs_type)]
        if len(c) == 1: return c[0]
        if len(c) > 1:
            log.warning("ambiguous serial match for %s — manual rebind required", ident.anchor)
    return None

def _ident_fields(ident: Identity) -> dict:
    return {"anchor": ident.anchor, "volume_guid": ident.volume_guid,
            "fs_serial": ident.fs_serial, "label": ident.label, "fs_type": ident.fs_type,
            "media_type": ident.media_type, "marker_uuid": ident.marker_uuid}

# ---------- операции ----------
def register_volume(db, path: str, create_marker=False, allow_system_marker=False) -> dict:
    conn = db.conn()
    ident = probe(path)
    if create_marker and not ident.marker_uuid:
        if is_system_drive(ident.anchor) and not allow_system_marker:
            raise ServiceError("bad_request",
                               "marker on system drive requires allow_system_marker=true")
        ident.marker_uuid = write_marker(ident.anchor, uuid.uuid4().hex)
    volumes = repo.list_volumes(conn)
    m = match_identity(ident, volumes)
    now = utcnow()
    if m:
        repo.update_volume(conn, m["id"], **_ident_fields(ident), status="online", last_seen_at=now)
        return repo.get_volume(conn, m["id"])
    vid = repo.insert_volume(conn, {"id": uuid.uuid4().hex, **_ident_fields(ident),
                                    "status": "online", "last_seen_at": now})
    return repo.get_volume(conn, vid)

def refresh_volumes(db) -> list[dict]:
    conn = db.conn()
    volumes = repo.list_volumes(conn)
    matched: set[str] = set()
    anchors = enumerate_anchors() or [v["anchor"] for v in volumes if v["anchor"]]
    for anchor in anchors:
        try:
            ident = probe(anchor)
        except (OSError, ServiceError):
            continue
        m = match_identity(ident, volumes)
        if m and m["id"] not in matched:
            repo.update_volume(conn, m["id"], **_ident_fields(ident),
                               status="online", last_seen_at=utcnow())
            matched.add(m["id"])
    for v in volumes:
        if v["id"] not in matched and v["status"] != "offline":
            repo.update_volume(conn, v["id"], status="offline")
    return repo.list_volumes(conn)

def rebind_volume(db, volume_id: str, path: str, force=False) -> dict:
    conn = db.conn()
    v = repo.get_volume(conn, volume_id)
    if not v:
        raise ServiceError("not_found", "volume not found")
    ident = probe(path)
    if ident.marker_uuid and v["marker_uuid"] and ident.marker_uuid != v["marker_uuid"] and not force:
        raise ServiceError("conflict", "marker mismatch; use force=true only if you are sure")
    other = match_identity(ident, [x for x in repo.list_volumes(conn) if x["id"] != volume_id])
    if other:
        raise ServiceError("conflict", f"path matches another registered volume {other['id']}")
    fields = _ident_fields(ident)
    if not ident.marker_uuid:
        fields.pop("marker_uuid")  # не затираем известный маркер отсутствующим
    repo.update_volume(conn, volume_id, **fields, status="online", last_seen_at=utcnow())
    return repo.get_volume(conn, volume_id)
```

### `core/image_loader.py`
```python
from __future__ import annotations
import json, logging, os
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageOps

log = logging.getLogger("imagevault.images")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg",
               ".jpeg": "image/jpeg", ".webp": "image/webp"}
EXIF_NAMES = {271: "Make", 272: "Model", 274: "Orientation", 306: "DateTime",
              33434: "ExposureTime", 33437: "FNumber", 34855: "ISOSpeedRatings",
              37386: "FocalLength", 4082: "Flash"}  # MakerNote (37500) намеренно не экспортируем

def thumb_path(cfg, image_id: str) -> Path:
    return cfg.thumbs_dir / image_id[:2] / f"{image_id}.webp"

def _exif_datetime(exif) -> str | None:
    try:
        s = exif.get_ifd(0x8769).get(36867) or exif.get(306)
        if s:
            return datetime.strptime(str(s), "%Y:%m:%d %H:%M:%S") \
                           .replace(tzinfo=timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError):
        pass
    return None

def read_metadata(path: Path) -> tuple[dict | None, str | None]:
    """Метаданные без полного декодирования. Анимированный WebP — только первый кадр."""
    try:
        st = path.stat()
        with Image.open(path) as im:
            if getattr(im, "is_animated", False):
                im.seek(0)
            exif = im.getexif()
            orientation = int(exif.get(274, 1) or 1)
            exif_json = json.dumps(
                {EXIF_NAMES.get(k, str(k)): str(v)[:200]
                 for k, v in exif.items() if k != 37500}, ensure_ascii=False)
            created = _exif_datetime(exif)
            if not created:
                ts = st.st_ctime if os.name == "nt" else st.st_mtime  # NT: st_ctime = создание
                created = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            meta = {"width": im.width, "height": im.height, "format": im.format,
                    "mode": im.mode, "exif_json": exif_json,
                    "orientation": orientation, "created_at_fs": created}
            im.verify()  # структурная проверка; после verify объект не используется
        return meta, None
    except Exception as e:  # повреждённый файл не должен останавливать сканирование
        return None, f"{type(e).__name__}: {e}"

def make_thumbnail(src: Path, dst: Path, size: int):
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        if getattr(im, "is_animated", False):
            im.seek(0)
        if (im.format or "").upper() == "JPEG":
            im.draft("RGB", (size * 2, size * 2))  # быстрое декодирование JPEG
        im = ImageOps.exif_transpose(im)
        im.thumbnail((size, size), Image.LANCZOS)
        has_alpha = "A" in im.getbands() or "transparency" in im.info
        im = im.convert("RGBA" if has_alpha else "RGB")
        tmp = dst.with_suffix(".tmp")
        im.save(tmp, "WEBP", quality=82, method=4)
    os.replace(tmp, dst)  # атомарно
```

### `core/scanner.py`
```python
from __future__ import annotations
import json, logging, os, uuid
from pathlib import Path
from database import repository as repo
from database.db import utcnow
from . import image_loader
from .errors import ServiceError
from .job_manager import JobCancelled  # noqa: F401  (пробрасывается через ctx.checkpoint)
from .paths import safe_join

log = logging.getLogger("imagevault.scanner")
DEFAULT_EXCLUDE = {"$recycle.bin", "system volume information", ".imagevault_quarantine",
                   "__pycache__", "node_modules", ".git"}
REPARSE, HIDDEN = 0x400, 0x2

def scan_root(db, cfg, volume: dict, root: dict, ctx) -> dict:
    conn = db.conn()
    anchor = Path(volume["anchor"])
    prefix = root["relative_path"] or ""
    root_abs = anchor if not prefix else safe_join(anchor, prefix)
    if not root_abs.is_dir():
        raise ServiceError("not_found", f"root directory missing: {root_abs}")
    excl = (DEFAULT_EXCLUDE | {n.lower() for n in cfg.extra_exclude_dirs}
            | {n.lower() for n in json.loads(root["exclusions_json"] or "[]")})
    data_norm = os.path.normcase(str(cfg.data_dir.resolve()))
    stats = {"files": 0, "new": 0, "changed": 0, "corrupt": 0, "missing": 0}
    seen: set[str] = set()
    st0 = root_abs.stat()
    visited = {(st0.st_dev, st0.st_ino)}
    stack = [root_abs]
    while stack:
        ctx.checkpoint()
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError as e:
            log.warning("cannot list %s: %s", d, e)
            continue
        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            attrs = getattr(st, "st_file_attributes", 0)
            if attrs & REPARSE and not cfg.follow_symlinks:
                continue  # junction/symlink: по умолчанию неходим — защита от циклов
            if entry.is_dir(follow_symlinks=False):
                name = entry.name
                if name.lower() in excl or name.startswith("."):
                    continue
                if cfg.skip_hidden and attrs & HIDDEN:
                    continue
                if os.path.normcase(os.path.realpath(entry.path)) == data_norm:
                    continue
                if cfg.follow_symlinks:
                    key = (st.st_dev, st.st_ino)
                    if key in visited:
                        continue
                    visited.add(key)
                stack.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                ext = os.path.splitext(entry.name)[1].lower()
                if ext not in image_loader.IMAGE_EXTS:
                    continue
                rel = os.path.relpath(entry.path, anchor).replace(os.sep, "/")
                seen.add(rel)
                try:
                    _process_file(db, cfg, volume, rel, entry, st, stats)
                except Exception:
                    log.exception("failed to process %s", entry.path)
                stats["files"] += 1
                if stats["files"] % 100 == 0:
                    ctx.progress(None, f"{stats['files']} файлов: +{stats['new']} новых, "
                                       f"~{stats['changed']} изменено")
    for row in repo.images_under_root(conn, volume["id"]):
        rel = row["relative_path"]
        if prefix and not (rel == prefix or rel.startswith(prefix + "/")):
            continue
        if rel not in seen:
            repo.update_image(conn, row["id"], scan_status="missing")
            stats["missing"] += 1
    ctx.progress(1.0, f"готово: {stats}")
    return stats

def _process_file(db, cfg, volume, rel, entry, st, stats):
    conn = db.conn()
    existing = repo.get_image_by_path(conn, volume["id"], rel)
    if (existing and existing["scan_status"] == "ok"
            and existing["file_size"] == st.st_size
            and existing["mtime_ns"] == st.st_mtime_ns):
        return  # инкрементальность: не трогаем хеши/миниатюры/анализ
    meta, error = image_loader.read_metadata(Path(entry.path))
    common = {"file_size": st.st_size, "mtime_ns": st.st_mtime_ns,
              "scanned_at": utcnow(), "scan_status": "ok" if meta else "corrupt",
              **(meta or {})}
    if existing:
        iid = existing["id"]
        changed = (existing["file_size"] != st.st_size
                   or existing["mtime_ns"] != st.st_mtime_ns)
        repo.update_image(conn, iid, **common)
        thumb = image_loader.thumb_path(cfg, iid)
        if changed:
            with db.tx():
                repo.delete_fingerprints(conn, iid)
                repo.mark_analyses_stale(conn, iid)
            thumb.unlink(missing_ok=True)
            stats["changed"] += 1
        if meta and (changed or not thumb.exists()):
            repo.create_job(conn, "thumbnail", {"image_id": iid})
    else:
        iid = repo.insert_image(conn, {
            "id": uuid.uuid4().hex, "volume_id": volume["id"], "relative_path": rel,
            "filename": os.path.basename(rel), "extension": os.path.splitext(rel)[1].lower(),
            **common})
        stats["new"] += 1
        if meta:
            repo.create_job(conn, "thumbnail", {"image_id": iid})
    if not meta:
        stats["corrupt"] += 1
        log.warning("corrupt image %s: %s", rel, error)
```

### `core/job_manager.py`
```python
from __future__ import annotations
import json, logging, os, threading, time
from database import repository as repo

log = logging.getLogger("imagevault.jobs")

class JobCancelled(Exception):
    pass

class JobContext:
    def __init__(self, db, job_id: str):
        self.db, self.job_id = db, job_id

    def checkpoint(self):
        conn = self.db.conn()
        if repo.job_cancel_requested(conn, self.job_id):
            raise JobCancelled()
        repo.job_heartbeat(conn, self.job_id)

    def progress(self, value: float | None, msg: str | None = None):
        repo.job_progress(self.db.conn(), self.job_id, value, msg)
        if repo.job_cancel_requested(self.db.conn(), self.job_id):
            raise JobCancelled()

class JobManager:
    """Персистентная очередь в SQLite. Захват — атомарный UPDATE...RETURNING."""
    def __init__(self, db, workers: int = 2):
        self.db = db
        self.workers = max(1, workers)
        self._handlers: dict = {}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def register(self, kind: str, fn):
        self._handlers[kind] = fn

    def start(self):
        self.recover_stale()
        for i in range(self.workers):
            t = threading.Thread(target=self._loop, args=(f"pid{os.getpid()}-t{i}",),
                                 name=f"iv-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self):
        self._stop.set()
        for t in self._threads:
            t.join(timeout=5)

    def recover_stale(self):
        """После аварийного завершения: running -> pending (§3.3)."""
        self.db.conn().execute(
            "UPDATE jobs SET status='pending', claimed_by=NULL, started_at=NULL "
            "WHERE status='running'")

    # ---- facade для API/MCP ----
    def create(self, kind, payload, priority=0) -> str:
        return repo.create_job(self.db.conn(), kind, payload, priority)

    def get(self, jid): return repo.get_job(self.db.conn(), jid)
    def list(self, status=None, limit=100): return repo.list_jobs(self.db.conn(), status, limit)

    def request_cancel(self, jid):
        with self.db.tx() as conn:
            job = repo.get_job(conn, jid)
            if not job:
                return False
            conn.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (jid,))
            if job["status"] == "pending":
                repo.finish_job(conn, jid, "cancelled")
        return True

    def pause(self): repo.set_setting(self.db.conn(), "queue_paused", True)
    def resume(self): repo.set_setting(self.db.conn(), "queue_paused", False)
    def is_paused(self) -> bool: return bool(repo.get_setting(self.db.conn(), "queue_paused", False))

    # ---- внутренний цикл ----
    def _loop(self, worker: str):
        conn = self.db.conn()
        while not self._stop.is_set():
            if self.is_paused():
                self._stop.wait(0.5)
                continue
            job = repo.claim_job(conn, worker)
            if job is None:
                self._stop.wait(0.4)
                continue
            jid, kind = job["id"], job["kind"]
            ctx = JobContext(self.db, jid)
            handler = self._handlers.get(kind)
            try:
                if handler is None:
                    raise RuntimeError(f"no handler registered for job kind '{kind}'")
                result = handler(json.loads(job["payload_json"]), ctx)
                repo.finish_job(conn, jid, "completed", result=result)
            except JobCancelled:
                repo.finish_job(conn, jid, "cancelled")
                log.info("job %s (%s) cancelled", jid, kind)
            except Exception as e:
                log.exception("job %s (%s) failed", jid, kind)
                repo.finish_job(conn, jid, "failed", error=f"{type(e).__name__}: {e}")
```

### `services/catalog.py`
```python
from __future__ import annotations
import logging, os
from pathlib import Path
from core import image_loader, scanner, volume_manager as vm
from core.errors import ServiceError
from core.paths import safe_join
from database import repository as repo
from database.db import utcnow

log = logging.getLogger("imagevault.catalog")

class CatalogService:
    """Единый сервисный слой: Web UI, REST и (позже) MCP вызывают только его."""
    def __init__(self, db, cfg):
        self.db, self.cfg = db, cfg

    # ---- volumes / roots ----
    def volumes(self, refresh=True):
        return vm.refresh_volumes(self.db) if refresh else repo.list_volumes(self.db.conn())

    def register_volume(self, path, create_marker=False, allow_system_marker=False):
        return vm.register_volume(self.db, path, create_marker, allow_system_marker)

    def rebind_volume(self, vid, path, force=False):
        return vm.rebind_volume(self.db, vid, path, force)

    def add_root(self, vid, relative_path: str):
        conn = self.db.conn()
        v = repo.get_volume(conn, vid)
        if not v:
            raise ServiceError("not_found", "volume not found")
        rel = (relative_path or "").replace("\\", "/").strip("/")
        if rel:
            p = safe_join(Path(v["anchor"]), rel)
            if not p.is_dir():
                raise ServiceError("bad_request", f"not a directory: {relative_path}")
        existing = [r for r in repo.list_roots(conn, vid) if r["relative_path"] == rel]
        if existing:
            return existing[0]
        rid = repo.insert_root(conn, vid, rel)
        return repo.get_root(conn, rid)

    def list_roots(self, vid): return repo.list_roots(self.db.conn(), vid)

    def request_scan(self, root_id) -> str:
        conn = self.db.conn()
        root = repo.get_root(conn, root_id)
        if not root:
            raise ServiceError("not_found", "root not found")
        v = repo.get_volume(conn, root["volume_id"])
        if not v or v["status"] != "online":
            raise ServiceError("offline", "volume is offline")
        if repo.has_active_scan(conn, root_id):
            raise ServiceError("conflict", "scan already queued or running for this root")
        return repo.create_job(conn, "scan_root", {"root_id": root_id}, priority=10)

    # ---- job handlers ----
    def run_scan(self, payload, ctx):
        conn = self.db.conn()
        root = repo.get_root(conn, payload["root_id"])
        if not root:
            raise ServiceError("not_found", "root not found")
        volume = repo.get_volume(conn, root["volume_id"])
        if not volume or volume["status"] != "online":
            raise ServiceError("offline", "volume went offline")
        stats = scanner.scan_root(self.db, self.cfg, volume, root, ctx)
        repo.set_root_scanned(conn, root["id"])
        repo.update_volume(conn, volume["id"], last_scan_at=utcnow())
        return stats

    def run_thumbnail(self, payload, ctx):
        iid = payload["image_id"]
        row = repo.get_image(self.db.conn(), iid)
        if not row or row["scan_status"] == "missing":
            return {"skipped": "missing"}
        src = self.image_file(iid)
        dst = image_loader.thumb_path(self.cfg, iid)
        try:
            image_loader.make_thumbnail(src, dst, self.cfg.thumb_size)
        except Exception as e:
            repo.update_image(self.db.conn(), iid, scan_status="corrupt")
            log.warning("thumbnail failed for %s: %s", iid, e)
            return {"skipped": "corrupt"}
        return {"thumbnail": str(dst)}

    # ---- images ----
    def list_images(self, **kw): return repo.list_images(self.db.conn(), **kw)

    def get_image(self, iid):
        row = repo.get_image(self.db.conn(), iid)
        if not row:
            raise ServiceError("not_found", "image not found")
        return row

    def image_file(self, iid) -> Path:
        row = self.get_image(iid)
        if row["volume_status"] != "online":
            raise ServiceError("offline", "volume is offline; file is indexed but not accessible")
        if row["scan_status"] == "missing":
            raise ServiceError("not_found", "file is missing on disk")
        p = safe_join(Path(row["volume_anchor"]), row["relative_path"])
        if not p.is_file():
            repo.update_image(self.db.conn(), iid, scan_status="missing")
            raise ServiceError("not_found", "file disappeared; marked missing")
        return p

    def thumb_file(self, iid) -> Path:
        row = self.get_image(iid)
        dst = image_loader.thumb_path(self.cfg, iid)
        if not dst.exists():
            if row["scan_status"] != "ok":
                raise ServiceError("not_found", "no thumbnail for corrupt/missing image")
            image_loader.make_thumbnail(self.image_file(iid), dst, self.cfg.thumb_size)
        return dst
```

### `api/deps.py`
```python
from fastapi import Request

def get_catalog(request: Request):
    return request.app.state.catalog

def get_jobs(request: Request):
    return request.app.state.jobs
```

### `api/routes_volumes.py`
```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from .deps import get_catalog

router = APIRouter(prefix="/api/volumes", tags=["volumes"])

class RegisterVolume(BaseModel):
    path: str
    create_marker: bool = False
    allow_system_marker: bool = False

class RebindVolume(BaseModel):
    path: str
    force: bool = False

class AddRoot(BaseModel):
    relative_path: str = ""

@router.get("")
def list_volumes(cat=Depends(get_catalog)):
    return {"items": cat.volumes(refresh=True)}

@router.post("")
def register_volume(body: RegisterVolume, cat=Depends(get_catalog)):
    return cat.register_volume(body.path, body.create_marker, body.allow_system_marker)

@router.post("/{vid}/rebind")
def rebind(vid: str, body: RebindVolume, cat=Depends(get_catalog)):
    return cat.rebind_volume(vid, body.path, body.force)

@router.get("/{vid}/roots")
def list_roots(vid: str, cat=Depends(get_catalog)):
    return {"items": cat.list_roots(vid)}

@router.post("/{vid}/roots")
def add_root(vid: str, body: AddRoot, cat=Depends(get_catalog)):
    return cat.add_root(vid, body.relative_path)
```

### `api/routes_images.py`
```python
from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from core import image_loader
from core.errors import ServiceError
from .deps import get_catalog, get_jobs

router = APIRouter(prefix="/api", tags=["images"])

@router.get("/images")
def list_images(volume_id: str | None = None, status: str | None = None,
                q: str | None = None, order: str = "name", direction: str = "asc",
                page: int = 1, page_size: int = Query(60, le=200),
                cat=Depends(get_catalog)):
    return cat.list_images(volume_id=volume_id, status=status, q=q, order=order,
                           direction=direction, page=page, page_size=page_size)

@router.get("/images/{iid}")
def get_image(iid: str, cat=Depends(get_catalog)):
    return cat.get_image(iid)

@router.get("/images/{iid}/thumbnail")
def thumbnail(iid: str, cat=Depends(get_catalog)):
    return FileResponse(cat.thumb_file(iid), media_type="image/webp",
                        headers={"Cache-Control": "private, max-age=86400"})

@router.get("/images/{iid}/original")
def original(iid: str, cat=Depends(get_catalog)):
    row = cat.get_image(iid)
    p = cat.image_file(iid)
    mt = image_loader.MEDIA_TYPES.get(row["extension"], "application/octet-stream")
    return FileResponse(p, media_type=mt, filename=row["filename"],
                        headers={"Cache-Control": "no-store"})

@router.post("/roots/{root_id}/scan")
def scan_root(root_id: str, cat=Depends(get_catalog)):
    return {"job_id": cat.request_scan(root_id)}
```

### `api/routes_jobs.py`
```python
from fastapi import APIRouter, Depends
from core.errors import ServiceError
from .deps import get_jobs

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

@router.get("")
def list_jobs(status: str | None = None, limit: int = 100, jm=Depends(get_jobs)):
    return {"items": jm.list(status, min(limit, 500)), "paused": jm.is_paused()}

@router.get("/{jid}")
def get_job(jid: str, jm=Depends(get_jobs)):
    job = jm.get(jid)
    if not job:
        raise ServiceError("not_found", "job not found")
    return job

@router.post("/{jid}/cancel")
def cancel(jid: str, jm=Depends(get_jobs)):
    if not jm.request_cancel(jid):
        raise ServiceError("not_found", "job not found")
    return {"ok": True}

@router.post("/pause")
def pause(jm=Depends(get_jobs)):
    jm.pause(); return {"paused": True}

@router.post("/resume")
def resume(jm=Depends(get_jobs)):
    jm.resume(); return {"paused": False}
```

### `app.py`
```python
from __future__ import annotations
import argparse, logging, secrets
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import Config, WEB_DIR, load_config
from core.errors import ServiceError, HTTP_CODES
from core.job_manager import JobManager
from database.db import Database
from services.catalog import CatalogService
from api import routes_volumes, routes_images, routes_jobs

log = logging.getLogger("imagevault.app")

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
    jm.register("scan_root", catalog.run_scan)
    jm.register("thumbnail", catalog.run_thumbnail)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        jm.start()
        log.info("ImageVault started (data_dir=%s)", cfg.data_dir)
        yield
        jm.stop()

    app = FastAPI(title="ImageVault", version="0.1.0", lifespan=lifespan,
                  docs_url=None if cfg.auth_token else "/docs")
    app.state.cfg, app.state.db, app.state.jobs, app.state.catalog = cfg, db, jm, catalog

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError):
        return JSONResponse({"error": exc.code, "message": exc.message},
                            status_code=HTTP_CODES.get(exc.code, 400))

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        if cfg.auth_token and request.url.path.startswith("/api"):
            if request.headers.get("authorization") != f"Bearer {cfg.auth_token}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.url.netloc:
                return JSONResponse({"error": "forbidden_origin"}, status_code=403)
        return await call_next(request)

    app.include_router(routes_volumes.router)
    app.include_router(routes_images.router)
    app.include_router(routes_jobs.router)

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app

def main():
    parser = argparse.ArgumentParser(description="ImageVault — local media catalog")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    cfg = load_config()
    if args.host: cfg.host = args.host
    if args.port: cfg.port = args.port
    loopback = cfg.host in ("127.0.0.1", "localhost", "::1")
    if not loopback and not cfg.auth_token:
        cfg.auth_token = secrets.token_urlsafe(32)
        cfg.save()
        # Токен печатается один раз в консоль и НЕ попадает в лог-файл.
        print(f"\n[ImageVault] LAN mode. Bearer token (saved to data/config.json):\n"
              f"  {cfg.auth_token}\n  Open: http://{cfg.host}:{cfg.port}/?token=<token>\n")
    print(f"[ImageVault] http://{cfg.host}:{cfg.port}/")
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, log_level="info")

if __name__ == "__main__":
    main()
```

### `web/index.html`
```html
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>ImageVault</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<nav>
  <span class="logo">ImageVault</span>
  <button data-tab="volumes" class="active">Volumes</button>
  <button data-tab="gallery">Gallery</button>
  <button data-tab="jobs">Jobs <span id="jobs-badge"></span></button>
  <span class="spacer"></span>
  <span id="status-line"></span>
</nav>

<section id="tab-volumes">
  <div class="panel">
    <h3>Зарегистрировать носитель / каталог</h3>
    <input id="vol-path" placeholder="E:\ или E:\Images\References" size="50">
    <label><input type="checkbox" id="vol-marker"> записать маркер в корень диска
      (рекомендуется для сменных)</label>
    <button id="vol-register">Register</button>
  </div>
  <div id="volumes-list"></div>
</section>

<section id="tab-gallery" hidden>
  <div class="panel controls">
    <select id="f-volume"><option value="">все диски</option></select>
    <select id="f-status">
      <option value="">все статусы</option>
      <option value="ok">ok</option><option value="corrupt">corrupt</option>
      <option value="missing">missing</option>
    </select>
    <input id="f-q" placeholder="имя файла…">
    <select id="f-order">
      <option value="name">по имени</option><option value="mtime">по дате изменения</option>
      <option value="size">по размеру</option>
    </select>
    <button id="f-apply">Применить</button>
    <span id="sel-count"></span>
  </div>
  <div id="grid"></div>
  <div class="pager">
    <button id="pg-prev">←</button><span id="pg-info"></span><button id="pg-next">→</button>
  </div>
</section>

<section id="tab-jobs" hidden>
  <div class="panel">
    <button id="jobs-pause">Пауза очереди</button>
    <button id="jobs-resume">Продолжить</button>
    <span id="queue-state"></span>
  </div>
  <table id="jobs-table">
    <thead><tr><th>kind</th><th>status</th><th>progress</th><th>message / error</th>
    <th>created</th><th></th></tr></thead>
    <tbody></tbody>
  </table>
</section>

<div id="viewer" hidden>
  <div id="viewer-img-wrap"><img id="viewer-img" alt=""></div>
  <aside id="viewer-info">
    <button id="viewer-close">✕ (Esc)</button>
    <div id="viewer-meta"></div>
  </aside>
  <button id="viewer-prev" class="vnav">‹</button>
  <button id="viewer-next" class="vnav">›</button>
</div>

<script src="/static/app.js"></script>
</body>
</html>
```

### `web/style.css`
```css
* { box-sizing: border-box; }
body { margin: 0; background: #121214; color: #d8d8dc;
       font: 14px/1.45 "Segoe UI", system-ui, sans-serif; }
nav { display: flex; gap: 8px; align-items: center; padding: 10px 16px;
      background: #1b1b1f; border-bottom: 1px solid #2a2a30; position: sticky; top: 0; z-index: 5; }
.logo { font-weight: 700; color: #4da3ff; margin-right: 12px; }
.spacer { flex: 1; }
button { background: #2a2a32; color: #d8d8dc; border: 1px solid #3a3a44;
         border-radius: 6px; padding: 6px 12px; cursor: pointer; }
button:hover { background: #34343e; }
button.active { background: #4da3ff; color: #10131a; border-color: #4da3ff; }
input, select { background: #1e1e24; color: #d8d8dc; border: 1px solid #3a3a44;
                border-radius: 6px; padding: 6px 8px; }
section { padding: 16px; }
.panel { background: #1b1b1f; border: 1px solid #2a2a30; border-radius: 8px;
         padding: 12px; margin-bottom: 14px; display: flex; gap: 10px;
         align-items: center; flex-wrap: wrap; }
.panel h3 { margin: 0 8px 0 0; font-size: 14px; }
.vol-card { background: #1b1b1f; border: 1px solid #2a2a30; border-radius: 8px;
            padding: 12px; margin-bottom: 10px; }
.badge { padding: 2px 8px; border-radius: 10px; font-size: 12px; }
.badge.online { background: #14351f; color: #6fdc8c; }
.badge.offline { background: #3a1a1a; color: #ff8a8a; }
.badge.ok { background: #14351f; color: #6fdc8c; }
.badge.corrupt { background: #3a2a10; color: #ffc266; }
.badge.missing { background: #3a1a1a; color: #ff8a8a; }
.root-row { display: flex; gap: 8px; align-items: center; margin: 6px 0 0 16px; }
.muted { color: #8a8a94; font-size: 12px; }
#grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 10px; }
.cell { position: relative; background: #1b1b1f; border: 1px solid #2a2a30;
        border-radius: 8px; overflow: hidden; cursor: pointer; }
.cell img { width: 100%; aspect-ratio: 1; object-fit: cover; display: block; }
.cell .cap { padding: 4px 8px; font-size: 12px; white-space: nowrap;
             overflow: hidden; text-overflow: ellipsis; }
.cell .sel { position: absolute; top: 6px; left: 6px; width: 18px; height: 18px; }
.cell .st { position: absolute; top: 6px; right: 6px; }
.pager { display: flex; gap: 12px; align-items: center; justify-content: center; padding: 14px; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #2a2a30; font-size: 13px; }
progress { width: 120px; }
#viewer { position: fixed; inset: 0; background: rgba(8,8,10,.96); z-index: 20; display: flex; }
#viewer-img-wrap { flex: 1; overflow: hidden; display: flex;
                   align-items: center; justify-content: center; cursor: grab; }
#viewer-img { max-width: 100%; max-height: 100%; user-select: none;
              transform-origin: center center; }
#viewer-info { width: 340px; background: #17171b; border-left: 1px solid #2a2a30;
               padding: 14px; overflow-y: auto; }
#viewer-meta pre { white-space: pre-wrap; word-break: break-all; font-size: 12px; color: #a8a8b2; }
.vnav { position: fixed; top: 50%; font-size: 28px; padding: 10px 16px; opacity: .7; }
#viewer-prev { left: 10px; } #viewer-next { right: 356px; }
#status-line { color: #8a8a94; font-size: 12px; }
```

### `web/app.js`
```javascript
"use strict";
const $ = s => document.querySelector(s);
const urlToken = new URLSearchParams(location.search).get("token");
if (urlToken) { localStorage.setItem("iv_token", urlToken); history.replaceState({}, "", "/"); }

async function api(path, opts = {}) {
  const headers = opts.headers || {};
  const t = localStorage.getItem("iv_token");
  if (t) headers["Authorization"] = "Bearer " + t;
  if (opts.json) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.json); }
  let r = await fetch(path, { ...opts, headers });
  if (r.status === 401) {
    const tok = prompt("Требуется токен доступа:");
    if (tok) { localStorage.setItem("iv_token", tok); return api(path, opts); }
  }
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).message || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}
const status = m => { $("#status-line").textContent = m; };
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---------- tabs ----------
let activeTab = "volumes";
document.querySelectorAll("nav button[data-tab]").forEach(b => b.onclick = () => {
  activeTab = b.dataset.tab;
  document.querySelectorAll("nav button[data-tab]").forEach(x => x.classList.toggle("active", x === b));
  document.querySelectorAll("section").forEach(s => s.hidden = s.id !== "tab-" + activeTab);
  if (activeTab === "volumes") loadVolumes();
  if (activeTab === "gallery") loadImages();
  if (activeTab === "jobs") loadJobs();
});

// ---------- volumes ----------
async function loadVolumes() {
  const { items } = await api("/api/volumes");
  const sel = $("#f-volume");
  sel.innerHTML = '<option value="">все диски</option>' +
    items.map(v => `<option value="${v.id}">${esc(v.label || v.anchor)}</option>`).join("");
  const box = $("#volumes-list");
  box.innerHTML = "";
  for (const v of items) {
    const roots = (await api(`/api/volumes/${v.id}/roots`)).items;
    const card = document.createElement("div");
    card.className = "vol-card";
    card.innerHTML = `
      <b>${esc(v.label || "(без метки)")}</b>
      <span class="badge ${v.status}">${v.status}</span>
      <span class="muted">${esc(v.anchor || "")} · ${esc(v.fs_type || "?")} · ${esc(v.media_type || "?")}
        · serial ${esc(v.fs_serial || "?")} · marker ${v.marker_uuid ? "yes" : "no"}
        · last scan ${esc(v.last_scan_at || "никогда")}</span>
      <div class="root-row">
        <input placeholder="подкаталог (пусто = весь диск)" data-vid="${v.id}" class="root-input">
        <button data-act="addroot" data-vid="${v.id}">+ root</button>
        <button data-act="rebind" data-vid="${v.id}">Rebind…</button>
      </div>
      ${roots.map(r => `<div class="root-row">
        <code>/${esc(r.relative_path)}</code>
        <span class="muted">scan: ${esc(r.last_scan_at || "никогда")}</span>
        <button data-act="scan" data-rid="${r.id}">Scan</button></div>`).join("")}`;
    box.appendChild(card);
  }
}
$("#vol-register").onclick = async () => {
  try {
    await api("/api/volumes", { method: "POST", json: {
      path: $("#vol-path").value.trim(), create_marker: $("#vol-marker").checked } });
    status("носитель зарегистрирован"); loadVolumes();
  } catch (e) { alert(e.message); }
};
$("#volumes-list").onclick = async e => {
  const b = e.target.closest("button"); if (!b) return;
  try {
    if (b.dataset.act === "addroot") {
      const inp = document.querySelector(`.root-input[data-vid="${b.dataset.vid}"]`);
      await api(`/api/volumes/${b.dataset.vid}/roots`, { method: "POST", json: { relative_path: inp.value.trim() } });
      loadVolumes();
    } else if (b.dataset.act === "scan") {
      const { job_id } = await api(`/api/roots/${b.dataset.rid}/scan`, { method: "POST" });
      status("scan job: " + job_id.slice(0, 8));
    } else if (b.dataset.act === "rebind") {
      const p = prompt("Новый путь к этому носителю:");
      if (p) { await api(`/api/volumes/${b.dataset.vid}/rebind`, { method: "POST", json: { path: p } }); loadVolumes(); }
    }
  } catch (err) { alert(err.message); }
};

// ---------- gallery ----------
const G = { page: 1, pageSize: 60, total: 0, items: [], selection: new Set() };
async function loadImages() {
  const p = new URLSearchParams({ page: G.page, page_size: G.pageSize, order: $("#f-order").value });
  if ($("#f-volume").value) p.set("volume_id", $("#f-volume").value);
  if ($("#f-status").value) p.set("status", $("#f-status").value);
  if ($("#f-q").value.trim()) p.set("q", $("#f-q").value.trim());
  const data = await api("/api/images?" + p);
  G.items = data.items; G.total = data.total;
  const grid = $("#grid"); grid.innerHTML = "";
  for (let i = 0; i < G.items.length; i++) {
    const it = G.items[i];
    const cell = document.createElement("div");
    cell.className = "cell";
    const thumb = it.scan_status === "ok"
      ? `/api/images/${it.id}/thumbnail?v=${it.mtime_ns}` : "";
    cell.innerHTML = `
      ${thumb ? `<img loading="lazy" src="${thumb}" alt="">` : `<div style="aspect-ratio:1"></div>`}
      <input type="checkbox" class="sel" ${G.selection.has(it.id) ? "checked" : ""}>
      <span class="st badge ${it.scan_status}">${it.scan_status}${it.volume_status === "offline" ? " · offline" : ""}</span>
      <div class="cap" title="${esc(it.relative_path)}">${esc(it.filename)}</div>`;
    cell.querySelector(".sel").onclick = ev => {
      ev.stopPropagation();
      ev.target.checked ? G.selection.add(it.id) : G.selection.delete(it.id);
      $("#sel-count").textContent = G.selection.size ? `выбрано: ${G.selection.size}` : "";
    };
    cell.onclick = () => openViewer(i);
    grid.appendChild(cell);
  }
  const pages = Math.max(1, Math.ceil(G.total / G.pageSize));
  $("#pg-info").textContent = `${G.page} / ${pages} · всего ${G.total}`;
}
$("#f-apply").onclick = () => { G.page = 1; loadImages().catch(e => alert(e.message)); };
$("#pg-prev").onclick = () => { if (G.page > 1) { G.page--; loadImages(); } };
$("#pg-next").onclick = () => { if (G.page * G.pageSize < G.total) { G.page++; loadImages(); } };

// ---------- viewer ----------
const V = { idx: 0, scale: 1, tx: 0, ty: 0, drag: null };
function vTransform() {
  $("#viewer-img").style.transform = `translate(${V.tx}px,${V.ty}px) scale(${V.scale})`;
}
async function openViewer(i) {
  V.idx = i; V.scale = 1; V.tx = V.ty = 0;
  const it = G.items[i];
  $("#viewer").hidden = false;
  const img = $("#viewer-img");
  img.src = it.scan_status === "ok" && it.volume_status === "online"
    ? `/api/images/${it.id}/original` : "";
  vTransform();
  const meta = await api(`/api/images/${it.id}`);
  let exif = {};
  try { exif = JSON.parse(meta.exif_json || "{}"); } catch {}
  $("#viewer-meta").innerHTML = `
    <h3>${esc(meta.filename)}</h3>
    <p class="muted">${esc(meta.volume_label || "")} (${meta.volume_status})<br>/${esc(meta.relative_path)}</p>
    <p>${meta.width}×${meta.height} · ${esc(meta.format)} · ${esc(meta.mode)}<br>
    ${(meta.file_size / 1024).toFixed(1)} KB · orientation ${meta.orientation}<br>
    created: ${esc(meta.created_at_fs || "?")}</p>
    <h4>EXIF</h4><pre>${esc(JSON.stringify(exif, null, 2))}</pre>`;
}
function vStep(d) {
  const n = V.idx + d;
  if (n >= 0 && n < G.items.length) openViewer(n);
}
$("#viewer-close").onclick = () => { $("#viewer").hidden = true; };
$("#viewer-prev").onclick = () => vStep(-1);
$("#viewer-next").onclick = () => vStep(1);
document.addEventListener("keydown", e => {
  if ($("#viewer").hidden) return;
  if (e.key === "Escape") $("#viewer").hidden = true;
  if (e.key === "ArrowLeft") vStep(-1);
  if (e.key === "ArrowRight") vStep(1);
});
$("#viewer-img-wrap").addEventListener("wheel", e => {
  e.preventDefault();
  V.scale = Math.min(12, Math.max(0.2, V.scale * Math.pow(1.15, -e.deltaY / 100)));
  vTransform();
}, { passive: false });
$("#viewer-img-wrap").addEventListener("mousedown", e => { V.drag = { x: e.clientX - V.tx, y: e.clientY - V.ty }; });
window.addEventListener("mousemove", e => { if (V.drag) { V.tx = e.clientX - V.drag.x; V.ty = e.clientY - V.drag.y; vTransform(); } });
window.addEventListener("mouseup", () => { V.drag = null; });

// ---------- jobs ----------
async function loadJobs() {
  const { items, paused } = await api("/api/jobs?limit=100");
  $("#queue-state").textContent = paused ? "очередь на паузе" : "очередь работает";
  const tb = $("#jobs-table tbody");
  tb.innerHTML = items.map(j => `<tr>
    <td>${esc(j.kind)}</td><td><span class="badge ${j.status === "failed" ? "missing" : j.status === "completed" ? "ok" : "corrupt"}">${j.status}</span></td>
    <td><progress max="1" value="${j.progress ?? 0}"></progress></td>
    <td class="muted">${esc(j.error || j.progress_msg || "")}</td>
    <td class="muted">${esc(j.created_at)}</td>
    <td>${["pending", "running"].includes(j.status) ? `<button data-jid="${j.id}">Cancel</button>` : ""}</td>
  </tr>`).join("");
  const active = items.filter(j => ["pending", "running"].includes(j.status)).length;
  $("#jobs-badge").textContent = active ? `(${active})` : "";
}
$("#jobs-table").onclick = async e => {
  const b = e.target.closest("button"); if (!b) return;
  await api(`/api/jobs/${b.dataset.jid}/cancel`, { method: "POST" }); loadJobs();
};
$("#jobs-pause").onclick = async () => { await api("/api/jobs/pause", { method: "POST" }); loadJobs(); };
$("#jobs-resume").onclick = async () => { await api("/api/jobs/resume", { method: "POST" }); loadJobs(); };
setInterval(() => { if (activeTab === "jobs") loadJobs().catch(() => {}); }, 2000);
setInterval(async () => {
  try {
    const { items } = await api("/api/jobs?status=running&limit=50");
    $("#jobs-badge").textContent = items.length ? `(${items.length})` : "";
  } catch {}
}, 5000);

loadVolumes().catch(e => status(e.message));
```

### `tools/check_env.py`
```python
"""Проверка среды ImageVault. Запуск: python tools/check_env.py [--tree]"""
import importlib, importlib.metadata, os, shutil, sqlite3, sys
from pathlib import Path

FAIL = []
def check(name, fn, required=True):
    try:
        info = fn()
        print(f"[OK]   {name}: {info}")
    except Exception as e:
        print(f"[{'FAIL' if required else 'WARN'}] {name}: {e}")
        if required: FAIL.append(name)

def ver(pkg): return importlib.metadata.version(pkg)

check("python>=3.10", lambda: (sys.version.split()[0],
      (_ for _ in ()).throw(RuntimeError("too old")) if sys.version_info < (3, 10) else "ok")[1])
print(f"       platform: {sys.platform}")
check("sqlite>=3.35 (RETURNING)", lambda: sqlite3.sqlite_version if sqlite3.sqlite_version_info >= (3, 35)
      else (_ for _ in ()).throw(RuntimeError(sqlite3.sqlite_version)))

def sqlite_features():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
    c.execute("CREATE TABLE j(a TEXT)")
    c.execute("INSERT INTO j VALUES('x')")
    assert c.execute("UPDATE j SET a='y' WHERE a='x' RETURNING a").fetchone()
    assert c.execute("SELECT json_extract('{\"a\":1}','$.a')").fetchone()[0] == 1
    return "FTS5 + RETURNING + JSON1"
check("sqlite features", sqlite_features)

for pkg in ("fastapi", "uvicorn", "pillow", "httpx", "pydantic", "pytest"):
    check(pkg, lambda p=pkg: ver(p))

def webp():
    from PIL import features, Image
    assert features.check("webp"), "no WebP"
    assert features.check("webp_anim"), "no animated WebP"
    return f"Pillow {Image.__version__}, webp+anim"
check("Pillow WebP", webp)

check("mcp SDK (Этап 6)", lambda: ver("mcp"), required=False)
check("numpy (Этап 2)", lambda: ver("numpy"), required=False)
check("opencv (Этап 2)", lambda: ver("opencv-python-headless"), required=False)
check("ffmpeg (Этап 7)", lambda: shutil.which("ffmpeg") or (_ for _ in ()).throw(RuntimeError("not in PATH")), required=False)
check("ffprobe (Этап 7)", lambda: shutil.which("ffprobe") or (_ for _ in ()).throw(RuntimeError("not in PATH")), required=False)

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
```

### `tools/backup_db.py`
```python
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
```

### `tests/make_test_data.py`
```python
"""Генератор тестовых данных (не использует пользовательские архивы, §23).
CLI: python -m tests.make_test_data <каталог>"""
import random, shutil, sys
from pathlib import Path
from PIL import Image

def build_sample_tree(root: Path) -> Path:
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    solid = Image.new("RGB", (64, 64), (128, 64, 32))
    solid.save(root / "solid.png")
    shutil.copyfile(root / "solid.png", root / "solid_copy.png")   # побайтный дубликат
    solid.save(root / "solid.jpg", quality=95)                     # те же пиксели (DC-only)
    solid.save(root / "solid_lossless.webp", lossless=True)        # те же пиксели, другой формат
    grad = Image.linear_gradient("L").resize((256, 256)).convert("RGB")
    grad.save(root / "gradient.png")
    grad.save(root / "gradient_q40.jpg", quality=40)               # визуальный «дубликат»
    grad.resize((128, 128)).save(root / "gradient_128.png")        # другое разрешение
    o = grad.resize((120, 60))
    exif = Image.Exif(); exif[274] = 6
    o.save(root / "orient.jpg", exif=exif)                         # EXIF orientation
    a = Image.new("RGBA", (64, 64), (200, 30, 30, 128))
    a.save(root / "alpha.png")                                     # прозрачность
    f1 = Image.new("RGB", (64, 64), (220, 20, 20))
    f2 = Image.new("RGB", (64, 64), (20, 20, 220))
    f1.save(root / "anim.webp", save_all=True, append_images=[f2], duration=100, loop=0)
    rnd = random.Random(42)
    noise = Image.frombytes("RGB", (64, 64), bytes(rnd.randrange(256) for _ in range(64 * 64 * 3)))
    noise.save(root / "noise.png")
    (root / "broken.png").write_bytes((root / "solid.png").read_bytes()[:20])  # повреждённый
    return root

if __name__ == "__main__":
    print("created:", build_sample_tree(Path(sys.argv[1])))
```

### `tests/util.py`
```python
import time

def wait_idle(client, timeout=90):
    db = client.app.state.db
    t0 = time.time()
    while time.time() - t0 < timeout:
        n = db.conn().execute(
            "SELECT COUNT(*) n FROM jobs WHERE status IN ('pending','running')").fetchone()["n"]
        if n == 0:
            return
        time.sleep(0.1)
    raise AssertionError("jobs did not finish in time")

def register_and_scan(client, path):
    r = client.post("/api/volumes", json={"path": str(path), "create_marker": False})
    assert r.status_code == 200, r.text
    vid = r.json()["id"]
    r = client.post(f"/api/volumes/{vid}/roots", json={"relative_path": ""})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    r = client.post(f"/api/roots/{rid}/scan")
    assert r.status_code == 200, r.text
    wait_idle(client)
    return vid, rid

def find_image(client, filename):
    items = client.get("/api/images", params={"q": filename, "page_size": 200}).json()["items"]
    return next(i for i in items if i["filename"] == filename)
```

### `tests/conftest.py`
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from fastapi.testclient import TestClient
from app import create_app
from config import Config
from tests.make_test_data import build_sample_tree

@pytest.fixture
def cfg(tmp_path):
    c = Config(data_dir=tmp_path / "data")
    for p in (c.data_dir, c.thumbs_dir, c.logs_dir, c.backups_dir):
        p.mkdir(parents=True, exist_ok=True)
    return c

@pytest.fixture
def client(cfg):
    with TestClient(create_app(cfg)) as c:
        yield c

@pytest.fixture
def sample(tmp_path):
    return build_sample_tree(tmp_path / "library")
```

### `tests/test_volumes.py`
```python
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
    assert vm.match_identity(vm.Identity("X", fs_serial="S2", label="L"), dup) is None  # неоднозначность

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
    # Маркер пишется в якорь; на POSIX якорь = каталог → перенос каталога сохраняет идентичность.
    if sys.platform == "win32":
        pytest.skip("marker-in-dir move test is POSIX-only; on Windows use a removable disk")
    vid = client.post("/api/volumes", json={"path": str(sample), "create_marker": True}).json()["id"]
    moved = tmp_path / "moved_library"
    shutil.move(str(sample), str(moved))
    r2 = client.post("/api/volumes", json={"path": str(moved)}).json()
    assert r2["id"] == vid and r2["status"] == "online"

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
```

### `tests/test_scan.py`
```python
import os, time, uuid
from pathlib import Path
from PIL import Image
from tests.util import register_and_scan, find_image, wait_idle

def test_scan_counts(client, sample):
    register_and_scan(client, sample)
    data = client.get("/api/images", params={"page_size": 200}).json()
    assert data["total"] == 12
    st = {}
    for it in data["items"]:
        st[it["scan_status"]] = st.get(it["scan_status"], 0) + 1
    assert st.get("ok") == 11 and st.get("corrupt") == 1

def test_incremental_no_rework(client, sample):
    register_and_scan(client, sample)
    db = client.app.state.db
    jobs_before = db.conn().execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"]
    img = find_image(client, "solid.png")
    thumb = client.app.state.cfg.thumbs_dir / img["id"][:2] / (img["id"] + ".webp")
    mtime = thumb.stat().st_mtime_ns
    rid = client.get(f"/api/volumes/{img['volume_id']}/roots").json()["items"][0]["id"]
    client.post(f"/api/roots/{rid}/scan"); wait_idle(client)
    jobs_after = db.conn().execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"]
    assert jobs_after == jobs_before + 1          # только новый scan, без thumbnail-задач
    assert thumb.stat().st_mtime_ns == mtime

def test_change_invalidates(client, sample):
    register_and_scan(client, sample)
    db = client.app.state.db
    img = find_image(client, "gradient.png")
    db.conn().execute(
        "INSERT INTO analyses (id, image_id, profile, status, result_json) VALUES (?,?,?,?,?)",
        (uuid.uuid4().hex, img["id"], "description", "completed", "{}"))
    p = sample / "gradient.png"
    Image.new("RGB", (300, 200), (1, 2, 3)).save(p)
    st = p.stat(); os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    rid = client.get(f"/api/volumes/{img['volume_id']}/roots").json()["items"][0]["id"]
    client.post(f"/api/roots/{rid}/scan"); wait_idle(client)
    assert db.conn().execute("SELECT stale FROM analyses WHERE image_id=?",
                             (img["id"],)).fetchone()["stale"] == 1
    meta = client.get(f"/api/images/{img['id']}").json()
    assert (meta["width"], meta["height"]) == (300, 200)

def test_missing(client, sample):
    register_and_scan(client, sample)
    img = find_image(client, "gradient_q40.jpg")
    (sample / "gradient_q40.jpg").unlink()
    rid = client.get(f"/api/volumes/{img['volume_id']}/roots").json()["items"][0]["id"]
    client.post(f"/api/roots/{rid}/scan"); wait_idle(client)
    assert client.get(f"/api/images/{img['id']}").json()["scan_status"] == "missing"
    assert client.get(f"/api/images/{img['id']}/original").status_code == 404

def test_offline_not_deletable(client, sample):
    vid, _ = register_and_scan(client, sample)
    img = find_image(client, "solid.png")
    client.app.state.db.conn().execute("UPDATE volumes SET status='offline' WHERE id=?", (vid,))
    assert client.get(f"/api/images/{img['id']}/original").status_code == 409
    # запись не удалена, индекс сохранён
    assert client.get("/api/images").json()["total"] == 12
```

### `tests/test_thumbnails.py`
```python
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
    assert im.height > im.width  # транспонировано

def test_animated_webp_first_frame(client, sample):
    register_and_scan(client, sample)
    img = find_image(client, "anim.webp")
    im = Image.open(io.BytesIO(client.get(f"/api/images/{img['id']}/thumbnail").content)).convert("RGB")
    r, g, b = im.getpixel((im.width // 2, im.height // 2))
    assert r > 150 and b < 100  # первый кадр красный, не синий

def test_thumb_autoregenerate(client, sample):
    register_and_scan(client, sample)
    img = find_image(client, "solid.png")
    cfg = client.app.state.cfg
    (cfg.thumbs_dir / img["id"][:2] / (img["id"] + ".webp")).unlink()
    assert client.get(f"/api/images/{img['id']}/thumbnail").status_code == 200
```

### `tests/test_jobs.py`
```python
import time, uuid
from database import repository as repo
from tests.util import wait_idle

def _noop(payload, ctx):
    return {"ok": True}

def _slow(payload, ctx):
    for _ in range(400):
        ctx.checkpoint()
        time.sleep(0.05)
    return {}

def test_cancel(client):
    jm = client.app.state.jobs
    jm.register("test_slow", _slow)
    jid = jm.create("test_slow", {})
    time.sleep(0.5)
    assert client.post(f"/api/jobs/{jid}/cancel").status_code == 200
    wait_idle(client)
    assert client.get(f"/api/jobs/{jid}").json()["status"] == "cancelled"

def test_pause_resume(client):
    jm = client.app.state.jobs
    jm.register("test_noop", _noop)
    client.post("/api/jobs/pause")
    jid = jm.create("test_noop", {})
    time.sleep(1.0)
    assert client.get(f"/api/jobs/{jid}").json()["status"] == "pending"
    client.post("/api/jobs/resume")
    wait_idle(client)
    assert client.get(f"/api/jobs/{jid}").json()["status"] == "completed"

def test_crash_recovery(client):
    jm = client.app.state.jobs
    jm.register("test_noop", _noop)
    conn = client.app.state.db.conn()
    jid = uuid.uuid4().hex
    conn.execute("INSERT INTO jobs (id, kind, status, claimed_by) VALUES (?,?, 'running','dead')",
                 (jid, "test_noop"))
    jm.recover_stale()
    wait_idle(client)
    assert client.get(f"/api/jobs/{jid}").json()["status"] == "completed"

def test_unknown_kind_fails_not_hangs(client):
    jid = client.app.state.jobs.create("no_such_kind", {})
    wait_idle(client)
    j = client.get(f"/api/jobs/{jid}").json()
    assert j["status"] == "failed" and "no handler" in j["error"]
```

### `tests/test_api_auth.py`
```python
from fastapi.testclient import TestClient
from app import create_app
from config import Config

def test_auth(tmp_path):
    cfg = Config(data_dir=tmp_path / "d2", auth_token="secret")
    for p in (cfg.data_dir, cfg.thumbs_dir, cfg.logs_dir, cfg.backups_dir):
        p.mkdir(parents=True, exist_ok=True)
    with TestClient(create_app(cfg)) as c:
        assert c.get("/api/volumes").status_code == 401
        assert c.get("/api/volumes", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get("/api/volumes", headers={"Authorization": "Bearer secret"}).status_code == 200
        assert c.get("/api/volumes", headers={"Authorization": "Bearer secret",
                                              "Origin": "http://evil.example"}).status_code == 403
```

### `README.md` (кратко)
```markdown
# ImageVault (Этапы 0–1)

Локальный каталогизатор изображений. Оригиналы никогда не изменяются.

## Установка (отдельное окружение, чужие venv не трогаются)
    py -3.13 -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    python tools\check_env.py        # проверка среды; пришли вывод при FAIL

## Тесты (только синтетические данные)
    python -m pytest tests -q

## Запуск
    python app.py                    # http://127.0.0.1:8765
    python app.py --host 0.0.0.0     # LAN: токен сгенерируется и напечатается один раз

## Использование
Volumes → Register (путь к диску/каталогу) → + root → Scan → Gallery.
Маркер `.imagevault_volume.json` пишется в корень носителя только по галочке;
на системный диск — лишь с явным allow_system_marker. Маркер нужен для устойчивой
идентификации сменных дисков после смены буквы/форматирования/другого ПК.

## Бэкап БД (онлайн, WAL-safe)
    python tools\backup_db.py

## Данные
data/imagevault.db, data/thumbnails/, data/logs/, data/config.json (содержит токен — не публиковать).
```

---

## 5. Порядок проверки на твоей машине

```bat
cd ImageVault
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python tools\check_env.py
python -m pytest tests -q
python app.py
```

Демо вручную: `python -m tests.make_test_data demo_data` → в UI зарегистрируй `demo_data`, root пустой, Scan → Gallery (12 файлов, 1 corrupt) → viewer (зум колесом, перетаскивание, стрелки, Esc) → Jobs. Смена буквы диска проверяется на реальном сменном носителе (автотест этого на Windows невозможен без второго тома — это ручная приёмка по §22).

---

## 6. Отчёт по этапу (§27)

**Созданные файлы:** все перечисленные в дереве выше (~30), включая пустые `__init__.py`.
**Изменённые файлы:** нет — допущение greenfield (проверить не мог, см. §0).

**Реализовано (код):**
- Этап 0: структура, изолированный venv, конфиг, полная схема SQLite (все 17 таблиц ТЗ + FTS5, WAL, FK, индексы, `user_version`), логирование в файл+stderr без секретов, онлайн-бэкап, check_env.
- Этап 1: реестр томов (GUID/serial/marker, refresh, rebind, Online/Offline), относительные пути, мульти-roots, исключения, защита от junction-циклов, инкрементальный скан (size+mtime_ns), инвалидация fingerprints/анализа/миниатюр при изменении, missing без удаления записей, повреждённые файлы не останавливают скан, EXIF/orientation/анимированный WebP (первый кадр), WebP-миниатюры с атомарной записью и авторегенерацией, персистентная очередь (claim/heartbeat/cancel/pause/crash-recovery), Gallery+Viewer+Volumes+Jobs (тёмный UI), REST с ID-адресацией и safe_join, базовый Bearer+Origin для не-loopback.

**Зависимости:** fastapi, uvicorn, pillow, httpx, pytest (+транзитивный pydantic v2). Тяжёлого ML — ничего, GPU не используется.

**Результаты тестирования:** **не выполнялось в этой среде** — нет доступа к исполнению. Приложено 20 автотестов, покрывающих критерии приёмки Этапа 1, кроме физической смены буквы диска (ручная проверка). Статус READY будет присвоен только после твоего прогона.

**Известные ограничения:** FAT/exFAT mtime 2s; коллизия serial+label → только ручной rebind; пауза — уровень очереди; FTS создана, но не заполняется (Этап 5); маркер на системный диск заблокирован по умолчанию; POSIX-идентичность — dev-режим; токен хранится в config.json открыто (локальный файл; хеширование — улучшение позже); LAN без HTTPS — только доверенная сеть до Этапа 8.

**Карта реализации:**

| Компонент | Статус |
|---|---|
| Этап 0 (каркас, схема, среда) | CODE DELIVERED / UNVERIFIED |
| Этап 1 (Image Engine + Volume Manager) | CODE DELIVERED / UNVERIFIED |
| Этапы 2–8 | NOT IMPLEMENTED |
| KNOWN ISSUES | список ограничений выше |

**Следующий шаг:** прогони `check_env.py` и `pytest -q`, пришли вывод (особенно падения, если будут). После фактической приёмки Этапа 1 — Этап 2 (Duplicate Engine: SHA-256 потоково, канонический pixel-hash, pHash/dHash на numpy+cv2 без ImageHash, SSIM только по кандидатам, группы, UI сравнения) — без переписывания работающих модулей: точки инвалидации fingerprints уже заложены в сканер.