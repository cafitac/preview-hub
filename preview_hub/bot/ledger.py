from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from preview_hub.registry import Registry

EPOCH = "1970-01-01T00:00:00+00:00"


class Ledger:
    def __init__(self, registry: Registry):
        self.registry = registry
        # Best-effort reply state: at most three POST attempts per process.
        # Restarting loses bodies and retry budgets; unacknowledged replies may repeat.
        self.initial_replies: dict[int, str] = {}
        self.attempts: dict[int, int] = {}
        self.retry_at: dict[int, float] = {}

    def receive(
        self,
        comment_id: int,
        repo: str,
        number: int,
        author: str,
        command: str,
        now: str,
    ) -> bool:
        with self.registry.transaction() as db:
            return (
                db.execute(
                    "INSERT OR IGNORE INTO bot_comments(comment_id,repo,pr_number,author,command,status,received_at) VALUES (?,?,?,?,?,?,?)",
                    (comment_id, repo, number, author, command, "RECEIVED", now),
                ).rowcount
                == 1
            )

    def running(self, comment_id: int, environment: str, command: str) -> None:
        with self.registry.transaction() as db:
            db.execute(
                "UPDATE bot_comments SET status='RUNNING',environment=?,command=? WHERE comment_id=?",
                (environment, command, comment_id),
            )

    def finish(
        self,
        comment_id: int,
        status: str,
        reply: str,
        now: str,
        error: str | None = None,
        environment: str | None = None,
    ) -> None:
        with self.registry.transaction() as db:
            db.execute(
                "UPDATE bot_comments SET status=?,finished_at=?,error=?,environment=COALESCE(?,environment) WHERE comment_id=?",
                (status, now, error, environment, comment_id),
            )
        self.initial_replies[comment_id] = reply

    def rows(self, statuses: tuple[str, ...]) -> list[dict[str, Any]]:
        with self.registry.transaction() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM bot_comments WHERE status IN ("
                    + ",".join("?" for _ in statuses)
                    + ") ORDER BY comment_id",
                    statuses,
                )
            ]

    def claim_reply(self, comment_id: int, now: float) -> bool:
        if (
            self.attempts.get(comment_id, 0) >= 3
            or self.retry_at.get(comment_id, 0) > now
        ):
            return False
        self.attempts[comment_id] = self.attempts.get(comment_id, 0) + 1
        return True

    def defer_reply(self, comment_id: int, retry_at: float, attempted: bool) -> None:
        self.retry_at[comment_id] = retry_at
        if not attempted:
            self.attempts[comment_id] -= 1

    def replied(self, comment_id: int, reply_id: int) -> None:
        with self.registry.transaction() as db:
            db.execute(
                "UPDATE bot_comments SET reply_comment_id=? WHERE comment_id=?",
                (reply_id, comment_id),
            )

    def contains(self, comment_id: int) -> bool:
        with self.registry.transaction() as db:
            return (
                db.execute(
                    "SELECT 1 FROM bot_comments WHERE comment_id=?", (comment_id,)
                ).fetchone()
                is not None
            )

    def has_cursor(self, repo: str) -> bool:
        with self.registry.transaction() as db:
            return (
                db.execute("SELECT 1 FROM bot_cursors WHERE repo=?", (repo,)).fetchone()
                is not None
            )

    def cursor(self, repo: str, start: str | None = None) -> tuple[str, str]:
        start = start or datetime.now(UTC).isoformat()
        with self.registry.transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO bot_cursors VALUES (?,?,?)",
                (repo, start, start),
            )
            row = db.execute(
                "SELECT comments_since,closed_checked_at FROM bot_cursors WHERE repo=?",
                (repo,),
            ).fetchone()
            assert row is not None
            return row[0], row[1]

    def advance(
        self, repo: str, *, comments: str | None = None, closed: str | None = None
    ) -> None:
        with self.registry.transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO bot_cursors VALUES (?,?,?)", (repo, EPOCH, EPOCH)
            )
            if comments is not None:
                db.execute(
                    "UPDATE bot_cursors SET comments_since=? WHERE repo=?",
                    (comments, repo),
                )
            if closed is not None:
                db.execute(
                    "UPDATE bot_cursors SET closed_checked_at=? WHERE repo=?",
                    (closed, repo),
                )


def overlap(value: str) -> str:
    return (datetime.fromisoformat(value) - timedelta(seconds=60)).isoformat()
