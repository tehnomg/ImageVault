В этой сессии у меня есть Python-песочница с git — значит, тесты я могу **реально выполнить** (на Linux; Windows-специфичные случаи будут явно отмечены как непройденные по платформе). Доступа к твоему репозиторию и рабочей директории по-прежнему нет: изучаю текущую реализацию по исходникам v0.2.0 из `01-core.patch`, воссоздаю их в песочнице один в один и проверяю патч на них.

Сначала проверю SQLite и воссоздам проект (бэкенд — точная копия v0.2.0):
# ImageVault — точечное исправление границы тома для symlink/junction

## 0. Что реально сделано и в какой среде (честно)

- **Доступа к твоему репозиторию/рабочей директории у меня нет.** Патч построен против `core/scanner.py` ровно в том виде, в котором он поставлен в `01-core.patch` (v0.2.0). `git apply` откажется применяться, если твой файл отличается — тогда пришли `git diff`/содержимое, сделаю дельту.
- **Тесты действительно выполнены**, но в Linux-песочнице (Python 3.10), а не на Windows. Системный SQLite там 3.27 (старше 3.35, нет `RETURNING`), поэтому **только в песочнице** я подменил stdlib `sqlite3` на `pysqlite3` (SQLite 3.51) через служебный `iv_sqlite_shim.py`. **В поставляемый код и тесты эта подмена не входит** — на твоём Windows Python 3.13 stdlib SQLite ≥ 3.45, шим не нужен.
- Из-за нестабильной/эфемерной ФС песочницы полный FastAPI-прогон был ненадёжен, поэтому я проверял **непосредственно `scanner.scan_root`** (ту самую функцию, которую правлю) против реальной SQLite, воспроизведя все 9 сценариев. Поставляемые тесты — интеграционные (в стиле проекта); их прогон и Windows-junction остаются за тобой. Это явно отмечено ниже.
- Ничего в GitHub не публиковал; ссылок на коммиты нет. Патч + команды для коммита — ниже. **Этап 2 не начинаю.**

---

## 1. Минимальный diff (`core/scanner.py`) и объяснение каждого изменения

```diff
diff --git a/core/scanner.py b/core/scanner.py
--- a/core/scanner.py
+++ b/core/scanner.py
@@ -15,6 +15,22 @@ REPARSE, HIDDEN = 0x400, 0x2
 def _under(key: str, prefix_key: str) -> bool:
     return key == prefix_key or key.startswith(prefix_key + "/")
 
+def _canonical_real(path) -> str:
+    """Реальный путь цели в нормализованной форме (Windows: \\?\, UNC, регистр)."""
+    p = os.path.realpath(path)
+    if p.startswith("\\\\?\\UNC\\"):
+        p = "\\\\" + p[8:]
+    elif p.startswith("\\\\?\\"):
+        p = p[4:]
+    return os.path.normcase(p)
+
+def _is_within(target: str, base: str) -> bool:
+    """target/base уже канонизированы; commonpath, а не startswith (защита от /root-evil)."""
+    try:
+        return os.path.commonpath([target, base]) == base
+    except ValueError:
+        return False
+
 def scan_root(db, cfg, volume: dict, root: dict, ctx) -> dict:
@@ -29,6 +45,7 @@
     data_norm = os.path.normcase(str(cfg.data_dir.resolve()))
+    root_real = _canonical_real(root_abs)
@@ -54,11 +71,24 @@
             attrs = getattr(st, "st_file_attributes", 0)
-            is_reparse = bool(attrs & REPARSE)
+            is_reparse = bool(attrs & REPARSE) or entry.is_symlink()
             if is_reparse and not follow:
                 if entry.is_dir(follow_symlinks=False):
                     skipped_dirs.append(rel_of(entry.path))
                 continue
+            if is_reparse and follow:
+                rel_l = rel_of(entry.path)
+                try:
+                    target = _canonical_real(entry.path)
+                except (OSError, ValueError) as e:
+                    skipped_dirs.append(rel_l)
+                    log.warning("cannot resolve link %s: %s; skipped", entry.path, e)
+                    continue
+                if not _is_within(target, root_real):
+                    skipped_dirs.append(rel_l)
+                    log.warning("link escapes scanned root, skipped: %s -> %s",
+                                entry.path, target)
+                    continue
             try:
                 st_eff = os.stat(entry.path) if is_reparse else st
@@ -94,9 +124,6 @@
                 rel = rel_of(entry.path)
-                if rel.startswith(".."):
-                    skipped_dirs.append(rel_of(entry.path))  # symlink наружу тома
-                    continue
                 seen.add(path_key(rel))
```

**Пояснения по пунктам:**

1. **`_canonical_real` / `_is_within`** — проверка границы по *фактической цели*, а не по пути ссылки. `os.path.realpath` раскрывает всю цепочку symlink/junction до конечного объекта. Снятие префиксов `\\?\` и `\\?\UNC\` + `os.path.normcase` закрывают особенности Windows (разные формы представления путей, регистр букв диска). `commonpath`, а не `startswith` — иначе `/vault-evil` прошёл бы как «внутри `/vault`»; `ValueError` (разные диски) трактуется как «снаружи».
2. **`root_real = _canonical_real(root_abs)`** — граница вычисляется один раз. **Граница = фактически сканируемый зарегистрированный корень (`root_abs`)**, а не весь том. Это строже, чем «весь том», и одинаково проверяемо на Windows и POSIX (на Windows том = весь диск, и выход за пределы тома в автотестах недостижим без второго диска). Выход за пределы корня тем более гарантирует непревышение тома. Файлы в других каталогах того же тома индексируются при сканировании их собственного корня. Если ты имел в виду именно границу всего тома — это замена `root_real` на канонизированный `anchor`, одна строка; скажи, и я поменяю.
3. **`is_reparse = … or entry.is_symlink()`** — необходимое локальное дополнение: `st_file_attributes` существует только на Windows, поэтому на POSIX symlink раньше **не распознавался** как ссылка (из-за этого и защита от циклов использовала inode самой ссылки, а не цели). `entry.is_symlink()` закрывает POSIX; на Windows symlink/junction по-прежнему покрыты атрибутом `REPARSE`. Побочный положительный эффект: `st_eff` теперь следует по ссылке → цикл-гард `(st_dev, st_ino)` работает по inode цели.
4. **Шлюз границы** — для каждой ссылки при `follow=True`:.resolve конечной цели; ошибка разрешения (`OSError`/`ValueError`) → пропуск + предупреждение + `skipped_dirs`; цель вне `root_real` → пропуск + предупреждение + `skipped_dirs`. Распространяется и на каталоги, и на файлы; вложенные ссылки перепроверяются на каждом хопе; **существующая защита от циклов (`visited`) сохранена** и применяется после шлюза.
5. **Удалён мёртвый `rel.startswith("..")`** — он проверял лексический путь *самой ссылки* (всегда внутри по построению), т.е. давал ложную защиту. Заменён шлюзом выше.

**Почему `skipped_dirs`, а не `walk_errors`:** ссылки наружу/битые/неразрешимые — это *намеренный пропуск*; `skipped_dirs` защищает их поддерево от ложного `missing`, не отключая фазу missing целиком. Реальные ошибки доступа при `stat`/`scandir` по-прежнему попадают в `walk_errors` → фаза missing отключается (консервативно). Оба механизма выполняют требование «никакого ложного missing». Режим `follow_symlinks=False` не тронут.

---

## 2. Патч `03-scanner-link-boundary.patch`

Содержит правку `core/scanner.py` (выше, проверена `git apply --check -R` → rc 0) и новый файл тестов. Сохрани как `03-scanner-link-boundary.patch` (UTF-8, LF) и применяй с `--recount`.

```diff
diff --git a/core/scanner.py b/core/scanner.py
--- a/core/scanner.py
+++ b/core/scanner.py
@@ -15,6 +15,22 @@ REPARSE, HIDDEN = 0x400, 0x2
 def _under(key: str, prefix_key: str) -> bool:
     return key == prefix_key or key.startswith(prefix_key + "/")
 
+def _canonical_real(path) -> str:
+    """Реальный путь цели в нормализованной форме (Windows: \\?\, UNC, регистр)."""
+    p = os.path.realpath(path)
+    if p.startswith("\\\\?\\UNC\\"):
+        p = "\\\\" + p[8:]
+    elif p.startswith("\\\\?\\"):
+        p = p[4:]
+    return os.path.normcase(p)
+
+def _is_within(target: str, base: str) -> bool:
+    """target/base уже канонизированы; commonpath, а не startswith (защита от /root-evil)."""
+    try:
+        return os.path.commonpath([target, base]) == base
+    except ValueError:
+        return False
+
 def scan_root(db, cfg, volume: dict, root: dict, ctx) -> dict:
     conn = db.conn()
     anchor = Path(volume["anchor"])
@@ -29,6 +45,7 @@ def scan_root(db, cfg, volume: dict, root: dict, ctx) -> dict:
     excl = (DEFAULT_EXCLUDE | {n.lower() for n in cfg.extra_exclude_dirs}
             | {n.lower() for n in json.loads(root["exclusions_json"] or "[]")})
     data_norm = os.path.normcase(str(cfg.data_dir.resolve()))
+    root_real = _canonical_real(root_abs)
     stats = {"files": 0, "new": 0, "changed": 0, "corrupt": 0, "missing": 0}
     seen: set[str] = set()
     walk_errors: list[str] = []
@@ -54,11 +71,24 @@ def scan_root(db, cfg, volume: dict, root: dict, ctx) -> dict:
                 log.warning("cannot stat %s: %s", entry.path, e)
                 continue
             attrs = getattr(st, "st_file_attributes", 0)
-            is_reparse = bool(attrs & REPARSE)
+            is_reparse = bool(attrs & REPARSE) or entry.is_symlink()
             if is_reparse and not follow:
                 if entry.is_dir(follow_symlinks=False):
                     skipped_dirs.append(rel_of(entry.path))
                 continue
+            if is_reparse and follow:
+                rel_l = rel_of(entry.path)
+                try:
+                    target = _canonical_real(entry.path)
+                except (OSError, ValueError) as e:
+                    skipped_dirs.append(rel_l)
+                    log.warning("cannot resolve link %s: %s; skipped", entry.path, e)
+                    continue
+                if not _is_within(target, root_real):
+                    skipped_dirs.append(rel_l)
+                    log.warning("link escapes scanned root, skipped: %s -> %s",
+                                entry.path, target)
+                    continue
             try:
                 st_eff = os.stat(entry.path) if is_reparse else st
                 is_dir = entry.is_dir(follow_symlinks=follow)
@@ -94,9 +124,6 @@ def scan_root(db, cfg, volume: dict, root: dict, ctx) -> dict:
                 if ext not in image_loader.IMAGE_EXTS:
                     continue
                 rel = rel_of(entry.path)
-                if rel.startswith(".."):
-                    skipped_dirs.append(rel_of(entry.path))  # symlink наружу тома
-                    continue
                 seen.add(path_key(rel))
                 try:
                     _process_file(db, cfg, volume, rel, entry, st_eff, stats)
diff --git a/tests/test_link_boundary.py b/tests/test_link_boundary.py
new file mode 100644
--- /dev/null
+++ b/tests/test_link_boundary.py
@@ -0,0 +1 @@
+"""Граничные тесты symlink/junction для core/scanner.py (патч 03-scanner-link-boundary).
+
+Проверяют, что обход при follow_symlinks=True не выходит за пределы сканируемого
+зарегистрированного корня; циклы, битые ссылки и ошибки доступа безопасны;
+при follow_symlinks=False ссылки не обходятся.
+
+Граница = фактический сканируемый корень (root_abs) — строже, чем весь том, и
+кроссплатформенно проверяемо (на Windows том = весь диск, поэтому выход за пределы
+тома в автотестах недостижим без второго диска; выход за пределы корня проверяется
+на обеих платформах и тем более гарантирует непревышение тома).
+
+Junction создаётся только на Windows; на других платформах тест явно пропускается
+(skip), а не выдаётся за пройденный.
+"""
+import json
+import os
+import pytest
+from PIL import Image
+
+from tests.util import wait_idle
+
+
+def _mkimg(path):
+    path.parent.mkdir(parents=True, exist_ok=True)
+    Image.new("RGB", (32, 32), (10, 120, 200)).save(path)
+
+
+def _symlink_dir(target, link):
+    try:
+        os.symlink(target, link, target_is_directory=True)
+    except (OSError, NotImplementedError) as e:
+        pytest.skip(f"symlink creation unavailable on this platform: {e}")
+
+
+def _junction_dir(target, link):
+    if os.name != "nt":
+        pytest.skip("junction is a Windows-only NTFS reparse point; not executable here")
+    import _winapi
+    try:
+        _winapi.CreateJunction(str(target), str(link))
+    except (OSError, AttributeError) as e:
+        pytest.skip(f"junction creation unavailable: {e}")
+
+
+def _scan_sample(client, sample):
+    """Регистрирует том и сканирует ТОЛЬКО каталог sample (безопасно на Windows:
+    root вычисляется относительно якоря тома, а не как '' = весь диск)."""
+    r = client.post("/api/volumes", json={"path": str(sample), "create_marker": False})
+    assert r.status_code == 200, r.text
+    v = r.json()
+    vid, anchor = v["id"], v["anchor"]
+    root_rel = os.path.relpath(sample, anchor).replace(os.sep, "/")
+    if root_rel == ".":
+        root_rel = ""
+    r = client.post(f"/api/volumes/{vid}/roots", json={"relative_path": root_rel})
+    assert r.status_code == 200, r.text
+    rid = r.json()["id"]
+    r = client.post(f"/api/roots/{rid}/scan")
+    assert r.status_code == 200, r.text
+    wait_idle(client)
+    return vid, rid
+
+
+def _rescan(client, vid, rid):
+    r = client.post(f"/api/roots/{rid}/scan")
+    assert r.status_code == 200, r.text
+    wait_idle(client)
+    return r.json()["job_id"]
+
+
+def _items(client):
+    return client.get("/api/images", params={"page_size": 200}).json()["items"]
+
+
+def _rels(client):
+    return {i["relative_path"] for i in _items(client)}
+
+
+def _names(client):
+    return {i["filename"] for i in _items(client)}
+
+
+def _has_suffix(rels, suffix):
+    return any(r.endswith(suffix) for r in rels)
+
+
+# 1. обычный каталог внутри тома сканируется
+def test_plain_subdir_scanned(client, sample):
+    _mkimg(sample / "plain" / "p.png")
+    _scan_sample(client, sample)
+    assert _has_suffix(_rels(client), "plain/p.png")
+
+
+# 2. symlink на каталог внутри корня обходится при follow_symlinks=True
+def test_symlink_inside_root_followed(client, sample):
+    # Цель внутри корня, но в исключённом (dot) каталоге: единственный путь к файлу —
+    # через ссылку. Доказывает, что ссылка внутри границы действительно пройдена.
+    _mkimg(sample / ".store" / "inside.png")
+    _symlink_dir(sample / ".store", sample / "link_in")
+    client.app.state.cfg.follow_symlinks = True
+    _scan_sample(client, sample)
+    assert _has_suffix(_rels(client), "link_in/inside.png")
+
+
+# 3. symlink за пределы корня НЕ обходится
+def test_symlink_outside_root_skipped(client, sample, tmp_path):
+    outside = tmp_path / "outside"
+    _mkimg(outside / "secret.png")
+    _symlink_dir(outside, sample / "link_out")
+    client.app.state.cfg.follow_symlinks = True
+    _scan_sample(client, sample)
+    assert "secret.png" not in _names(client)
+    assert not _has_suffix(_rels(client), "link_out/secret.png")
+    assert len(_items(client)) == 12
+
+
+# 4. junction за пределы корня НЕ обходится (Windows)
+def test_junction_outside_root_skipped(client, sample, tmp_path):
+    outside = tmp_path / "outside_j"
+    _mkimg(outside / "jsecret.png")
+    _junction_dir(outside, sample / "junc_out")
+    client.app.state.cfg.follow_symlinks = True
+    _scan_sample(client, sample)
+    assert "jsecret.png" not in _names(client)
+    assert not _has_suffix(_rels(client), "junc_out/jsecret.png")
+
+
+# 5. ссылка на родителя не вызывает бесконечный обход
+def test_parent_link_no_infinite_walk(client, sample):
+    _mkimg(sample / "sub" / "s.png")
+    _symlink_dir(sample, sample / "sub" / "up")
+    client.app.state.cfg.follow_symlinks = True
+    _scan_sample(client, sample)  # wait_idle ограничит время при зацикливании
+    rels = _rels(client)
+    assert _has_suffix(rels, "sub/s.png")
+    assert not any("sub/up/" in r for r in rels)
+    assert len(_items(client)) == 13
+
+
+# 6. битая ссылка не прерывает сканирование
+def test_broken_link_does_not_break_scan(client, sample):
+    _symlink_dir(sample / "no_such_dir", sample / "broken_link")
+    client.app.state.cfg.follow_symlinks = True
+    _scan_sample(client, sample)
+    assert len(_items(client)) == 12
+
+
+# 7. ошибка доступа к цели ссылки не приводит к ложному missing
+def test_target_access_error_no_false_missing(client, sample, monkeypatch):
+    import core.scanner as scanner_mod
+    _mkimg(sample / ".restricted" / "r.png")
+    _symlink_dir(sample / ".restricted", sample / "link_r")
+    client.app.state.cfg.follow_symlinks = True
+    vid, rid = _scan_sample(client, sample)
+    assert _has_suffix(_rels(client), "link_r/r.png")
+
+    target_real = os.path.normcase(os.path.realpath(sample / ".restricted"))
+    real_scandir = os.scandir
+
+    def fake_scandir(p):
+        if isinstance(p, int):
+            return real_scandir(p)
+        if os.path.normcase(os.path.realpath(p)) == target_real:
+            raise PermissionError("denied")
+        return real_scandir(p)
+
+    monkeypatch.setattr(scanner_mod.os, "scandir", fake_scandir)
+    jid = _rescan(client, vid, rid)
+    job = client.get(f"/api/jobs/{jid}").json()
+    assert json.loads(job["result_json"])["missing_check"] == "skipped_incomplete_walk"
+    row = next(i for i in _items(client) if i["relative_path"].endswith("link_r/r.png"))
+    assert row["scan_status"] != "missing"
+
+
+# 8. follow_symlinks=False: ссылки не обходятся
+def test_follow_false_links_not_traversed(client, sample, tmp_path):
+    _mkimg(sample / "realdir2" / "i2.png")
+    _symlink_dir(sample / "realdir2", sample / "link_in2")
+    outside2 = tmp_path / "outside2"
+    _mkimg(outside2 / "o2.png")
+    _symlink_dir(outside2, sample / "link_out2")
+    client.app.state.cfg.follow_symlinks = False
+    vid, rid = _scan_sample(client, sample)
+    rels = _rels(client)
+    assert _has_suffix(rels, "realdir2/i2.png")
+    assert "o2.png" not in _names(client)
+    assert not any("link_in2/" in r or "link_out2/" in r for r in rels)
+    _rescan(client, vid, rid)
+    assert all(i["scan_status"] != "missing" for i in _items(client))
+
+
+# 9. файловая ссылка за пределы корня не индексируется
+def test_file_symlink_outside_not_indexed(client, sample, tmp_path):
+    outside3 = tmp_path / "outside3"
+    _mkimg(outside3 / "fsecret.png")
+    try:
+        os.symlink(outside3 / "fsecret.png", sample / "f_link.png")
+    except (OSError, NotImplementedError) as e:
+        pytest.skip(f"symlink creation unavailable on this platform: {e}")
+    client.app.state.cfg.follow_symlinks = True
+    _scan_sample(client, sample)
+    names = _names(client)
+    assert "fsecret.png" not in names
+    assert "f_link.png" not in names
```

---

## 3. Результаты реально выполненных тестов (Linux-песочница, `scan_root` + реальная SQLite)

Прогон **до** и **после** правки, одни и те же 9 сценариев:

| # | Сценарий | До правки | После правки |
|---|---|---|---|
| 1 | обычный каталог внутри тома | PASS | PASS |
| 2 | symlink внутри корня обходится (`follow=True`) | PASS | PASS |
| 3 | symlink за пределы корня не сканируется | **FAIL** (индексировал `secret.png`) | PASS |
| 4 | junction за пределы корня не сканируется | SKIP (non-Windows) | SKIP (non-Windows) |
| 5 | ссылка на родителя — без бесконечного обхода | **FAIL** (дублирование обхода) | PASS |
| 6 | битая ссылка не прерывает сканирование | PASS | PASS |
| 7 | ошибка доступа к цели — без ложного `missing` | PASS | PASS |
| 8 | `follow_symlinks=False` — ссылки не обходятся | PASS | PASS |
| 9 | файловая ссылка за пределы корня не индексируется | **FAIL** (индексировал `f_link.png`) | PASS |

Итог после правки: **8/8 исполнимых — PASS, 1 SKIP (Windows-junction), FAILS: []**. В логе видны срабатывания защиты: `link escapes scanned root, skipped: …/f_link.png -> …/outside/fsecret.png` и `missing-check skipped: 1 access errors`. Патч проверен `git apply --check -R` → rc 0 (консистентен с baseline).

## 4. Что НЕ удалось выполнить и почему

- **#4 junction** — Windows-only NTFS reparse point; песочница Linux → явный SKIP, **не выдаётся за пройденный**. Запусти на Windows.
- **Windows-формы путей** (`\\?\`, `\\?\UNC\`, регистр букв диска) — код их обрабатывает, но проверить можно только на Windows; здесь не верифицировано.
- **Сами интеграционные тесты из патча** (`tests/test_link_boundary.py`, HTTP-слой) и полный регрессионный набор — в песочнице проверялся именно `scan_root` (та же логика, те же сценарии); полный FastAPI-прогон ненадёжен из-за эфемерной ФС. Прогони у себя: `python -m pytest tests/test_link_boundary.py -q` и весь `tests/`.
- **Физическая смена буквы диска / выход на второй том** — требует реальных Windows-томов, автотестом не покрыто.

## 5. Побочное наблюдение (вне рамок этой правки, не менял)

В `core/image_loader.py::read_metadata` `im.verify()` вызывается **после** `im.getexif()`; на Pillow 9.4 это даёт `RuntimeError: verify must be called directly after open` → каждый файл помечается `corrupt`. Это **самостоятельный предсуществующий баг другого модуля**; в этот патч он не входит (ты просил точечно и не трогать другие модули). Рекомендую отдельный мини-фикс: вызывать `verify()` сразу после `open`/`seek`, до `getexif()`, либо убрать. В тесте #7 я намеренно утверждаю `scan_status != "missing"` (а не `== "ok"`), чтобы он не зависел от этой отдельной проблемы.

## 6. Применение и коммит (ты выполняешь)

```bat
git apply --recount --check 03-scanner-link-boundary.patch
git apply --recount 03-scanner-link-boundary.patch
python -m pytest tests/test_link_boundary.py -q
python -m pytest tests -q
git add core/scanner.py tests/test_link_boundary.py
git commit -m "scanner: enforce symlink/junction boundary at scanned root (fix escape via link target)"
```

Если `--check` сообщит о конфликте (твой `scanner.py` отличается от v0.2.0) — не форсируй, пришли содержимое/`git diff`, сделаю дельту.

**Останавливаюсь и жду твоей проверки.** К следующему этапу не перехожу.