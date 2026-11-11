CREATE TABLE IF NOT EXISTS volumes (
  id            TEXT PRIMARY KEY,
  marker_uuid   TEXT,
  volume_guid   TEXT,
  fs_serial     TEXT,
  label         TEXT,
  fs_type       TEXT,
  media_type    TEXT,
  anchor        TEXT,
  status        TEXT NOT NULL DEFAULT 'offline' CHECK(status IN ('online','offline')),
  first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  last_seen_at  TEXT,
  last_scan_at  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_volumes_marker ON volumes(marker_uuid) WHERE marker_uuid IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_volumes_guid   ON volumes(volume_guid);
CREATE INDEX IF NOT EXISTS ix_volumes_serial ON volumes(fs_serial);

CREATE TABLE IF NOT EXISTS roots (
  id              TEXT PRIMARY KEY,
  volume_id       TEXT NOT NULL REFERENCES volumes(id) ON DELETE CASCADE,
  relative_path   TEXT NOT NULL,
  exclusions_json TEXT NOT NULL DEFAULT '[]',
  enabled         INTEGER NOT NULL DEFAULT 1,
  last_scan_at    TEXT,
  UNIQUE(volume_id, relative_path)
);

CREATE TABLE IF NOT EXISTS images (
  id            TEXT PRIMARY KEY,
  volume_id     TEXT NOT NULL REFERENCES volumes(id) ON DELETE CASCADE,
  relative_path TEXT NOT NULL,
  filename      TEXT NOT NULL,
  extension     TEXT NOT NULL,
  file_size     INTEGER,
  mtime_ns      INTEGER,
  width         INTEGER,
  height        INTEGER,
  format        TEXT,
  mode          TEXT,
  exif_json     TEXT,
  orientation   INTEGER DEFAULT 1,
  created_at_fs TEXT,
  scanned_at    TEXT,
  scan_status   TEXT NOT NULL DEFAULT 'ok' CHECK(scan_status IN ('ok','corrupt','missing')),
  UNIQUE(volume_id, relative_path)
);
CREATE INDEX IF NOT EXISTS ix_images_filename ON images(filename);
CREATE INDEX IF NOT EXISTS ix_images_size     ON images(file_size);
CREATE INDEX IF NOT EXISTS ix_images_status   ON images(volume_id, scan_status);

CREATE TABLE IF NOT EXISTS fingerprints (
  image_id     TEXT PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
  sha256       TEXT,
  pixel_hash   TEXT,
  pixel_width  INTEGER,
  pixel_height INTEGER,
  pixel_mode   TEXT,
  phash        INTEGER,
  dhash        INTEGER,
  algo_version INTEGER NOT NULL DEFAULT 1,
  computed_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_fp_sha   ON fingerprints(sha256);
CREATE INDEX IF NOT EXISTS ix_fp_pixel ON fingerprints(pixel_hash);
CREATE INDEX IF NOT EXISTS ix_fp_phash ON fingerprints(phash);
CREATE INDEX IF NOT EXISTS ix_fp_dhash ON fingerprints(dhash);

CREATE TABLE IF NOT EXISTS duplicate_groups (
  id                 TEXT PRIMARY KEY,
  kind               TEXT NOT NULL CHECK(kind IN ('byte','pixel','visual')),
  params_json        TEXT,
  status             TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved','ignored')),
  preferred_image_id TEXT REFERENCES images(id) ON DELETE SET NULL,
  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at         TEXT
);
CREATE TABLE IF NOT EXISTS duplicate_members (
  group_id    TEXT NOT NULL REFERENCES duplicate_groups(id) ON DELETE CASCADE,
  image_id    TEXT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
  similarity  REAL,
  metrics_json TEXT,
  PRIMARY KEY(group_id, image_id)
);
CREATE INDEX IF NOT EXISTS ix_dm_image ON duplicate_members(image_id);

CREATE TABLE IF NOT EXISTS analyses (
  id             TEXT PRIMARY KEY,
  image_id       TEXT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
  profile        TEXT NOT NULL,
  schema_version INTEGER NOT NULL DEFAULT 1,
  model          TEXT,
  backend        TEXT,
  prompt_version TEXT,
  source_sha256  TEXT,
  status         TEXT NOT NULL CHECK(status IN ('completed','failed','uncertain')),
  result_json    TEXT,
  error          TEXT,
  stale          INTEGER NOT NULL DEFAULT 0,
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_analyses_image ON analyses(image_id, profile, created_at);

CREATE TABLE IF NOT EXISTS tags (
  id        INTEGER PRIMARY KEY,
  canonical TEXT NOT NULL UNIQUE,
  category  TEXT
);
CREATE TABLE IF NOT EXISTS tag_synonyms (
  id      INTEGER PRIMARY KEY,
  tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  synonym TEXT NOT NULL,
  lang    TEXT NOT NULL DEFAULT 'ru',
  UNIQUE(tag_id, synonym, lang)
);
CREATE INDEX IF NOT EXISTS ix_syn ON tag_synonyms(synonym);
CREATE TABLE IF NOT EXISTS image_tags (
  image_id   TEXT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
  tag_id     INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  source     TEXT NOT NULL DEFAULT 'ai' CHECK(source IN ('ai','user','import')),
  confidence REAL,
  PRIMARY KEY(image_id, tag_id)
);

CREATE TABLE IF NOT EXISTS videos (
  id                    TEXT PRIMARY KEY,
  volume_id             TEXT NOT NULL REFERENCES volumes(id) ON DELETE CASCADE,
  relative_path         TEXT NOT NULL,
  filename              TEXT NOT NULL,
  extension             TEXT NOT NULL,
  file_size             INTEGER,
  mtime_ns              INTEGER,
  duration_s            REAL,
  width                 INTEGER,
  height                INTEGER,
  fps                   REAL,
  video_codec           TEXT,
  audio_codec           TEXT,
  bitrate               INTEGER,
  audio_streams_json    TEXT,
  created_at_fs         TEXT,
  sha256                TEXT,
  sidecar_relative_path TEXT,
  index_status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK(index_status IN ('pending','indexed','failed','missing','stale')),
  scanned_at            TEXT,
  UNIQUE(volume_id, relative_path)
);
CREATE TABLE IF NOT EXISTS video_frames (
  id            TEXT PRIMARY KEY,
  video_id      TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  ts_ms         INTEGER NOT NULL,
  relative_path TEXT NOT NULL,
  width         INTEGER,
  height        INTEGER,
  kind          TEXT NOT NULL DEFAULT 'interval' CHECK(kind IN ('first','interval','scene','manual')),
  description   TEXT
);
CREATE INDEX IF NOT EXISTS ix_vf_video ON video_frames(video_id, ts_ms);
CREATE TABLE IF NOT EXISTS video_analyses (
  id             TEXT PRIMARY KEY,
  video_id       TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  frame_id       TEXT REFERENCES video_frames(id) ON DELETE CASCADE,
  profile        TEXT NOT NULL,
  model          TEXT,
  backend        TEXT,
  prompt_version TEXT,
  status         TEXT NOT NULL,
  result_json    TEXT,
  error          TEXT,
  stale          INTEGER NOT NULL DEFAULT 0,
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS jobs (
  id               TEXT PRIMARY KEY,
  kind             TEXT NOT NULL,
  payload_json     TEXT NOT NULL DEFAULT '{}',
  status           TEXT NOT NULL DEFAULT 'pending'
                   CHECK(status IN ('pending','running','completed','failed','cancelled')),
  priority         INTEGER NOT NULL DEFAULT 0,
  progress         REAL,
  progress_msg     TEXT,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  pause_requested  INTEGER NOT NULL DEFAULT 0,
  claimed_by       TEXT,
  error            TEXT,
  result_json      TEXT,
  created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  started_at       TEXT,
  heartbeat_at     TEXT,
  finished_at      TEXT
);
CREATE INDEX IF NOT EXISTS ix_jobs_claim ON jobs(status, priority DESC, created_at);

CREATE TABLE IF NOT EXISTS file_actions (
  id                TEXT PRIMARY KEY,
  image_id          TEXT REFERENCES images(id) ON DELETE SET NULL,
  video_id          TEXT REFERENCES videos(id) ON DELETE SET NULL,
  volume_id         TEXT REFERENCES volumes(id) ON DELETE SET NULL,
  action            TEXT NOT NULL CHECK(action IN
                    ('mark_delete','unmark_delete','quarantine','restore','final_delete')),
  src_relative_path TEXT NOT NULL,
  dst_relative_path TEXT,
  sha256            TEXT,
  status            TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','done','failed','cancelled')),
  actor             TEXT NOT NULL DEFAULT 'user' CHECK(actor IN ('user','api','mcp')),
  details_json      TEXT,
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  executed_at       TEXT
);
CREATE INDEX IF NOT EXISTS ix_fa_image ON file_actions(image_id, created_at);

CREATE TABLE IF NOT EXISTS settings (
  key        TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS images_fts USING fts5(
  image_id UNINDEXED,
  short_description, full_description, tags, objects, scene, style, colors, notes,
  tokenize = "unicode61 remove_diacritics 2"
);