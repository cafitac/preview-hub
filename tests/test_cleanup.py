import fcntl
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from preview_hub.cleanup import CHECKOUT_RETENTION, LOG_RETENTION, cleanup
from preview_hub.cli import main
from preview_hub.git import GitCliSource
from preview_hub.registry import BusyError

NOW = 2_000_000_000.0


def directory(path, age):
    path.mkdir(parents=True, exist_ok=True)
    (path / "payload").write_text("retained data")
    os.utime(path, (NOW - age, NOW - age))
    return path


def environment(ctx, name, state, sha="a" * 40):
    stamp = datetime.fromtimestamp(NOW - LOG_RETENTION - 1, UTC).isoformat()
    with ctx.registry.transaction() as db:
        row = db.execute(
            "INSERT INTO environments(name,state,spec_json,ttl_expires_at,created_at,updated_at,deleted_at) VALUES (?,?, '{}',?,?,?,?)",
            (name, state, stamp, stamp, stamp, stamp if state == "DELETED" else None),
        )
        db.execute(
            "INSERT INTO environment_services(environment_id,service,repo,requested_ref,commit_sha,image) VALUES (?,'backend','org/backend','main',?,'image')",
            (row.lastrowid, sha),
        )


def test_checkouts(ctx, tmp_path):
    ctx.git = GitCliSource(tmp_path / "sources")
    root = ctx.git.cache_dir / "backend"
    paths = [directory(root / (c * 40), CHECKOUT_RETENTION + 1) for c in "abcd"]
    recent = directory(root / ("e" * 40), CHECKOUT_RETENTION - 1)
    ignored = directory(root / "not-a-sha", CHECKOUT_RETENTION + 1)
    target = directory(tmp_path / "outside", CHECKOUT_RETENTION + 1)
    (root / ("f" * 40)).symlink_to(target, target_is_directory=True)
    (ctx.git.cache_dir / "other").symlink_to(root, target_is_directory=True)
    environment(ctx, "active", "READY", "b" * 40)
    environment(ctx, "deleted", "DELETED", "d" * 40)
    lock = root / ("c" * 40 + ".lock")
    with lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert cleanup(ctx, now=NOW)["checkouts"] == 2
    assert not paths[0].exists() and not paths[3].exists()
    assert all(p.exists() for p in [paths[1], paths[2], recent, ignored, target])
    assert (root / ("a" * 40 + ".lock")).exists()
    assert (root / ("f" * 40)).is_symlink()


def test_logs_manifests_and_locks(ctx):
    state = ctx.registry.state_dir
    old = directory(state / "logs/web" / ("a" * 32), LOG_RETENTION + 1)
    new = directory(state / "logs/web" / ("b" * 32), LOG_RETENTION - 1)
    environment(ctx, "deleted", "DELETED")
    environment(ctx, "active", "READY")
    deleted = directory(state / "envs/deleted", 0)
    active = directory(state / "envs/active", 0)
    locks = state / "locks"
    locks.mkdir()
    for name in ("deleted", "active", "orphan", "recent", "build-0", "busy"):
        path = locks / f"{name}.lock"
        path.touch()
        age = 1 if name == "recent" else LOG_RETENTION + 1
        os.utime(path, (NOW - age, NOW - age))
    with ctx.registry.lock("busy"):
        counts = cleanup(ctx, now=NOW)
    assert counts == {"checkouts": 0, "web_logs": 1, "manifests": 1, "env_locks": 2}
    assert not old.exists() and new.exists()
    assert not deleted.exists() and active.exists()
    assert not (locks / "deleted.lock").exists()
    assert not (locks / "orphan.lock").exists()
    assert all(
        (locks / f"{name}.lock").exists()
        for name in ("active", "recent", "build-0", "busy")
    )


@pytest.mark.parametrize("replacements", [1, 2])
def test_registry_retries_replaced_inode(ctx, monkeypatch, replacements):
    original = Path.open
    opened = 0

    def replacing_open(path, *args, **kwargs):
        nonlocal opened
        handle = original(path, *args, **kwargs)
        if path.name == "retry.lock":
            opened += 1
            if opened <= replacements:
                path.unlink()
        return handle

    monkeypatch.setattr(Path, "open", replacing_open)
    if replacements == 2:
        with pytest.raises(BusyError), ctx.registry.lock("retry"):
            pytest.fail("A stale inode must not enter the critical section")
    else:
        with ctx.registry.lock("retry"):
            assert (ctx.registry.state_dir / "locks/retry.lock").exists()
    assert opened == 2


def test_gc_keeps_list_output_and_logs_counts(ctx, capsys, caplog):
    with caplog.at_level(logging.INFO, logger="preview_hub.cli"):
        assert main(["gc", "--format", "json"], ctx) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert "GC cleanup:" in caplog.text
    assert "'checkouts': 0" in caplog.text
