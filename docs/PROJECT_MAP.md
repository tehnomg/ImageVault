# ImageVault — Project Map

## Scope
ImageVault is a local image catalog. The current implementation indexes files under registered filesystem roots, stores catalog and job state in SQLite, and generates derived WebP thumbnails. Original files remain on their source volumes. This document describes the current source tree, not the target multi-catalog architecture.

## Dependency direction
- app.py is the composition root: configuration, database, services, routes, middleware, job handlers, and application lifespan.
- API route modules obtain services through api/deps.py and delegate application behavior.
- services/catalog.py coordinates catalog operations and delegates specialized work to core modules and database/repository.py.
- core/job_manager.py coordinates worker threads and delegates persistence to database/repository.py.
- core/auth.py delegates session persistence to database/repository.py.
- database/db.py owns SQLite connections, migrations, transactions, and online backup.
- database/repository.py contains SQL-level operations.

This is a high-level map, not a complete call graph.

## Application composition
### app.py
Loads configuration, initializes logging and the database, constructs JobManager, CatalogService, and AuthService, registers scan_root and thumbnail handlers, configures FastAPI routes/middleware, and starts/stops workers through FastAPI lifespan.

### config.py
Defines configuration/defaults, loads and saves data/config.json, and provides paths for the database, thumbnails, logs, and backups. Settings include host/port, worker count, thumbnail size, symlink following, hidden-directory handling, extra exclusions, and optional authentication token.

## HTTP API
- api/deps.py — exposes application services from request.app.state.
- api/routes_auth.py — browser login, logout, and authentication status.
- api/routes_volumes.py — volume listing/registration, rebind, root listing/registration.
- api/routes_images.py — image listing/metadata, original and thumbnail responses, scan requests.
- api/routes_jobs.py — job listing/details, cancellation, queue pause/resume.

Routes should delegate business behavior rather than implement traversal or SQL workflows.

## Application service layer
### services/catalog.py
CatalogService is the application service layer used by the current Web UI and REST API. It coordinates volume registration/refresh/rebind, root registration and overlap checks, scan-job creation and duplicate-active-scan checks per root, scan and thumbnail execution, image listing/metadata, and safe resolution of original and thumbnail files.

Delegation:
- volume identity: core/volume_manager.py
- traversal/indexing: core/scanner.py
- metadata/thumbnails: core/image_loader.py
- path validation: core/paths.py
- SQL: database/repository.py

The service docstring mentions future MCP use; this source tree contains no current MCP server or MCP tool implementation.

## Core modules
- core/scanner.py — traverses one registered root, applies exclusions/link rules, detects supported images, updates metadata, and performs missing detection after a sufficiently complete walk.
- core/paths.py — path comparison keys and safe_join(); rejects absolute/drive-qualified paths, NUL, parent traversal, and resolved paths outside the supplied base.
- core/volume_manager.py — probes identity, reads/writes optional marker, matches identities, handles ambiguous matches/duplicate marker sightings, refreshes Online/Offline state, and rebinds volumes.
- core/job_manager.py — SQLite-backed background workers, handler registry, job claiming, progress/heartbeat, cooperative cancellation, queue pause/resume, startup recovery.
- core/image_loader.py — supported extensions, image metadata/EXIF/orientation, verification, WebP thumbnail generation. Animated WebP uses its first frame.
- core/auth.py — configured Bearer-token validation and browser cookie sessions. With no configured auth token, this service authorizes requests.
- core/errors.py — ServiceError and HTTP status mapping.

## Database
- database/db.py — thread-local SQLite connections, connection pragmas, WAL, sequential migrations, transaction context, online backup.
- database/repository.py — SQL operations for volumes, roots, images, jobs, settings, fingerprint/analysis state, and auth sessions.
- database/migrations/ — sequential SQL migrations tracked by PRAGMA user_version. At this revision: 0001_initial.sql and 0002_auth_sessions.sql.

The schema includes structures reserved for future workflows. Table existence is not proof of an implemented processing/UI workflow.

## Tools and tests
- tools/check_env.py — Python/SQLite/package/Pillow WebP checks and optional tool checks.
- tools/backup_db.py — SQLite online backup.
- tests/conftest.py — fixtures and test application setup.
- tests/util.py — shared helpers.
- tests/make_test_data.py — synthetic image data.
- tests/test_auth.py — authentication.
- tests/test_fixes.py — regression cases.
- tests/test_jobs.py — job lifecycle/recovery.
- tests/test_link_boundary.py — link boundaries/traversal.
- tests/test_scan.py — scanner/incremental indexing.
- tests/test_thumbnails.py — thumbnails.
- tests/test_volumes.py — identity, roots, path validation, rebind.

Tests prove only scenarios they explicitly exercise.

## Target architecture is separate
docs/ARCHITECTURE_ADDENDUM.md describes future decisions including multiple catalogs/databases, global scheduling, video, duplicate search, AI analysis, and MCP. These are not current implementation claims.
