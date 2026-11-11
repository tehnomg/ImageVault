CREATE TABLE IF NOT EXISTS auth_sessions (
  id           TEXT PRIMARY KEY,
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  expires_at   TEXT NOT NULL,
  last_seen_at TEXT,
  user_agent   TEXT
);
CREATE INDEX IF NOT EXISTS ix_sessions_expires ON auth_sessions(expires_at);
ALTER TABLE volumes ADD COLUMN identity_warning TEXT;