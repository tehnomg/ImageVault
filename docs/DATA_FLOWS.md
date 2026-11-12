# ImageVault — Data Flows

## Scope
This document describes workflows in the current single-catalog, single-database application. SQLite stores catalog, volume/root, settings, session, and job state. Original images remain on source volumes. WebP thumbnails are derived files under the application data directory.

## 1. Startup and shutdown
1. app.py loads Config and initializes logging.
2. Database is constructed with the configured database path.
3. Database.init() creates the parent directory, enables WAL, and applies pending sequential migrations.
4. JobManager, CatalogService, and AuthService are constructed.
5. The application registers scan_root and thumbnail handlers.
6. FastAPI lifespan calls JobManager.start(), which runs recover_stale() and starts worker threads.
7. Shutdown signals workers and joins each thread with a five-second timeout.

Startup recovery changes every jobs row with status running back to pending and clears claimed_by and started_at. It does not check heartbeat age. The code does not establish a safe multi-process scheduler protocol; do not assume startup recovery is safe while another application process is still running.

## 2. Volume registration
Entry point: POST /api/volumes.

1. The route validates the body and delegates to CatalogService.register_volume().
2. The service delegates to core/volume_manager.py.
3. The manager probes identity fields available on the platform.
4. Windows probing uses volume GUID and filesystem information, including serial, label, filesystem type, and drive type.
5. Non-Windows probing uses the resolved directory, st_dev as fs_serial, and directory name as label.
6. The optional ImageVault marker is written only when create_marker is explicitly requested. Writing on the system drive additionally requires allow_system_marker.
7. Matching precedence: marker UUID, volume GUID, then filesystem serial combined with matching label or filesystem type.
8. Ambiguous matches are not automatically selected. Duplicate marker sightings across live mounts are treated as an identity conflict/warning.

The marker is optional.

## 3. Refresh and rebind
GET /api/volumes calls CatalogService.volumes(refresh=True), which delegates to volume_manager.refresh_volumes(). The manager probes available anchors, matches them to registered records, updates observed volumes as online, and marks unobserved registered volumes offline. Windows enumerates logical drives; non-Windows refresh checks registered anchors.

Offline means the source is not currently available. It does not delete catalog records.

POST /api/volumes/{vid}/rebind delegates to the volume manager. The requested path is probed and checked against the existing identity and other registered volumes. Marker mismatch requires force=true; ambiguous conflicts are rejected. Rebind updates the registered anchor/identity; it does not scan images.

## 4. Root registration
POST /api/volumes/{vid}/roots:
1. Load the registered volume.
2. Normalize the supplied relative path.
3. Resolve it using safe_join() against the volume anchor.
4. Require the target to be a directory.
5. Compare it with roots already registered for that volume.
6. Return an identical root idempotently.
7. Reject parent/child overlap with another root belonging to the same volume record.
8. Insert a non-overlapping root into SQLite.

## 5. Scan request and job creation
POST /api/roots/{root_id}/scan:
1. CatalogService loads the root and its volume.
2. The volume must be online.
3. An already queued/running scan for that root is rejected.
4. A scan_root job is inserted in SQLite with priority 10.
5. The API returns the job identifier.

The request queues work; a worker performs traversal.

## 6. Worker execution and cancellation
A worker checks queue pause, obtains its thread-local SQLite connection, and claims a pending job using an atomic UPDATE ... RETURNING operation. It selects the handler by job kind, decodes the JSON payload, and passes a JobContext. Progress, heartbeat, and final status are persisted in SQLite. Unknown job kinds fail explicitly. Queue-polling failures are logged and retried with bounded exponential delay.

Cancellation is cooperative:
- checkpoint() checks the cancellation flag and then updates heartbeat.
- progress() writes progress and then checks the cancellation flag.
- Pending jobs can be cancelled immediately; running jobs receive a cancellation request.
- A running handler stops only when it reaches a cancellation check.

The scanner calls checkpoint() at the beginning of each directory-loop iteration and progress() periodically and at completion. There is no separate checkpoint immediately before missing detection. A late cancellation request may therefore be observed only after missing detection has run.

The thumbnail handler accepts JobContext but currently does not call checkpoint() or progress(); do not claim thumbnail jobs are cooperatively cancellable.

## 7. Scan workflow
CatalogService.run_scan() loads the root and volume, verifies that the volume is online, and calls scanner.scan_root().

The scanner resolves the registered root relative to the volume anchor using safe_join(). The canonical registered root is the boundary for followed links. A link to another directory on the same volume is rejected if its target is outside that root.

Traversal uses an explicit directory stack. It applies built-in, configured, and root-specific exclusions; hidden-name rules; optional Windows hidden attributes; and application data-directory exclusion.

With follow_symlinks disabled, symbolic links and reparse points are skipped. When enabled, canonical targets must remain inside the registered root. A visited set based on (st_dev, st_ino) prevents repeated/cyclic directory traversal.

Only extensions defined in core/image_loader.py are scanned: PNG, JPG, JPEG, WebP.

For each supported file:
1. Normalize its relative path and add the path key to seen.
2. Look up an existing row by volume and relative path.
3. If status is ok and file_size and mtime_ns match, skip metadata processing.
4. Otherwise call image_loader.read_metadata().
5. Insert or update the image row.
6. Queue a thumbnail job when metadata is valid and a thumbnail is needed.

The fast path uses size and mtime_ns, not a content hash. When a changed file is processed, stored fingerprints are deleted, existing analyses are marked stale, and the old thumbnail is removed. These persistence structures do not prove duplicate/AI workflows are implemented.

A file-processing exception is logged separately. Its path was already added to seen, so it is not confused with an unseen/deleted path during missing detection.

## 8. Missing detection
Missing detection is a final scanner phase.

If directory listing/stat/access errors were recorded, missing_check is set to skipped_incomplete_walk and unseen rows are not marked missing.

If no such walk errors occurred, indexed paths under the registered root are compared with seen paths. Paths under deliberately skipped directories/links are preserved. For a skipped hidden directory beginning with a dot, the scanner also preserves the corresponding previous non-hidden name as an alias.

The scanner reports missing_check=complete when this comparison runs, or skipped_incomplete_walk when walk errors prevent it.

Cancellation nuance: there is no separate cancellation checkpoint immediately before this phase. A late cancellation request is not guaranteed to prevent missing detection.

## 9. Metadata and thumbnails
Metadata extraction reads dimensions, format, mode, EXIF values, and orientation. If no EXIF date is available, the current fallback uses st_ctime on Windows and st_mtime on non-Windows. This is a fallback timestamp, not a universal creation-time guarantee.

Thumbnail generation opens the source, uses the first frame for animated WebP, applies EXIF orientation, resizes within the configured square size, converts to RGB/RGBA, saves a temporary WebP file, and replaces the destination with os.replace(). The original is read, not rewritten.

If background thumbnail generation fails, CatalogService marks the image corrupt and returns a skipped result. The on-demand thumbnail route can also generate a missing thumbnail directly.

## 10. Image access
- GET /api/images returns a paginated/filterable listing.
- GET /api/images/{id} returns the catalog record.
- GET /api/images/{id}/original checks volume availability and missing status, resolves the relative path safely, and returns the original.
- GET /api/images/{id}/thumbnail returns a derived WebP thumbnail, generating it on demand when the image is valid and the thumbnail is absent.

An offline volume makes the original inaccessible but does not erase indexed metadata.

## 11. SQLite behavior
Database creates one connection per thread. Connections enable foreign keys, a five-second busy timeout, synchronous=NORMAL, and autocommit mode. Initialization enables WAL.

Database.tx() wraps a block in BEGIN IMMEDIATE, COMMIT, and ROLLBACK. Repository methods execute SQL on the supplied connection; callers and explicit transaction contexts determine transaction boundaries.

Migrations are sequential and tracked by PRAGMA user_version. The online backup method uses SQLite's connection backup API.

## 12. Not current workflows
Do not infer implemented video/contact-sheet, duplicate-search, AI-analysis/tagging, multi-catalog scheduling, or MCP workflows from schema tables or target-architecture documents. Verify source and tests first.
