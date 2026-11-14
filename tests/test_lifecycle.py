import fcntl
import json
import os
import threading
import time
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
from preview_hub.runner import Health


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
    with pytest.raises(InvalidInput) as error:
        CreateEnvironment(ctx).execute(spec(backend="other"))
    assert str(error.value) == (
        "Environment exists with different refs; update it instead "
        "(dashboard update, `/preview update`, or `phub update`)"
    )
    updated = UpdateEnvironment(ctx).execute("feat-x", {"backend": "other"})
    assert updated["services"][0]["commit_sha"] == "b" * 40
    assert updated["state"] == "READY"
    result = DeleteEnvironment(ctx).execute("feat-x")
    assert result["state"] == "DELETED"
    assert DeleteEnvironment(ctx).execute("feat-x") == result
    assert DeleteEnvironment(ctx).execute("unknown") is None
    assert CreateEnvironment(ctx).execute(spec())["id"] != first["id"]


def test_create_existing_non_ready_environment_message(ctx):
    CreateEnvironment(ctx).execute(spec())
    with ctx.registry.transaction() as db:
        db.execute("UPDATE environments SET state='FAILED' WHERE name='feat-x'")
    before = ctx.registry.get("feat-x")

    with pytest.raises(InvalidInput) as error:
        CreateEnvironment(ctx).execute(spec())

    assert str(error.value) == (
        "Environment is not READY; update or delete it first "
        "(dashboard, `/preview update|down`, or `phub update|down`)"
    )
    assert ctx.registry.get("feat-x") == before


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
        # A restarted container reuses PIDs: a live PID with a fresh heartbeat is still dead
        # once the environment lock is free.
        (os.getpid(), "2999-01-01T00:00:00+00:00"),
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


def test_gc_reclaims_every_interrupted_environment_in_one_pass(ctx):
    CreateEnvironment(ctx).execute(spec())
    CreateEnvironment(ctx).execute(spec("feat-y"))
    with ctx.registry.transaction() as db:
        db.execute(
            "UPDATE operations SET status='RUNNING',pid=?,heartbeat_at=?",
            (os.getpid(), "2999-01-01T00:00:00+00:00"),
        )
        db.execute("UPDATE environments SET state='STARTING'")
    ExpireEnvironments(ctx).execute()
    assert {e["name"]: e["state"] for e in ctx.registry.list()} == {
        "feat-x": "FAILED",
        "feat-y": "FAILED",
    }


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
            == "4"
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
    # Another process running the operation holds the environment flock.
    with (ctx.registry.state_dir / "locks" / "feat-x.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BusyError):
            DescribeEnvironment(ctx).execute("feat-x")
    with ctx.registry.connect() as db:
        assert db.execute("SELECT status FROM operations").fetchone()[0] == "RUNNING"


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


@pytest.mark.parametrize("live", ["UNHEALTHY", "missing", OSError, ValueError])
def test_descriptor_live_readiness(ctx, monkeypatch, live):
    from preview_hub.cli import environment_descriptor

    env = CreateEnvironment(ctx).execute(spec())
    before = ctx.registry.path.read_bytes()

    def health(name):
        assert name == env["name"]
        if isinstance(live, type):
            raise live("health failed")
        return {} if live == "missing" else {"backend": Health.UNHEALTHY}

    monkeypatch.setattr(ctx.runner, "health", health)
    checked = "2030-01-01T00:00:00Z"
    document = environment_descriptor(ctx, env, now=checked)
    assert document["readiness"] == {"allHealthy": False, "checkedAt": checked}
    expected = (
        "HEALTHY"
        if isinstance(live, type)
        else ("UNKNOWN" if live == "missing" else "UNHEALTHY")
    )
    assert document["services"][0]["health"] == expected
    assert env["services"][0]["health"] == "HEALTHY"
    assert ctx.registry.path.read_bytes() == before


def test_descriptor_non_ready_uses_stored_health(ctx, monkeypatch):
    from preview_hub.cli import environment_descriptor

    env = CreateEnvironment(ctx).execute(spec())
    env["state"] = "STARTING"

    def health(name):
        pytest.fail("Non-READY descriptors must not check health")

    monkeypatch.setattr(ctx.runner, "health", health)
    document = environment_descriptor(ctx, env, now="2030-01-01T00:00:00Z")
    assert document["readiness"] == {
        "allHealthy": False,
        "checkedAt": env["updated_at"],
    }
    assert document["services"][0]["health"] == "HEALTHY"


@pytest.mark.parametrize("services", [("backend",), ("backend", "frontend")])
def test_operation_stage_timings(ctx, services):
    from datetime import datetime

    from conftest import manifest

    from preview_hub.contracts import CatalogEntry

    for service in services:
        ctx.catalog.services[service] = CatalogEntry(f"org/{service}", "main")
        ctx.git.manifests[f"org/{service}"] = manifest(service)
    ctx.catalog = replace(ctx.catalog, build_concurrency=1)
    env = CreateEnvironment(ctx).execute(spec(**dict.fromkeys(services, "main")))
    rows = ctx.registry.latest_stages(env["id"])
    assert [(r["stage"], r["service"]) for r in rows] == [
        pair
        for service in services
        for pair in [("resolve", service), ("checkout", service)]
    ] + [("build", service) for service in services] + [
        ("apply", None),
        ("health", None),
    ]
    assert all(r["status"] == "SUCCEEDED" and r["seconds"] >= 0 for r in rows)
    with ctx.registry.connect() as db:
        timestamps = [
            datetime.fromisoformat(value)
            for row in db.execute(
                "SELECT started_at,finished_at FROM operation_stages ORDER BY id"
            )
            for value in row
        ]
    assert timestamps == sorted(timestamps)
    UpdateEnvironment(ctx).execute("feat-x", {"backend": "main"})
    assert "build" not in [r["stage"] for r in ctx.registry.latest_stages(env["id"])]
    DeleteEnvironment(ctx).execute("feat-x")
    assert [r["stage"] for r in ctx.registry.latest_stages(env["id"])] == ["delete"]


@pytest.mark.parametrize("failure,last", [("build", "build"), ("start", "apply")])
def test_failed_operation_stage(ctx, failure, last):
    ctx.runner.fail_at = failure
    with pytest.raises(OperationFailed):
        CreateEnvironment(ctx).execute(spec())
    env = ctx.registry.get("feat-x")
    rows = ctx.registry.latest_stages(env["id"])
    assert rows[-1]["stage"] == last
    assert rows[-1]["status"] == "FAILED"
    assert rows[-1]["seconds"] >= 0
    assert all(r["status"] == "SUCCEEDED" for r in rows[:-1])
    assert "health" not in [r["stage"] for r in rows]


def test_status_json_stages(ctx, capsys):
    CreateEnvironment(ctx).execute(spec())
    assert main(["status", "feat-x", "--format", "json"], ctx) == 0
    assert json.loads(capsys.readouterr().out)["stages"][-1]["stage"] == "health"


def test_stage_writes_from_parallel_threads(ctx):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from preview_hub.lifecycle import _stage

    CreateEnvironment(ctx).execute(spec())
    barrier = threading.Barrier(4)

    def record(service):
        with _stage(ctx, 1, "build", service):
            barrier.wait(timeout=5)
            rows = ctx.registry.stages(1)
            running = [r for r in rows if r["service"] == service]
            assert running[-1]["status"] == "RUNNING"
            assert running[-1]["seconds"] is None

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(record, [f"worker-{i}" for i in range(4)]))
    assert all(r["status"] == "SUCCEEDED" for r in ctx.registry.stages(1))


@pytest.fixture
def two_build_services(ctx):
    from conftest import manifest

    from preview_hub.contracts import CatalogEntry

    ctx.catalog.services["frontend"] = CatalogEntry("org/frontend", "main")
    ctx.git.manifests["org/frontend"] = manifest("frontend")
    return ctx


@pytest.mark.parametrize("concurrency", [1, 2])
def test_changed_services_build_concurrency(
    two_build_services, monkeypatch, concurrency
):
    ctx = two_build_services
    ctx.catalog = replace(ctx.catalog, build_concurrency=concurrency)
    barrier = threading.Barrier(2, timeout=5)
    lock = threading.Lock()
    active = maximum = 0
    original = ctx.runner.build

    def build(service, commit, source, manifest):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            if concurrency == 2:
                barrier.wait()
            else:
                time.sleep(0.02)
            return original(service, commit, source, manifest)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(ctx.runner, "build", build)
    env = CreateEnvironment(ctx).execute(spec(backend="main", frontend="main"))
    assert env["state"] == "READY"
    assert maximum == concurrency
    assert len(ctx.runner.builds) == 2


@pytest.mark.parametrize("failing", ["backend", "frontend", "both"])
def test_parallel_build_failure_finishes_stages(
    two_build_services, monkeypatch, failing
):
    ctx = two_build_services
    barrier = threading.Barrier(2, timeout=5)
    original = ctx.runner.build

    def build(service, commit, source, manifest):
        barrier.wait()
        if failing == "both" or service == failing:
            raise RuntimeError(f"failed {service}")
        time.sleep(0.02)
        return original(service, commit, source, manifest)

    monkeypatch.setattr(ctx.runner, "build", build)
    with pytest.raises(OperationFailed) as error:
        CreateEnvironment(ctx).execute(spec(backend="main", frontend="main"))
    expected = "backend" if failing == "both" else failing
    assert error.value.failure.stage == "build"
    assert error.value.failure.service == expected
    assert error.value.failure.message == f"failed {expected}"
    env = ctx.registry.get("feat-x")
    assert env["state"] == "FAILED"
    rows = {
        row["service"]: row
        for row in ctx.registry.latest_stages(env["id"])
        if row["stage"] == "build"
    }
    assert rows[expected]["status"] == "FAILED"
    assert all(row["status"] != "RUNNING" for row in rows.values())
    if failing != "both":
        other = "frontend" if failing == "backend" else "backend"
        assert other not in rows or rows[other]["status"] == "SUCCEEDED"
