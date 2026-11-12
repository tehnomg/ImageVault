# Instructions for AI agents

## Source of truth
The current source code and tests define implemented behavior. Documentation can be stale. When source, tests, and documentation disagree, inspect the implementation, report the discrepancy, and do not silently assume the documentation is correct.

Read docs/ARCHITECTURE_ADDENDUM.md as target architecture, not as proof of current functionality. A database table, migration, API placeholder, comment, or roadmap item does not prove that a workflow is implemented.

## Reading order
For orientation, read README.md, docs/PROJECT_MAP.md, docs/ARCHITECTURE.md, docs/INVARIANTS.md, and docs/DATA_FLOWS.md.

Before changing a subsystem, inspect its source files, relevant SQL migrations, and tests. Read docs/TESTING.md before choosing or reporting test commands. Check requirements.txt and tools/check_env.py when environment compatibility matters.

## Current implementation
The current application is a single-catalog, single-SQLite-database FastAPI application. Implemented workflows include volume registration/identity matching/refresh/rebind, registered roots with overlap checks, PNG/JPEG/WebP scanning, incremental metadata extraction, missing detection after a sufficiently complete walk, SQLite-backed background jobs, WebP thumbnail generation, and Bearer-token/browser-cookie authentication when configured.

Do not describe the following as implemented without locating and testing the actual workflow: multiple catalogs or per-catalog databases, global volume registry/scheduler, video/contact sheets, duplicate search/grouping, AI analysis/tagging, MCP server/tools, destructive file operations.

## Mandatory safety constraints
- Cataloging and thumbnail generation must not modify original image files.
- Filesystem traversal must remain within the registered root.
- A followed link whose canonical target is outside the registered root must be skipped, even if it is on the same volume.
- An incomplete directory walk must not cause unseen catalog entries to be marked missing.
- Deliberately skipped paths must be protected from false missing detection.
- Ambiguous volume identity must not be resolved by guessing.
- Offline status must not be treated as deletion of indexed metadata.
- Never weaken path validation, link-boundary checks, or volume identity checks without explicit design approval and regression tests.
- Never perform destructive filesystem operations without explicit user authorization and a separately verified implementation.

When path safety or volume identity cannot be established, fail closed.

## Scanner changes
Before changing scanner behavior, inspect core/scanner.py, core/paths.py, services/catalog.py, database/repository.py, tests/test_scan.py, tests/test_fixes.py, and tests/test_link_boundary.py.

Important details:
- The followed-link boundary is the canonical registered root, not the volume anchor.
- follow_symlinks defaults to false.
- When following links, the scanner checks canonical targets and uses (st_dev, st_ino) to avoid repeated/cyclic directory traversal.
- Directory listing/stat/access errors are collected as walk errors and skip missing detection.
- A file-processing exception is logged separately; its path has already been added to seen.
- Deliberately skipped paths are protected from missing detection.
- A directory renamed to a hidden name has a special previous-name preservation rule.
- Cancellation is cooperative. There is no separate checkpoint immediately before missing detection; do not promise that every late cancellation request prevents that phase.

## Database changes
Before changing persistence, inspect database/db.py, database/repository.py, database/migrations/, and relevant tests.

SQLite is the persistent store for current application records and job state. Connections are thread-local. Foreign keys, busy timeout, and synchronous=NORMAL are configured per connection; WAL is enabled during initialization. Migrations are sequential and tracked with PRAGMA user_version. Database.tx() uses BEGIN IMMEDIATE, COMMIT, and ROLLBACK.

Do not edit an already-applied migration to change an existing schema. Add a new sequential migration. Preserve transaction boundaries and bound SQL parameters. Do not introduce a second source of truth for job state.

## Background jobs
Before changing job behavior, inspect core/job_manager.py, database/repository.py, services/catalog.py, api/routes_jobs.py, and tests/test_jobs.py.

Jobs are persisted in SQLite. Workers claim pending jobs using atomic UPDATE ... RETURNING. Cancellation is cooperative and observed only where a handler calls JobContext.checkpoint() or progress(). Queue pause prevents new claims; it does not stop a running handler. Pending jobs can be cancelled immediately. Unknown handler kinds fail explicitly.

Startup recovery currently resets every running row to pending without checking heartbeat age. Do not call this lease-based or heartbeat-timeout recovery. Do not assume every handler checks cancellation: the thumbnail handler currently does not.

## Minimal-change policy
Prefer the smallest correct change. Do not rewrite working modules for style alone, combine unrelated cleanup with a bug fix, or introduce abstractions without demonstrated need. Preserve public API behavior unless an API change is part of the task. Explain schema/data migrations before proposing them. Separate a required redesign from an immediate fix.

## Verification and reporting
After a code change, run narrow relevant tests and the full suite when practical. Report exact commands, actual results, skips, and warnings. Distinguish automated tests from manual acceptance checks. Do not claim POSIX tests verify Windows-specific behavior or synthetic filesystem tests verify real removable-drive behavior.

For non-trivial work, report the problem, inspected files, root cause, minimal change, risks, tests, and documentation updates. Never report an unexecuted test as passed, an uncommitted change as committed, or a planned feature as implemented.

## Documentation maintenance
Update documentation in the same change when modifying a safety invariant, data flow, public API contract, schema/migration, job lifecycle, volume identity rule, or module responsibility. Keep implemented behavior, reserved schema, and target architecture explicitly separate.
