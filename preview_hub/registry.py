from __future__ import annotations

import fcntl
import json
import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .contracts import EnvName


class BusyError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(UTC).isoformat()


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class Registry:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        state_dir.mkdir(parents=True, exist_ok=True)
        self.path = state_dir / "state.db"
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection]:
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def migrate(self) -> None:
        with self.transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = db.execute(
                "SELECT value FROM schema_meta WHERE key='version'"
            ).fetchone()
            version = int(row[0]) if row else 0
            files = sorted((Path(__file__).parent / "migrations").glob("*.sql"))
            if version > len(files):
                raise RuntimeError("Registry schema is newer than this hub")
            for file in files:
                revision = int(file.name.split("_")[0])
                if revision > version:
                    for statement in file.read_text().split(";"):
                        if statement.strip():
                            db.execute(statement)
                    db.execute(
                        "INSERT OR REPLACE INTO schema_meta VALUES ('version', ?)",
                        (str(revision),),
                    )

    @contextmanager
    def lock(self, name: str) -> Generator[None]:
        EnvName(name)
        folder = self.state_dir / "locks"
        folder.mkdir(exist_ok=True)
        with (folder / f"{name}.lock").open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BusyError(f"Operation in progress: {name}") from exc
            try:
                self.recover(name)
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def recover(self, name: str) -> None:
        cutoff = datetime.now(UTC) - timedelta(minutes=10)
        with self.transaction() as db:
            rows = db.execute(
                "SELECT o.*,e.state AS environment_state FROM operations o JOIN environments e ON e.id=o.environment_id WHERE e.name=? AND o.status='RUNNING'",
                (name,),
            ).fetchall()
            for op in rows:
                if (
                    pid_alive(op["pid"])
                    and datetime.fromisoformat(op["heartbeat_at"]) >= cutoff
                ):
                    raise BusyError(f"Operation in progress: {name}")
                error = json.dumps(
                    {
                        "stage": {
                            "BUILDING": "build",
                            "STARTING": "start",
                            "DELETING": "delete",
                        }.get(op["environment_state"], "resolve"),
                        "service": None,
                        "message": "Operation interrupted",
                        "log_excerpt": "",
                    }
                )
                db.execute(
                    "UPDATE operations SET status='INTERRUPTED', finished_at=?, error_json=? WHERE id=?",
                    (now(), error, op["id"]),
                )
                db.execute(
                    "UPDATE environments SET state=CASE WHEN state IN ('REQUESTED','RESOLVING','BUILDING','STARTING','UPDATING') THEN 'FAILED' ELSE state END, version=version+1, updated_at=?, last_error_json=? WHERE id=?",
                    (now(), error, op["environment_id"]),
                )

    def get(
        self, name: str, db: sqlite3.Connection | None = None
    ) -> dict[str, Any] | None:
        own = db is None
        connection = db or self.connect()
        try:
            row = connection.execute(
                "SELECT * FROM environments WHERE name=? ORDER BY (state!='DELETED') DESC, id DESC LIMIT 1",
                (name,),
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["services"] = [
                dict(r)
                for r in connection.execute(
                    "SELECT * FROM environment_services WHERE environment_id=? ORDER BY service",
                    (row["id"],),
                )
            ]
            return result
        finally:
            if own:
                connection.close()

    def list(self) -> list[dict[str, Any]]:
        db = self.connect()
        try:
            return [
                dict(r) for r in db.execute("SELECT * FROM environments ORDER BY id")
            ]
        finally:
            db.close()
