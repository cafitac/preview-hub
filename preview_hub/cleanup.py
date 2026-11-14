from __future__ import annotations

import fcntl
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from .git import GitCliSource
from .lifecycle import Context
from .registry import BusyError

CHECKOUT_RETENTION = 7 * 86400
LOG_RETENTION = 14 * 86400


def _directories(root: Path, pattern: str) -> list[Path]:
    if root.is_symlink() or not root.is_dir():
        return []
    return [
        path
        for path in root.iterdir()
        if re.fullmatch(pattern, path.name)
        and path.name not in {".", ".."}
        and not path.is_symlink()
        and path.is_dir()
    ]


def cleanup(ctx: Context, *, now: float | None = None) -> dict[str, int]:
    now = time.time() if now is None else now
    registry = ctx.registry
    state = registry.state_dir
    counts = {"checkouts": 0, "web_logs": 0, "manifests": 0, "env_locks": 0}
    if isinstance(ctx.git, GitCliSource):
        for service in _directories(ctx.git.cache_dir, r"[a-zA-Z0-9_.-]+"):
            for path in _directories(service, r"[0-9a-f]{40}"):
                lock = service / f"{path.name}.lock"
                if lock.is_symlink():
                    continue
                with lock.open("a") as handle:
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        continue
                    db = registry.connect()
                    try:
                        used = db.execute(
                            "SELECT 1 FROM environment_services s JOIN environments e ON e.id=s.environment_id WHERE e.state!='DELETED' AND s.service=? AND s.commit_sha=?",
                            (service.name, path.name),
                        ).fetchone()
                        if (
                            not used
                            and not path.is_symlink()
                            and path.is_dir()
                            and path.stat().st_mtime < now - CHECKOUT_RETENTION
                        ):
                            shutil.rmtree(path)
                            counts["checkouts"] += 1
                    finally:
                        db.close()
    for path in _directories(state / "logs" / "web", r"[0-9a-f]{32}"):
        if path.stat().st_mtime < now - LOG_RETENTION:
            shutil.rmtree(path)
            counts["web_logs"] += 1
    env_pattern = r"[a-z][a-z0-9-]{1,30}"
    for path in _directories(state / "envs", env_pattern):
        try:
            with registry.lock(path.name):
                row = registry.get(path.name)
                if (
                    (row is None or row["state"] == "DELETED")
                    and not path.is_symlink()
                    and path.is_dir()
                ):
                    shutil.rmtree(path)
                    counts["manifests"] += 1
        except BusyError:
            continue
    folder = state / "locks"
    if folder.is_symlink() or not folder.is_dir():
        return counts
    for path in folder.iterdir():
        name = path.stem
        if (
            not re.fullmatch(env_pattern + r"\.lock", path.name)
            or re.fullmatch(r"build-[0-9]+", name)
            or path.is_symlink()
            or not path.is_file()
        ):
            continue
        try:
            with registry.lock(name):
                rows = [row for row in registry.list() if row["name"] == name]
                if any(row["state"] != "DELETED" for row in rows):
                    continue
                deleted = [row["deleted_at"] for row in rows]
                if rows and any(value is None for value in deleted):
                    continue
                latest = (
                    max(datetime.fromisoformat(value).timestamp() for value in deleted)
                    if rows
                    else path.stat().st_mtime
                )
                if latest < now - LOG_RETENTION:
                    path.unlink()
                    counts["env_locks"] += 1
        except BusyError:
            continue
    return counts
