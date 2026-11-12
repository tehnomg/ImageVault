# ImageVault — Invariants and Safety Rules

## Purpose
These rules describe behavior that must remain true when implementation changes. A change that violates one requires an explicit design decision, explanation, and regression tests.

## 1. Original files and derived data
- Scanning and metadata extraction read original files.
- Thumbnail generation reads originals and writes derived WebP files under the application data directory.
- Current catalog and thumbnail workflows do not rewrite original image contents.
- A thumbnail is derived data, not an original.

Any future move/delete/rename workflow is a separate safety-critical feature. Do not infer permission or implementation from schema alone.

## 2. Registered-root boundary
A registered root defines the filesystem area the scanner may traverse.

- A root is resolved relative to its registered volume anchor.
- Relative paths must not escape the supplied base.
- Absolute paths, drive-qualified paths, NUL characters, and parent traversal are rejected by safe_join().
- When following links, the canonical target must remain inside the canonical registered root.
- Being on the same physical volume is not sufficient to authorize traversal outside the root.

Example: if D:/Photos/Family is registered, a link to D:/Photos/Other must not be followed, even though both paths are on drive D:.

## 3. Links and cycles
- follow_symlinks defaults to false.
- When disabled, symbolic links and Windows reparse points are skipped.
- When enabled, canonical targets must remain within the registered root.
- The scanner uses a visited set based on (st_dev, st_ino) to avoid repeated/cyclic directory traversal.
- Broken/inaccessible links must not cause unsafe traversal.
- Deliberately skipped links/directories must be excluded from missing detection.

## 4. Missing detection
A catalog row must not be marked missing merely because it was not observed during an incomplete directory walk.

- Directory listing/stat/access errors cause missing detection to be skipped.
- Deliberately skipped directories and links are preserved.
- A directory renamed to a hidden name has a special previous-name preservation rule.
- Results distinguish missing_check=complete from missing_check=skipped_incomplete_walk.

Cancellation is cooperative. The scanner checks cancellation during traversal, but has no separate checkpoint immediately before missing detection. Do not promise every late cancellation request prevents that phase.

File metadata/processing errors differ from directory traversal errors. A file path is added to seen before processing, so a processing exception alone does not make it eligible for missing detection.

## 5. Volume identity
Current matching precedence:
1. ImageVault marker UUID.
2. Windows volume GUID, when available.
3. Filesystem serial combined with matching label or filesystem type, when available.

A unique match may be used. Ambiguous matches must not be selected automatically. Duplicate marker sightings across live mounts are treated as an identity conflict/warning. Marker creation is optional and requires an explicit request; writing on the system drive additionally requires explicit permission. Rebind checks identity conflicts with other registered volumes.

If identity cannot be established safely, require manual resolution. Do not guess based on drive letter alone.

## 6. Online/Offline state
- Offline means the registered source is not currently observed/available; it does not mean indexed metadata should be deleted.
- Catalog metadata can remain available while the original volume is offline.
- Access to an original file requires the volume to be online.
- Rebind is separate from scanning.
- A volume becoming offline is not equivalent to its images becoming missing.

## 7. Incremental scan heuristic
The scanner skips metadata processing when an existing row has status ok and both file_size and mtime_ns match. This is a performance heuristic, not proof of byte-for-byte identity.

When a detected change is processed, metadata/scan fields are updated, stored fingerprints are deleted, existing analyses are marked stale, the previous thumbnail is removed, and a thumbnail job may be queued when metadata is valid.

Do not describe size plus mtime as a cryptographic fingerprint.

## 8. Database integrity
- SQLite is the persistent store for current application records and job state.
- Application connections enable foreign keys.
- Migrations are sequential and tracked with PRAGMA user_version.
- Database.tx() commits or rolls back its explicit transaction.
- Repository methods use the supplied connection; do not assume every repository call automatically opens its own transaction.
- A schema table does not prove its feature is operational.

Do not rewrite an already-applied migration. Add a new sequential migration.

## 9. Job lifecycle
Current statuses: pending, running, completed, failed, cancelled.

- Job records are persisted in SQLite.
- A worker claims pending jobs atomically.
- Cancellation is cooperative and depends on handler checkpoints/progress calls.
- Queue pause prevents new claims; it does not forcibly stop a running handler.
- Unknown handler kinds fail explicitly.
- Startup currently resets every running job to pending without checking heartbeat age.

Do not claim heartbeat-timeout recovery or universal handler cancellation.

## 10. Thumbnail integrity
- Thumbnail output is derived WebP.
- Destination is replaced after temporary output is saved.
- EXIF orientation is applied to the thumbnail.
- Animated WebP currently uses its first frame.
- Thumbnail generation must not modify the source image.

## 11. Authentication
When an authentication token is configured, API clients may use Authorization: Bearer, browser clients use an HttpOnly cookie session, token comparisons use constant-time comparison, failed login attempts incur a fixed delay, and submitted tokens are not logged.

When no auth token is configured, the authentication service authorizes requests. Network exposure/startup policy is configured in app.py and must be inspected separately.

## 12. Documentation integrity
Documentation must distinguish implemented behavior, schema reserved for future use, agreed target architecture, and unverified assumptions. Never turn a proposal into an implementation claim.
