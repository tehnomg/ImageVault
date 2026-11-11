# Архитектура ImageVault (v0.2.0, Этапы 0–1)

## Слои
Web UI / REST / (MCP позже) → `services/CatalogService` → `core/*` → `database/*` (SQLite WAL).
Бизнес-логика не дублируется в интерфейсах. Состояние задач — только в SQLite.

## Аутентификация
- LAN включается явно (`--host` не loopback). Без токена не стартует в LAN.
- Токен печатается только в консоль (`--show-token`), хранится в `data/config.json`.
- Браузер: форма входа → `POST /api/auth/login` → HttpOnly `SameSite=Strict` cookie
  (`auth_sessions` в БД, TTL 30 дней). `<img>` несёт cookie автоматически.
- API-клиенты/MCP: `Authorization: Bearer <token>` (constant-time сравнение).
- Проверка Origin при включённой авторизации. В URL секреты не передаются.
- HTTP в LAN — только доверенная сеть; HTTPS/reverse proxy — Этап 8.

## Миграции
`database/migrations/NNNN_*.sql`, версия в `PRAGMA user_version`.
Каждая миграция — одна транзакция (BEGIN…PRAGMA…COMMIT), откат при ошибке,
нумерация без пропусков. Схема v0.1 = миграция 0001; 0002 = сессии + identity_warning.

## Идентичность носителей
Приоритет: marker UUID → Volume GUID → serial+label/fs_type.
Любая неоднозначность (в т.ч. marker) → автосвязывание запрещено, только ручной rebind.
Клон диска (маркер на двух живых маунтах) → 409 при регистрации, `identity_warning` при refresh.
Маркер пишется только по явному запросу; на системный диск — с `allow_system_marker`.

## Сканирование
- Инкрементальность: size + mtime_ns; неизменённые файлы не трогаются.
- missing проставляется ТОЛЬКО при полностью успешном обходе (`missing_check: complete`);
  ошибки доступа → фаза missing пропускается; исключённые/скрытые/reparse/циклические
  каталоги и их содержимое никогда не помечаются missing. Отмена job — до фазы missing.
- follow_symlinks=False (по умолчанию): reparse points пропускаются.
  True: обход с цикл-гардом (st_dev, st_ino); ссылки наружу тома пропускаются.
- Windows: сравнения путей регистронезависимы (path_key + COLLATE NOCASE;
  ограничение: NOCASE — ASCII-фолдинг).

## Очередь задач
Захват атомарным `UPDATE…RETURNING`; heartbeat; cancel кооперативный;
пауза — уровень очереди; восстановление `running→pending` при старте.

## Известные ограничения
FAT/exFAT mtime 2s; смена буквы диска проверяется вручную на сменном носителе;
POSIX-идентичность — dev-режим; токен в config.json открыто (локальный файл).