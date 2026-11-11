# Этап принят: граница зарегистрированного root для symlink/junction

## 0. Важное об ограничении этого хода

Инструменты исполнения и веба в этом ходе **недоступны** (`code_interpreter` и `web_extractor` отвечают «Tool does not exists»). Поэтому я **не могу** сейчас клонировать репозиторий, запустить `pytest`, проверить CI или запушить. Патч построен против **точного снимка `main`, прочитанного в аудите** (HEAD `c541481ef`, «Update scanner.py»). **Тесты я не запускал** и не выдаю их за пройденные. Ниже — план, минимальный diff, новый тестовый файл, Windows-CI и команды; финальное условие («файл в репо + оба CI зелёные») выполняешь ты. Если вернёшь sandbox — склонирую, прогоню полный набор и дам верифицированный diff.

---

## 1. План и точный список файлов

Меняются **ровно 3 файла**, ничего больше (job_manager, SQL, alias-эвристика и прочие P2/P3 не трогаются):

| Файл | Изменение |
|---|---|
| `core/scanner.py` | 2 маленьких хелпера (`_canonical`, `_is_within`); `root_real`; шлюз границы для ссылок при `follow=True`; симметрия `follow=False`; удаление мёртвого `rel.startswith("..")`. |
| `tests/test_link_boundary.py` | **новый** — POSIX symlink + Windows junction, граница root, циклы, битые ссылки, ошибка доступа, регрессия `follow=False`. |
| `.github/workflows/main.yml` | матрица `ubuntu-latest` + `windows-latest`, Python 3.13, `fail-fast: false`. |

Как закрыты 9 требований:

1. **Граница = registered root.** `root_real = _canonical(root_abs)`, где `root_abs` — именно сканируемый root (не якорь тома).
2. **Файлы и каталоги.** Шлюз стоит **до** веток `is_dir`/`is_file` → блокирует оба типа ссылок наружу.
3. **Внутри root разрешено.** `_is_within(target, root_real)` через `commonpath` (не `startswith`, защита от `/root-evil`);inside-ссылки проходят и обходятся.
4. **Циклы/повторы сохранены.** `visited` по `(st_dev, st_ino)` цели (`st_eff = os.stat`) не тронут.
5. **Симметрия `follow=False`.** Ветка改為 `if (is_reparse or is_symlink) and not follow:` и записывает ссылку (каталог **или файл**) в `skipped_dirs` → ранее проиндексированные записи не становятся ложными missing на POSIX так же, как на Windows.
6. **Canonical Windows 3.13 без снятия префиксов.** `_canonical = os.path.normcase(os.path.realpath(p))` применяется **симметрично** к цели и корню. Префиксы `\\?\` / `\\?\UNC\` **вручную не снимаются**: `realpath` на Windows (3.8+, включая 3.13) сам приводит к согласованной форме через `GetFinalPathNameByHandleW(VOLUME_NAME_DOS)`; согласованность подтверждается **Windows-CI junction-тестом**. Если CI покажет расхождение форм (например, volume-GUID у цели без буквы диска) — правим по факту, а не наугад.
7. **Мёртвая проверка удалена.** После шлюза неб链接-записи не могут выйти за root, `rel.startswith("..")` избыточен.
8. **Тесты POSIX + Windows junction** — ниже; junction создаётся через `_winapi.CreateJunction` **без привилегий** → реально исполняется на Windows-CI.
9. **Windows job** добавлен.

---

## 2. Полный diff

### 2.1 `core/scanner.py` (применять с `--recount`; база `c541481ef`)

```diff
diff --git a/core/scanner.py b/core/scanner.py
--- a/core/scanner.py
+++ b/core/scanner.py
@@
 def _under(key: str, prefix_key: str) -> bool:
     return key == prefix_key or key.startswith(prefix_key + "/")
 
+def _canonical(path) -> str:
+    # Симметричная canonicalization цели и корня. Префиксы \\?\ / \\?\UNC\ НЕ
+    # снимаем вручную: os.path.realpath на Windows Python 3.13 сам приводит к
+    # согласованной форме; согласованность проверяется Windows-CI (junction).
+    return os.path.normcase(os.path.realpath(path))
+
+def _is_within(target: str, base: str) -> bool:
+    # Обе строки уже canonical. commonpath, а не startswith (защита от /root-evil);
+    # разные диски на Windows -> ValueError -> считаем "снаружи".
+    try:
+        return os.path.commonpath([target, base]) == base
+    except ValueError:
+        return False
+
 def scan_root(db, cfg, volume: dict, root: dict, ctx) -> dict:
@@
     data_norm = os.path.normcase(str(cfg.data_dir.resolve()))
+    root_real = _canonical(root_abs)
     stats = {"files": 0, "new": 0, "changed": 0, "corrupt": 0, "missing": 0}
@@
             attrs = getattr(st, "st_file_attributes", 0)
             is_reparse = bool(attrs & REPARSE)
             is_symlink = entry.is_symlink()
-            if is_reparse and not follow:
-                if entry.is_dir(follow_symlinks=False):
-                    skipped_dirs.append(rel_of(entry.path))
-                continue
+            is_link = is_reparse or is_symlink
+            if is_link and not follow:
+                # Симметрично POSIX symlink / Windows reparse: запоминаем ссылку
+                # (каталог или файл), чтобы ранее проиндексированные записи не
+                # становились ложными missing при follow_symlinks=False.
+                skipped_dirs.append(rel_of(entry.path))
+                continue
+            if is_link and follow:
+                rel_l = rel_of(entry.path)
+                try:
+                    target = _canonical(entry.path)
+                except (OSError, ValueError) as e:
+                    skipped_dirs.append(rel_l)
+                    log.warning("cannot resolve link %s: %s; skipped", entry.path, e)
+                    continue
+                if not _is_within(target, root_real):
+                    skipped_dirs.append(rel_l)
+                    log.warning("link escapes registered root, skipped: %s -> %s",
+                                entry.path, target)
+                    continue
             try:
                 st_eff = os.stat(entry.path) if (is_reparse or is_symlink) else st
@@
                 rel = rel_of(entry.path)
-                if rel.startswith(".."):
-                    skipped_dirs.append(rel_of(entry.path))  # symlink наружу тома
-                    continue
                 seen.add(path_key(rel))
```

### 2.2 `tests/test_link_boundary.py` (новый файл)

```diff
diff --git a/tests/test_link_boundary.py b/tests/test_link_boundary.py
new file mode 100644
--- /dev/null
+++ b/tests/test_link_boundary.py
@@ -0,0 +1 @@
+"""Граница зарегистрированного root для symlink/junction (core/scanner.py).
+
+Граница = сканируемый root (не физический том). Кроссплатформенно проверяется
+выход за пределы root; на Windows дополнительно исполняются junction-тесты
+(CreateJunction не требует привилегий). Symlink-тесты пропускаются, если создание
+ссылок недоступно (например, Windows без SeCreateSymbolicLinkPrivilege).
+"""
+import json
+import os
+
+import pytest
+from PIL import Image
+
+from tests.util import register_and_scan, rescan, wait_idle
+
+
+def _mkimg(path):
+    path.parent.mkdir(parents=True, exist_ok=True)
+    Image.new("RGB", (32, 32), (10, 120, 200)).save(path)
+
+
+def _symlink(target, link, is_dir=True):
+    try:
+        os.symlink(target, link, target_is_directory=is_dir)
+    except (OSError, NotImplementedError) as e:
+        pytest.skip(f"symlink creation unavailable on this platform: {e}")
+
+
+def _junction(target, link):
+    if os.name != "nt":
+        pytest.skip("junction is a Windows-only NTFS reparse point")
+    import _winapi
+    try:
+        _winapi.CreateJunction(str(target), str(link))
+    except (OSError, AttributeError) as e:
+        pytest.skip(f"junction creation unavailable: {e}")
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
+def test_plain_subdir_scanned(client, sample):
+    _mkimg(sample / "plain" / "p.png")
+    register_and_scan(client, sample)
+    assert _has_suffix(_rels(client), "plain/p.png")
+
+
+def test_symlink_dir_inside_root_followed(client, sample):
+    # Цель внутри root, но в исключённом dot-каталоге: единственный путь — ссылка.
+    _mkimg(sample / ".store" / "inside.png")
+    _symlink(sample / ".store", sample / "link_in")
+    client.app.state.cfg.follow_symlinks = True
+    register_and_scan(client, sample)
+    assert _has_suffix(_rels(client), "link_in/inside.png")
+
+
+def test_symlink_dir_outside_root_skipped(client, sample, tmp_path):
+    outside = tmp_path / "outside"
+    _mkimg(outside / "secret.png")
+    _symlink(outside, sample / "link_out")
+    client.app.state.cfg.follow_symlinks = True
+    register_and_scan(client, sample)
+    assert "secret.png" not in _names(client)
+    assert not _has_suffix(_rels(client), "link_out/secret.png")
+    assert len(_items(client)) == 12
+
+
+def test_symlink_file_outside_root_skipped(client, sample, tmp_path):
+    outside = tmp_path / "outside_f"
+    _mkimg(outside / "fsecret.png")
+    _symlink(outside / "fsecret.png", sample / "f_link.png", is_dir=False)
+    client.app.state.cfg.follow_symlinks = True
+    register_and_scan(client, sample)
+    names = _names(client)
+    assert "fsecret.png" not in names
+    assert "f_link.png" not in names
+
+
+def test_junction_dir_outside_root_skipped(client, sample, tmp_path):
+    outside = tmp_path / "outside_j"
+    _mkimg(outside / "jsecret.png")
+    _junction(outside, sample / "junc_out")
+    client.app.state.cfg.follow_symlinks = True
+    register_and_scan(client, sample)
+    assert "jsecret.png" not in _names(client)
+    assert not _has_suffix(_rels(client), "junc_out/jsecret.png")
+
+
+def test_junction_dir_inside_root_followed(client, sample):
+    _mkimg(sample / ".store" / "jinside.png")
+    _junction(sample / ".store", sample / "junc_in")
+    client.app.state.cfg.follow_symlinks = True
+    register_and_scan(client, sample)
+    assert _has_suffix(_rels(client), "junc_in/jinside.png")
+
+
+def test_parent_link_no_infinite_walk(client, sample):
+    _mkimg(sample / "sub" / "s.png")
+    _symlink(sample, sample / "sub" / "up")
+    client.app.state.cfg.follow_symlinks = True
+    register_and_scan(client, sample)  # wait_idle ограничит время при зацикливании
+    rels = _rels(client)
+    assert _has_suffix(rels, "sub/s.png")
+    assert not any("sub/up/" in r for r in rels)
+    assert len(_items(client)) == 13
+
+
+def test_broken_link_does_not_break_scan(client, sample):
+    _symlink(sample / "no_such_dir", sample / "broken_link")
+    client.app.state.cfg.follow_symlinks = True
+    register_and_scan(client, sample)
+    assert len(_items(client)) == 12
+
+
+def test_follow_false_no_false_missing(client, sample, tmp_path):
+    # Регрессия требования 5: записи, индексированные через ссылку при follow=True,
+    # не должны становиться missing после переключения на follow=False (POSIX+Win).
+    _mkimg(sample / ".store" / "inside.png")
+    _mkimg(sample / ".store" / "f.png")
+    _symlink(sample / ".store", sample / "link_in")
+    _symlink(sample / ".store" / "f.png", sample / "f_link_in", is_dir=False)
+    outside = tmp_path / "outside_t"
+    _mkimg(outside / "o.png")
+    _symlink(outside, sample / "link_out")
+    client.app.state.cfg.follow_symlinks = True
+    vid, _ = register_and_scan(client, sample)
+    assert _has_suffix(_rels(client), "link_in/inside.png")
+    assert "f_link_in" in _names(client)
+    assert "o.png" not in _names(client)
+    client.app.state.cfg.follow_symlinks = False
+    rescan(client, vid)
+    rows = {i["relative_path"]: i["scan_status"] for i in _items(client)}
+    assert any(r.endswith("link_in/inside.png") and s != "missing" for r, s in rows.items())
+    assert any(r.endswith("f_link_in") and s != "missing" for r, s in rows.items())
+    assert "o.png" not in _names(client)
+
+
+def test_access_error_no_false_missing(client, sample, monkeypatch):
+    import core.scanner as scanner_mod
+    _mkimg(sample / ".restricted" / "r.png")
+    _symlink(sample / ".restricted", sample / "link_r")
+    client.app.state.cfg.follow_symlinks = True
+    vid, _ = register_and_scan(client, sample)
+    assert _has_suffix(_rels(client), "link_r/r.png")
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
+    jid = rescan(client, vid)
+    job = client.get(f"/api/jobs/{jid}").json()
+    assert json.loads(job["result_json"])["missing_check"] == "skipped_incomplete_walk"
+    row = next(i for i in _items(client) if i["relative_path"].endswith("link_r/r.png"))
+    assert row["scan_status"] != "missing"
```

### 2.3 `.github/workflows/main.yml` (полная замена файла)

```yaml
name: Python CI

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    name: pytest (${{ matrix.os }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          python -m pip install -r requirements.txt
      - name: Run tests
        run: python -m pytest tests -q
```

---

## 3. Уточнение реализации после проверки Python 3.13 / Windows

При переносе патча обнаружена ещё одна важная Windows-особенность, которую исходный вариант не учитывал:

- `os.DirEntry.stat()` на Windows не гарантирует корректные `st_dev` и `st_ino`;
- текущий cycle guard использует именно эту пару для обычных каталогов;
- в результате несколько соседних каталогов могут получить одинаковую пару и часть дерева будет ошибочно пропущена.

Поэтому в итоговом изменении для Windows обычные каталоги также получают `st_eff` через `os.stat(entry.path)`. Для ссылок `os.stat()` используется на обеих платформах, чтобы получить статистику цели. Добавлен отдельный тест с двумя соседними подкаталогами — он проверяет не только ссылочную границу, но и полноценный обход нескольких ветвей на Windows.

Документация Python 3.13 указывает, что Windows `DirEntry.stat()` возвращает нулевые `st_dev`/`st_ino`; для получения этих значений требуется `os.stat()`. `os.path.realpath()` разрешает symlink и junction на Windows начиная с Python 3.8. См. [Python 3.13 os](https://docs.python.org/3.13/library/os.html) и [Python 3.13 os.path](https://docs.python.org/3.13/library/os.path.html).

## 4. Фактическое состояние внесения

Подготовлена реализация в отдельной ветке, без прямой записи в `main`:

- `core/scanner.py` — canonical boundary check по зарегистрированному root; блокировка внешних ссылок на файлы и каталоги; симметричная обработка `follow_symlinks=False`; исправлен Windows inode/device для обычных каталогов.
- `tests/test_link_boundary.py` — новый набор регрессионных тестов: обычные соседние каталоги, внутренние/внешние symlink, внешняя ссылка на файл, junction внутрь/наружу, цикл, битая ссылка, переключение follow.
- `.github/workflows/main.yml` — матрица Ubuntu + Windows, Python 3.13.

**Статус проверки:** исходники изменены, но локальный pytest и GitHub Actions ещё не запускались. Поэтому этап не считается завершённым. Сначала нужно получить полный зелёный CI на обеих ОС; если Windows job упадёт, разбирать конкретную ошибку, не отключая соответствующий тест.

Остальные P2/P3 из аудита не включены: job manager, SQL batching, пересекающиеся корни, alias эвристика, pruning и HTTPS остаются отдельными задачами.


---

# Этап P2-1: восстановление worker после ошибки опроса очереди

## Объём изменений

В отдельной ветке `fix/job-manager-claim-retry` изменены:

- `core/job_manager.py`
- `tests/test_jobs.py`

Схема SQLite, формат задач, обработчики, сканер и остальные P2/P3 не менялись.

## Что исправлено

Ранее `self.db.conn()`, `is_paused()` и `repo.claim_job()` выполнялись вне защитного блока. Любое исключение на этом участке завершало поток worker. После этого поток уже не возвращался к опросу очереди.

Теперь ошибки при проверке паузы, получении thread-local соединения и захвате задачи перехватываются в цикле worker. Поток пишет traceback в лог, ждёт и повторяет попытку:

- начальная задержка — 0,25 секунды;
- экспоненциальное увеличение;
- максимальная задержка — 5 секунд;
- после успешного опроса очереди задержка сбрасывается;
- остановка менеджера прерывает ожидание через `Event.wait()`.

Обработка самой задачи оставлена прежней. Это намеренно узкий фикс: он восстанавливает worker после ошибок опроса очереди, но не вводит общую retry-политику для бизнес-обработчиков или ошибок финализации задачи.

## Регрессионный тест

Добавлен `test_worker_recovers_after_transient_claim_error`:

1. Останавливает fixture workers, чтобы тест управлял одним потоком.
2. Подменяет `claim_job`: первый вызов выбрасывает `sqlite3.OperationalError("database is locked")`.
3. Следующий вызов выполняет исходный `claim_job`.
4. Проверяет, что задача завершилась со статусом `completed`, а захват вызывался повторно.

## Проверка и статус

Код отправлен в отдельную ветку GitHub. Локальный pytest пользователя и GitHub Actions для этой версии ещё не подтверждены. Этап нельзя считать закрытым до проверки нового теста, полного набора и CI на Ubuntu + Windows.



---

# Этап P2-2: запрет пересекающихся зарегистрированных корней

## Решение по архитектуре

Зарегистрированный root — постоянная граница каталога на томе, а не способ передать параметры одного запуска сканирования. Поэтому разные режимы сканирования не должны требовать создания вложенных roots.

- Зарегистрированные roots одного тома не могут быть равны по смыслу или находиться один внутри другого.
- Соседние независимые roots разрешены.
- Повторная регистрация того же пути возвращает существующую запись (идемпотентность).
- Выбор нескольких папок и исключения относятся к параметрам задания сканирования; это отдельная будущая функциональность.
- Инкрементальная обработка также относится к режиму сканирования. Уже существующая проверка размера и `mtime_ns` сохраняется.

## Изменения

В `services/catalog.py` добавлена проверка пересечения путей по компонентам, а не по простому строковому префиксу. Это важно для корректного различения `Photos` и `Photos-old`. На Windows сравнение использует существующий `path_key()` с casefold; на POSIX сохраняется чувствительность к регистру.

Перед проверкой путь безопасно разрешается через `safe_join`, а сохраняемое относительное представление нормализуется по разделителям и компонентам. Точный повтор остаётся идемпотентным. При попытке добавить родительский или дочерний root API возвращает конфликт HTTP 409.

Существующие записи roots в БД автоматически не удаляются и не объединяются. Это намеренно: автоматическое изменение уже созданного каталога могло бы повлиять на индексированные данные. Защита применяется к новым регистрациям; если в существующей БД уже есть пересечения, их нужно отдельно выявить и согласовать способ устранения.

## Регрессионные тесты

Добавлены проверки:
- запрет вложенного root при уже зарегистрированном родителе;
- запрет родительского root при уже зарегистрированном потомке;
- разрешение соседних roots и имён с общим текстовым префиксом;
- идемпотентность точного повторного добавления;
- корень всего тома пересекается с любым вложенным root.

## Проверка

Результаты pytest и GitHub Actions будут указаны после выполнения локальной проверки и CI для этой ветки. До этого этап не считается принятым.
