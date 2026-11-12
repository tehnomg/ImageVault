# ImageVault

Локальный каталогизатор изображений (Windows 10/11, Python). Оригиналы никогда не изменяются.
Статус: **Этапы 0–1, v0.2.0 — код поставлен, тесты выполняются на машине пользователя (UNVERIFIED до приёмки)**.

## Установка (отдельное окружение; WanGP/Strata/LM Studio не затрагиваются)

    py -3.13 -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    python tools\check_env.py

## Тесты (только синтетические данные)

    python -m pytest tests -q

## Запуск

    python app.py                    # http://127.0.0.1:8765
    python app.py --host 0.0.0.0     # LAN: токен печатается в консоль один раз
    python app.py --show-token       # показать токен повторно (только консоль)

В LAN-режиме откройте адрес в браузере и введите токен в форму входа.
Токен **не передаётся через URL**. Браузер работает через HttpOnly-cookie сессию,
API-клиенты — через `Authorization: Bearer <token>`.

## Использование

Volumes → Register (путь к диску/каталогу) → + root → Scan → Gallery → Jobs.
Маркер `.imagevault_volume.json` пишется в корень носителя только по галочке
(на системный диск — лишь с явным `allow_system_marker`). Маркер нужен для устойчивой
идентификации сменных дисков после смены буквы/форматирования/другого ПК.

## База данных

SQLite (WAL). Миграции применяются автоматически при старте (`database/migrations/`,
версия в `PRAGMA user_version`). Онлайн-бэкап:

    python tools\backup_db.py

## Данные

`data/imagevault.db`, `data/thumbnails/`, `data/logs/`, `data/config.json`
(содержит токен — не публиковать; каталог `data/` в .gitignore).

## Документация

- AGENTS.md — правила работы AI-агентов с проектом
- docs/PROJECT_MAP.md — карта модулей и ответственности
- docs/ARCHITECTURE.md — реализованная архитектура и ограничения
- docs/DATA_FLOWS.md — фактические потоки данных и выполнения
- docs/INVARIANTS.md — инварианты безопасности и корректности
- docs/ARCHITECTURE_ADDENDUM.md — целевая архитектура, не описание текущей реализации
- docs/TESTING.md — тестовый план, ручной и LAN-чек-листы
- docs/reports/ — исторические отчёты по этапам
- CHANGELOG.md — история изменений