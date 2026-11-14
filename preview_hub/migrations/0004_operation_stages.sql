CREATE TABLE operation_stages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id INTEGER NOT NULL REFERENCES operations(id),
    stage TEXT NOT NULL,
    service TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL
);
CREATE INDEX ix_stage_op ON operation_stages(operation_id);
