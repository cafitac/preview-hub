CREATE TABLE bot_comments (
    comment_id INTEGER PRIMARY KEY,
    repo TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    author TEXT NOT NULL,
    command TEXT NOT NULL,
    status TEXT NOT NULL,
    environment TEXT,
    reply_comment_id INTEGER,
    error TEXT,
    received_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX ix_bot_pr ON bot_comments(repo, pr_number);
CREATE INDEX ix_bot_status ON bot_comments(status);
CREATE TABLE bot_cursors (
    repo TEXT PRIMARY KEY,
    comments_since TEXT NOT NULL,
    closed_checked_at TEXT NOT NULL
);
