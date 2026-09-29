CREATE TABLE environments (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL,
 state TEXT NOT NULL,
 spec_json TEXT NOT NULL,
 ttl_expires_at TEXT NOT NULL,
 version INTEGER NOT NULL DEFAULT 1,
 last_error_json TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 deleted_at TEXT
);
CREATE UNIQUE INDEX uq_env_active_name ON environments(name) WHERE state != 'DELETED';
CREATE INDEX ix_env_expiry ON environments(state, ttl_expires_at);
CREATE TABLE environment_services (
 environment_id INTEGER NOT NULL REFERENCES environments(id),
 service TEXT NOT NULL,
 repo TEXT NOT NULL,
 requested_ref TEXT NOT NULL,
 commit_sha TEXT NOT NULL,
 image TEXT NOT NULL,
 public_url TEXT,
 health TEXT,
 PRIMARY KEY(environment_id, service)
);
CREATE TABLE operations (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 environment_id INTEGER NOT NULL REFERENCES environments(id),
 kind TEXT NOT NULL,
 status TEXT NOT NULL,
 requested_by TEXT NOT NULL,
 pid INTEGER NOT NULL,
 heartbeat_at TEXT NOT NULL,
 started_at TEXT NOT NULL,
 finished_at TEXT,
 error_json TEXT
);
CREATE INDEX ix_op_env_status ON operations(environment_id, status);
