# Тестирование ImageVault v0.2.0

## 1. Окружение и автотесты
    py -3.13 -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    python tools\check_env.py
    python -m pytest tests -q
Все тесты используют синтетические данные во временных каталогах.
Пользовательские архивы не затрагиваются. Destructive-операций нет.

## 2. Ручной сценарий (localhost)
1. `python -m tests.make_test_data demo_data`
2. `python app.py` → http://127.0.0.1:8765
3. Volumes → Register `demo_data` → + root (пусто) → Scan.
4. Jobs: scan completed, 11 thumbnail completed; Gallery: 12 карточек, 1 corrupt.
5. Viewer: оригинал, зум колесом, перетаскивание, стрелки, Esc, EXIF.
6. Повторный Scan: новых thumbnail-задач нет (инкрементальность).
7. Удалить файл из demo_data → Scan → статус missing; оригинал недоступен (404).
8. Volumes: искусственно offline (отключить носитель) → Gallery показывает offline,
   оригинал 409; подключить → Refresh → online, пути восстановлены.
9. Сменный диск: сменить букву в Disk Management → Refresh → том опознан (GUID/маркер).

## 3. LAN-сценарий (отдельно!)
1. `python app.py --host 0.0.0.0` — токен появится в консоли (один раз).
2. Windows Firewall (админ, только частная сеть):
   `netsh advfirewall firewall add rule name="ImageVault LAN" dir=in action=allow protocol=TCP localport=8765 profile=private`
3. Второй компьютер/телефон: `http://<IP сервера>:8765/` → форма входа → токен.
4. Проверить: Gallery, миниатюры, открытие оригинала, Jobs, повторный Scan.
5. Негативные: неверный токен; Logout → данные закрыты; прямой GET /api/images без cookie → 401.
6. В access-логах uvicorn не должно быть токенов/секретов в URL.
7. HTTP допустим только в доверенной LAN; HTTPS — Этап 8.

## 4. Критерии приёмки Этапа 1
- pytest зелёный; check_env без FAIL;
- ручной сценарий и LAN-сценарий пройдены;
- смена буквы диска восстановлена на реальном сменном носителе.
Только после этого этап переводится в READY. Этап 2 — после явной приёмки.

## 4. Interpretation of test results

Automated tests use synthetic data and temporary directories. A passing suite proves only the scenarios explicitly exercised by those tests.

A passing automated suite does not by itself verify:
- behavior on every Windows filesystem;
- real removable-drive identity after drive-letter changes;
- behavior with every USB enclosure or storage controller;
- recovery from physical disk disconnection during active writes;
- performance and stability on large real-world image archives;
- safe operation with multiple simultaneously running application processes.

Report Windows-only tests separately from tests skipped on other platforms. Distinguish automated tests from manual acceptance scenarios. A manual scenario is completed only after it has actually been performed.

Historical test counts in reports refer to the test tree at the time of the report. They are not current test-suite totals.
