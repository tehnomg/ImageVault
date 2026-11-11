# Changelog

## [0.2.0] - 2026-11-11
### Added
- Cookie-сессии для браузера: /api/auth/login|logout|status, таблица auth_sessions (миграция 0002).
- Механизм миграций SQLite по PRAGMA user_version (database/migrations/, транзакционно, с откатом).
- volumes.identity_warning + детекция клона диска (один маркер на двух маунтах).
- Тесты на все исправления ревью; docs/ARCHITECTURE.md, docs/TESTING.md, отчёт этапа.
### Fixed
- LAN: миниатюры и оригиналы загружаются в <img> без Authorization (cookie-сессия).
- Scanner: missing не проставляется при неполном обходе/ошибках доступа; файлы под исключёнными каталогами не помечаются missing.
- Неоднозначный marker UUID больше не привязывается к первой записи (только ручной rebind).
- Токен входа убран из URL (форма входа + консольный вывод).
- follow_symlinks: корректный обход symlink/junction-каталогов с цикл-гардом; наружу тома — skip.
- Регистронезависимые сравнения путей на Windows (path_key + COLLATE NOCASE).
### Changed
- database/schema.sql заменён migrations/0001_initial.sql (без дублирования схемы).

## [0.1.0] - 2026-11-11
- Прототип Этапов 0–1 (только в чате, в репозиторий не публиковался).