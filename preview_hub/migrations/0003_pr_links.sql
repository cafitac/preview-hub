CREATE TABLE pr_links (
    environment TEXT NOT NULL,
    environment_id INTEGER NOT NULL,
    repo TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    comment_id INTEGER,
    rendered_version INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    attempted_version INTEGER,
    retryable INTEGER NOT NULL DEFAULT 1,
    retired_comment_id INTEGER,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (environment, repo, pr_number)
);
CREATE INDEX ix_links_status ON pr_links(status);
