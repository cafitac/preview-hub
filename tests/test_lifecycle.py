import json
import os
from dataclasses import replace

import pytest

from preview_hub.cli import descriptor, main
from preview_hub.contracts import CompositionSpec, EnvName, InvalidInput, validate
from preview_hub.lifecycle import (
    CreateEnvironment,
    DeleteEnvironment,
    DescribeEnvironment,
    ExpireEnvironments,
    OperationFailed,
    UpdateEnvironment,
)
from preview_hub.registry import BusyError, Registry


def spec(name="feat-x", **refs):
    return CompositionSpec(EnvName(name), refs)


def test_create_pin_immutability_update_and_delete(ctx):
    first = CreateEnvironment(ctx).execute(spec())
    assert first["state"] == "READY"
    assert first["version"] == 5
    ctx.git.sha = "b" * 40
    assert CreateEnvironment(ctx).execute(spec()) == first
    assert ctx.git.resolutions == 1
    assert (
        DescribeEnvironment(ctx).execute("feat-x")["services"][0]["commit_sha"]
        == "a" * 40
    )
    with pytest.raises(InvalidInput):
        CreateEnvironment(ctx).execute(spec(backend="other"))
    updated = UpdateEnvironment(ctx).execute("feat-x", {"backend": "other"})
    assert updated["services"][0]["commit_sha"] == "b" * 40
    assert updated["state"] == "READY"
    result = DeleteEnvironment(ctx).execute("feat-x")
    assert result["state"] == "DELETED"
    assert DeleteEnvironment(ctx).execute("feat-x") == result
    assert DeleteEnvironment(ctx).execute("unknown") is None
    assert CreateEnvironment(ctx).execute(spec())["id"] != first["id"]


@pytest.mark.parametrize("stage", ["resolve", "build", "start", "health"])
def test_failure_stages(ctx, stage):
    if stage == "resolve":
        ctx.git.fail = True
    else:
        ctx.runner.fail_at = stage
    with pytest.raises(OperationFailed) as error:
        CreateEnvironment(ctx).execute(spec())
    assert error.value.failure.stage == stage
    env = ctx.registry.get("feat-x")
    assert env["state"] == "FAILED"
    assert json.loads(env["last_error_json"])["stage"] == stage
    with ctx.registry.connect() as db:
        assert db.execute("SELECT status FROM operations").fetchone()[0] == "FAILED"
    ctx.git.fail = False
    ctx.runner.fail_at = None
    assert (
        UpdateEnvironment(ctx).execute("feat-x", {"backend": "main"})["state"]
        == "READY"
    )


def test_delete_failure_retry_isolation_and_expiry(ctx):
    CreateEnvironment(ctx).execute(spec())
    CreateEnvironment(ctx).execute(spec("feat-y"))
    ctx.runner.fail_at = "delete"
    with pytest.raises(OperationFailed):
        DeleteEnvironment(ctx).execute("feat-x")
    assert ctx.registry.get("feat-x")["state"] == "DELETING"
    ctx.runner.fail_at = None
    assert ExpireEnvironments(ctx).execute() == ["feat-x"]
    assert not ctx.runner.inventory("feat-y").empty
    with ctx.registry.transaction() as db:
        db.execute(
            "UPDATE environments SET ttl_expires_at='2000-01-01T00:00:00+00:00' WHERE name='feat-y'"
        )
    assert ExpireEnvironments(ctx).execute() == ["feat-y"]


@pytest.mark.parametrize(
    "pid,heartbeat",
    [
        (99999999, "2999-01-01T00:00:00+00:00"),
        (os.getpid(), "2000-01-01T00:00:00+00:00"),
    ],
)
def test_stale_recovery(ctx, pid, heartbeat):
    CreateEnvironment(ctx).execute(spec())
    with ctx.registry.transaction() as db:
        db.execute(
            "UPDATE operations SET status='RUNNING',pid=?,heartbeat_at=?",
            (pid, heartbeat),
        )
        db.execute("UPDATE environments SET state='BUILDING'")
    assert DescribeEnvironment(ctx).execute("feat-x")["state"] == "FAILED"
    with ctx.registry.connect() as db:
        assert (
            db.execute("SELECT status FROM operations").fetchone()[0] == "INTERRUPTED"
        )


def test_busy_capacity_disk_and_cli_exit_codes(ctx, capsys):
    with ctx.registry.lock("feat-x"):
        assert main(["up", "feat-x"], ctx) == 3
        with pytest.raises(BusyError):
            DescribeEnvironment(ctx).execute("feat-x")
    ctx.catalog = replace(ctx.catalog, max_environments=1)
    assert main(["up", "feat-x", "--format", "json"], ctx) == 0
    assert main(["up", "feat-y"], ctx) == 4
    assert main(["up", "Bad"], ctx) == 2
    ctx.free_space = lambda: 0
    assert main(["update", "feat-x", "--set", "backend=main"], ctx) == 4
    assert main(["up", "feat-x"], ctx) == 0
    ctx.free_space = lambda: 10 * 1024**3
    ctx.runner.fail_at = "build"
    ctx.git.sha = "c" * 40
    assert main(["update", "feat-x", "--set", "backend=next"], ctx) == 5


def test_descriptor_and_migration(ctx):
    env = CreateEnvironment(ctx).execute(spec())
    validate("environment-descriptor", descriptor(env, ctx.catalog.public_url_template))
    Registry(ctx.registry.state_dir)
    with ctx.registry.connect() as db:
        assert (
            db.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()[
                0
            ]
            == "3"
        )
        assert (
            "WHERE state != 'DELETED'"
            in db.execute(
                "SELECT sql FROM sqlite_master WHERE name='uq_env_active_name'"
            ).fetchone()[0]
        )


def test_unchanged_update_does_not_build(ctx):
    CreateEnvironment(ctx).execute(spec())
    UpdateEnvironment(ctx).execute("feat-x", {"backend": "main"})
    assert len(ctx.runner.builds) == 1
    assert ctx.runner.plans["feat-x"].services[0].changed is False


def test_live_operation_is_not_stolen(ctx):
    CreateEnvironment(ctx).execute(spec())
    with ctx.registry.transaction() as db:
        db.execute("UPDATE operations SET status='RUNNING'")
    with pytest.raises(BusyError):
        DescribeEnvironment(ctx).execute("feat-x")


def test_failed_build_retry_rebuilds_same_pin(ctx):
    ctx.runner.fail_at = "build"
    with pytest.raises(OperationFailed):
        CreateEnvironment(ctx).execute(spec())
    assert not ctx.runner.images
    ctx.runner.fail_at = None
    UpdateEnvironment(ctx).execute("feat-x", {"backend": "main"})
    assert ctx.runner.images == {"phub/backend:aaaaaaaaaaaa"}
    assert ctx.runner.plans["feat-x"].services[0].changed


def test_gc_keeps_active_images_and_three_recent(ctx):
    CreateEnvironment(ctx).execute(spec())
    for digit in "bcdef":
        ctx.runner.build(
            "backend",
            digit * 40,
            ctx.registry.state_dir,
            ctx.git.manifests["org/backend"],
        )
    assert main(["gc"], ctx) == 0
    assert ctx.runner.images == {f"phub/backend:{digit * 12}" for digit in "adef"}


def test_cli_formats_commands_and_expiry_busy(ctx, capsys, tmp_path):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec().as_dict()))
    assert main(["up", "-f", str(path), "--format", "descriptor"], ctx) == 0
    validate("environment-descriptor", json.loads(capsys.readouterr().out))
    assert main(["status", "feat-x", "--format", "json"], ctx) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "READY"
    assert main(["list"], ctx) == 0
    assert main(["logs", "feat-x", "backend", "--tail", "5"], ctx) == 0
    with ctx.registry.transaction() as db:
        db.execute("UPDATE environments SET ttl_expires_at='2000-01-01T00:00:00+00:00'")
    with ctx.registry.lock("feat-x"):
        assert ExpireEnvironments(ctx).execute() == []
    assert main(["down", "feat-x"], ctx) == 0


def test_capacity_is_atomic_between_different_environment_locks(ctx):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from preview_hub.lifecycle import CapacityError

    barrier = Barrier(2)
    ctx.catalog = replace(ctx.catalog, max_environments=1)

    def space():
        barrier.wait(timeout=5)
        return 10 * 1024**3

    ctx.free_space = space

    def create(name):
        try:
            return CreateEnvironment(ctx).execute(spec(name))["state"]
        except CapacityError:
            return "CAPACITY"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, ["feat-x", "feat-y"])) == ["CAPACITY", "READY"]
    assert len(ctx.registry.list()) == 1


def test_external_work_never_holds_sqlite_write_transaction(ctx):
    original = ctx.runner.build

    def build(service, commit, source, manifest):
        with ctx.registry.transaction() as db:
            assert db.execute("SELECT count(*) FROM environments").fetchone()[0] == 1
        return original(service, commit, source, manifest)

    ctx.runner.build = build
    assert CreateEnvironment(ctx).execute(spec())["state"] == "READY"


@pytest.mark.parametrize("failure_stage", ["destroy", "inventory"])
def test_expiry_continues_after_delete_failure(ctx, monkeypatch, caplog, failure_stage):
    CreateEnvironment(ctx).execute(spec("feat-x"))
    CreateEnvironment(ctx).execute(spec("feat-y"))
    with ctx.registry.transaction() as db:
        db.execute("UPDATE environments SET state='DELETING' WHERE name='feat-x'")
        db.execute(
            "UPDATE environments SET ttl_expires_at='2000-01-01T00:00:00+00:00' WHERE name='feat-y'"
        )
    original = getattr(ctx.runner, failure_stage)

    def fail_first(name):
        if name == "feat-x":
            raise RuntimeError("persistent deletion failure")
        return original(name)

    monkeypatch.setattr(ctx.runner, failure_stage, fail_first)
    collected = []
    monkeypatch.setattr(
        ctx.runner, "gc_images", lambda retained: collected.append(retained)
    )
    assert main(["gc"], ctx) == 0
    assert ctx.registry.get("feat-x")["state"] == "DELETING"
    assert ctx.registry.get("feat-y")["state"] == "DELETED"
    assert "feat-x: persistent deletion failure" in caplog.text
    assert len(collected) == 1
    with ctx.registry.connect() as db:
        failed = db.execute(
            "SELECT status,error_json FROM operations WHERE kind='EXPIRE' ORDER BY id"
        ).fetchall()
    assert [row["status"] for row in failed] == ["FAILED", "SUCCEEDED"]
    assert json.loads(failed[0]["error_json"])["stage"] == "delete"


@pytest.mark.parametrize(
    "state",
    [
        "REQUESTED",
        "RESOLVING",
        "BUILDING",
        "STARTING",
        "UPDATING",
        "DELETING",
        "READY",
        "FAILED",
        "DELETED",
    ],
)
@pytest.mark.parametrize(
    "pid,heartbeat",
    [
        (99999999, "2999-01-01T00:00:00+00:00"),
        (os.getpid(), "2000-01-01T00:00:00+00:00"),
    ],
)
def test_recovery_preserves_deletion_and_terminal_states(ctx, state, pid, heartbeat):
    CreateEnvironment(ctx).execute(spec())
    with ctx.registry.transaction() as db:
        db.execute(
            "UPDATE operations SET status='RUNNING',pid=?,heartbeat_at=?",
            (pid, heartbeat),
        )
        db.execute("UPDATE environments SET state=?", (state,))
    recovered = DescribeEnvironment(ctx).execute("feat-x")
    expected = (
        "FAILED"
        if state in {"REQUESTED", "RESOLVING", "BUILDING", "STARTING", "UPDATING"}
        else state
    )
    assert recovered["state"] == expected
    with ctx.registry.connect() as db:
        op = db.execute("SELECT * FROM operations").fetchone()
    assert op["status"] == "INTERRUPTED"
    assert op["finished_at"]
    if state == "DELETING":
        assert json.loads(op["error_json"])["stage"] == "delete"
        assert ExpireEnvironments(ctx).execute() == ["feat-x"]
        assert ctx.registry.get("feat-x")["state"] == "DELETED"


@pytest.mark.parametrize("inject_url", [True, False])
def test_adding_optional_service_changes_interpolated_consumer_only(ctx, inject_url):
    from conftest import manifest

    from preview_hub.contracts import CatalogEntry

    ctx.catalog = replace(
        ctx.catalog,
        services={
            **ctx.catalog.services,
            "frontend": CatalogEntry("org/frontend", "main"),
            "notifier": CatalogEntry("org/notifier", "main", "on_request"),
        },
    )
    ctx.git.manifests.update(
        {
            "org/backend": manifest(
                requires=[{"service": "notifier", "optional": True}],
                env={"NOTIFIER_URL": "${services.notifier.internal_url}"}
                if inject_url
                else {},
            ),
            "org/frontend": manifest("frontend"),
            "org/notifier": manifest("notifier"),
        }
    )
    CreateEnvironment(ctx).execute(spec())
    assert "NOTIFIER_URL" not in ctx.runner.plans["feat-x"].services[0].env
    UpdateEnvironment(ctx).execute("feat-x", {"notifier": "main"})
    services = {s.name: s for s in ctx.runner.plans["feat-x"].services}
    if inject_url:
        assert services["backend"].env["NOTIFIER_URL"] == "http://notifier:8000"
    assert {name for name, service in services.items() if service.changed} == {
        "backend",
        "notifier",
    }
    assert len(ctx.runner.builds) == 3


@pytest.mark.parametrize("case", ["missing", "state", "empty", "unknown", "empty-ref"])
def test_update_input_errors_precede_disk_guard(ctx, case):
    if case != "missing":
        CreateEnvironment(ctx).execute(spec())
    if case == "state":
        with ctx.registry.transaction() as db:
            db.execute("UPDATE environments SET state='DELETING'")
    changes = {"backend": "main"}
    if case == "empty":
        changes = {}
    elif case == "unknown":
        changes = {"unknown": "main"}
    elif case == "empty-ref":
        changes = {"backend": ""}
    before = ctx.registry.get("feat-x")
    ctx.free_space = lambda: 0
    with pytest.raises(InvalidInput):
        UpdateEnvironment(ctx).execute("feat-x", changes)
    assert ctx.registry.get("feat-x") == before
