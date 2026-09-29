from __future__ import annotations

import fcntl
import json
import logging
import os
import shutil
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .contracts import (
    Catalog,
    CompositionSpec,
    EnvName,
    InvalidInput,
    ServiceManifest,
    duration,
)
from .git import GitSource, PrRef
from .plan import PlanBuilder
from .registry import BusyError, Registry, now
from .runner import FailureInfo, Health, Runner


class CapacityError(RuntimeError):
    pass


class OperationFailed(RuntimeError):
    def __init__(self, failure: FailureInfo):
        super().__init__(failure.message)
        self.failure = failure


@dataclass
class Context:
    registry: Registry
    catalog: Catalog
    git: GitSource
    runner: Runner
    free_space: Callable[[], int] | None = None
    min_free_bytes: int = 5 * 1024**3
    poll_interval: float = 0.1

    def disk_guard(self) -> None:
        free = (
            self.free_space()
            if self.free_space
            else shutil.disk_usage(self.registry.state_dir).free
        )
        if free < self.min_free_bytes:
            raise CapacityError("VM free disk space below 5 GiB")


@contextmanager
def _heartbeat(ctx: Context, op: int) -> Generator[None]:
    stop = threading.Event()

    def beat() -> None:
        while not stop.wait(30):
            with ctx.registry.transaction() as db:
                db.execute(
                    "UPDATE operations SET heartbeat_at=? WHERE id=? AND status='RUNNING'",
                    (now(), op),
                )

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


@contextmanager
def _build_slot(ctx: Context) -> Generator[None]:
    folder = ctx.registry.state_dir / "locks"
    handles = [
        (folder / f"build-{i}.lock").open("a")
        for i in range(ctx.catalog.build_concurrency)
    ]
    selected = None
    try:
        while selected is None:
            for handle in handles:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    selected = handle
                    break
                except BlockingIOError:
                    continue
            if selected is None:
                time.sleep(0.1)
        yield
    finally:
        for handle in handles:
            handle.close()


def _operation(db: Any, env_id: int, kind: str, requested_by: str) -> int:
    cursor = db.execute(
        "INSERT INTO operations(environment_id,kind,status,requested_by,pid,heartbeat_at,started_at) VALUES (?,?,'RUNNING',?,?,?,?)",
        (env_id, kind, requested_by, os.getpid(), now(), now()),
    )
    return int(cursor.lastrowid)


def _state(
    ctx: Context,
    env_id: int,
    state: str,
    op: int,
    status: str = "RUNNING",
    error: FailureInfo | None = None,
) -> None:
    serialized = json.dumps(asdict(error)) if error else None
    with ctx.registry.transaction() as db:
        db.execute(
            "UPDATE environments SET state=?,version=version+1,updated_at=?,last_error_json=?,deleted_at=? WHERE id=?",
            (state, now(), serialized, now() if state == "DELETED" else None, env_id),
        )
        db.execute(
            "UPDATE operations SET status=?,heartbeat_at=?,finished_at=?,error_json=? WHERE id=?",
            (status, now(), None if status == "RUNNING" else now(), serialized, op),
        )


def _provision(
    ctx: Context,
    spec: CompositionSpec,
    env_id: int,
    op: int,
    old: dict[str, Any] | None,
    changes: set[str],
    pr_pins: dict[str, str],
) -> dict[str, Any]:
    stage = "resolve"
    current: str | None = None
    try:
        with _heartbeat(ctx, op):
            manifests: dict[str, ServiceManifest] = {}
            commits: dict[str, str] = {}
            sources: dict[str, Path] = {}
            images: dict[str, str] = {}
            previous = {s["service"]: s for s in old["services"]} if old else {}
            previous_plan = None
            if old and old["state"] == "READY":
                previous_plan = PlanBuilder().build(
                    spec.name,
                    {
                        name: ctx.git.read_manifest(pin["repo"], pin["commit_sha"])
                        for name, pin in previous.items()
                    },
                    ctx.catalog,
                    {name: pin["commit_sha"] for name, pin in previous.items()},
                    {name: Path(".") for name in previous},
                    {name: pin["image"] for name, pin in previous.items()},
                )
            refs = dict(spec.services)
            pending = list(refs)
            while pending:
                current = pending.pop(0)
                entry = ctx.catalog.services[current]
                prior = previous.get(current)
                sha = (
                    pr_pins[current]
                    if current in pr_pins
                    else ctx.git.resolve(entry.repo, refs[current])
                    if current in changes or prior is None
                    else str(prior["commit_sha"])
                )
                if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
                    raise InvalidInput("GitSource returned invalid commit")
                manifest = ctx.git.read_manifest(entry.repo, sha)
                if manifest.service != current:
                    raise InvalidInput("Manifest service does not match catalog key")
                manifests[current] = manifest
                commits[current] = sha
                sources[current] = ctx.git.checkout(entry.repo, sha)
                images[current] = f"phub/{current}:{sha[:12]}"
                for dep in manifest.requires:
                    target = str(dep["service"])
                    if not dep.get("optional", False) and target not in refs:
                        if target not in ctx.catalog.services:
                            raise InvalidInput(f"Unknown required service: {target}")
                        refs[target] = ctx.catalog.services[target].default_ref
                        pending.append(target)
            changed = {
                s
                for s, sha in commits.items()
                if s not in previous or previous[s]["commit_sha"] != sha
            }
            if old and old["state"] == "FAILED":
                changed.update(commits)
            completed = CompositionSpec(spec.name, refs, spec.ttl)
            plan = PlanBuilder().build(
                spec.name, manifests, ctx.catalog, commits, sources, images, changed
            )
            with ctx.registry.transaction() as db:
                db.execute(
                    "UPDATE environments SET spec_json=? WHERE id=?",
                    (json.dumps(completed.as_dict()), env_id),
                )
                for service, sha in commits.items():
                    prior = previous.get(service)
                    if prior and prior["commit_sha"] == sha:
                        db.execute(
                            "UPDATE environment_services SET requested_ref=? WHERE environment_id=? AND service=?",
                            (refs[service], env_id, service),
                        )
                    else:
                        db.execute(
                            "DELETE FROM environment_services WHERE environment_id=? AND service=?",
                            (env_id, service),
                        )
                        db.execute(
                            "INSERT INTO environment_services(environment_id,service,repo,requested_ref,commit_sha,image,health) VALUES (?,?,?,?,?,?,?)",
                            (
                                env_id,
                                service,
                                ctx.catalog.services[service].repo,
                                refs[service],
                                sha,
                                images[service],
                                Health.UNKNOWN,
                            ),
                        )
            _state(ctx, env_id, "BUILDING", op)
            stage = "build"
            for service in plan.services:
                current = service.name
                if current in changed:
                    with _build_slot(ctx):
                        images[current] = ctx.runner.build(
                            current,
                            commits[current],
                            sources[current],
                            manifests[current],
                        )
                else:
                    images[current] = previous[current]["image"]
            plan = PlanBuilder().build(
                spec.name,
                manifests,
                ctx.catalog,
                commits,
                sources,
                images,
                changed,
                previous_plan,
            )
            # The reconstructed previous plan uses today's catalog. Persisted URLs
            # record the applied routes, including those from an older catalog.
            changed_urls = {
                service.name
                for service in plan.services
                if service.name in previous
                and previous[service.name]["public_url"] != service.public_url
            }
            plan = replace(
                plan,
                services=tuple(
                    replace(
                        service,
                        changed=service.changed
                        or service.name in changed_urls
                        or any(
                            "${services." + target + ".public_url}" in value
                            for target in changed_urls
                            for value in service.manifest.env.values()
                        ),
                    )
                    for service in plan.services
                ),
            )
            _state(ctx, env_id, "STARTING", op)
            stage, current = "start", None
            result = ctx.runner.apply(plan)
            if not result.success:
                raise OperationFailed(
                    FailureInfo(
                        stage,
                        result.service,
                        result.message,
                        result.log_excerpt or result.message[-2000:],
                    )
                )
            with ctx.registry.transaction() as db:
                for service in plan.services:
                    db.execute(
                        "UPDATE environment_services SET image=?,public_url=? WHERE environment_id=? AND service=?",
                        (service.image, service.public_url, env_id, service.name),
                    )
            stage = "health"
            deadlines = {
                s.name: time.monotonic() + duration(str(s.manifest.health["timeout"]))
                for s in plan.services
            }
            while True:
                health = ctx.runner.health(spec.name)
                if all(health.get(s.name) == Health.HEALTHY for s in plan.services):
                    break
                for service in plan.services:
                    current = service.name
                    if health.get(current) == Health.UNHEALTHY or (
                        health.get(current) != Health.HEALTHY
                        and time.monotonic() >= deadlines[current]
                    ):
                        raise RuntimeError(f"Health check failed: {current}")
                time.sleep(ctx.poll_interval)
            with ctx.registry.transaction() as db:
                for service, value in health.items():
                    db.execute(
                        "UPDATE environment_services SET health=? WHERE environment_id=? AND service=?",
                        (value, env_id, service),
                    )
            _state(ctx, env_id, "READY", op, "SUCCEEDED")
    except Exception as exc:
        failure = (
            exc.failure
            if isinstance(exc, OperationFailed)
            else FailureInfo(stage, current, str(exc), str(exc)[-2000:])
        )
        _state(ctx, env_id, "FAILED", op, "FAILED", failure)
        raise OperationFailed(failure) from exc
    result_env = ctx.registry.get(spec.name)
    assert result_env is not None
    return result_env


def _resolve_pr_refs(ctx: Context, refs: dict[str, str]) -> dict[str, str]:
    # Reject PR inputs before recording an operation; use each observed head once.
    return {
        service: ctx.git.resolve(ctx.catalog.services[service].repo, ref)
        for service, ref in refs.items()
        if PrRef.parse(ref) is not None
    }


class CreateEnvironment:
    def __init__(self, context: Context):
        self.context = context

    def execute(
        self, spec: CompositionSpec, requested_by: str = "cli:user"
    ) -> dict[str, Any]:
        ctx = self.context
        spec = ctx.catalog.complete(spec)
        with ctx.registry.lock(spec.name):
            old = ctx.registry.get(spec.name)
            if old and old["state"] != "DELETED":
                previous = CompositionSpec.parse(json.loads(old["spec_json"]))
                requested = dict(spec.services)
                pins = {pin["service"]: pin for pin in old["services"]}
                # Complete mandatory dependencies using pinned manifests, never moving refs.
                pending = (
                    list(requested)
                    if previous.services.keys() - requested.keys()
                    else []
                )
                visited: set[str] = set()
                while pending:
                    service = pending.pop()
                    if service in visited or service not in pins:
                        continue
                    visited.add(service)
                    pin = pins[service]
                    manifest = ctx.git.read_manifest(pin["repo"], pin["commit_sha"])
                    for dependency in manifest.requires:
                        target = str(dependency["service"])
                        if (
                            not dependency.get("optional", False)
                            and target not in requested
                        ):
                            if target not in ctx.catalog.services:
                                raise InvalidInput(
                                    f"Unknown required service: {target}"
                                )
                            requested[target] = ctx.catalog.services[target].default_ref
                            pending.append(target)
                if requested != previous.services:
                    raise InvalidInput(
                        "Environment exists with different refs; use phub update"
                    )
                if old["state"] == "READY":
                    return old
                raise InvalidInput("Environment is not READY; use phub update or down")
            ctx.disk_guard()
            pr_pins = _resolve_pr_refs(ctx, spec.services)
            with ctx.registry.transaction() as db:
                count = db.execute(
                    "SELECT count(*) FROM environments WHERE state!='DELETED'"
                ).fetchone()[0]
                if count >= ctx.catalog.max_environments:
                    raise CapacityError("Maximum environment capacity reached")
                try:
                    expiry = (
                        datetime.now(UTC)
                        + timedelta(
                            seconds=duration(spec.ttl or ctx.catalog.default_ttl)
                        )
                    ).isoformat()
                except OverflowError as exc:
                    raise InvalidInput("TTL deadline is out of range") from exc
                cursor = db.execute(
                    "INSERT INTO environments(name,state,spec_json,ttl_expires_at,created_at,updated_at) VALUES (?,'REQUESTED',?,?,?,?)",
                    (spec.name, json.dumps(spec.as_dict()), expiry, now(), now()),
                )
                assert cursor.lastrowid is not None
                env_id = cursor.lastrowid
                op = _operation(db, env_id, "CREATE", requested_by)
            _state(ctx, env_id, "RESOLVING", op)
            return _provision(ctx, spec, env_id, op, None, set(spec.services), pr_pins)


class UpdateEnvironment:
    def __init__(self, context: Context):
        self.context = context

    def execute(
        self, name: str, changes: dict[str, str], requested_by: str = "cli:user"
    ) -> dict[str, Any]:
        ctx = self.context
        with ctx.registry.lock(name):
            with ctx.registry.transaction() as db:
                old = ctx.registry.get(name, db)
                if old is None or old["state"] not in {"READY", "FAILED"}:
                    raise InvalidInput("Update requires a READY or FAILED environment")
                if not changes or changes.keys() - ctx.catalog.services.keys():
                    raise InvalidInput("Update requires known service refs")
                previous = CompositionSpec.parse(json.loads(old["spec_json"]))
                spec = ctx.catalog.complete(
                    CompositionSpec(
                        EnvName(name), {**previous.services, **changes}, previous.ttl
                    )
                )
                ctx.disk_guard()
            pr_pins = _resolve_pr_refs(ctx, changes)
            with ctx.registry.transaction() as db:
                op = _operation(db, old["id"], "UPDATE", requested_by)
                db.execute(
                    "UPDATE environments SET state='UPDATING',version=version+1,updated_at=? WHERE id=?",
                    (now(), old["id"]),
                )
            return _provision(ctx, spec, old["id"], op, old, set(changes), pr_pins)


class DeleteEnvironment:
    def __init__(self, context: Context):
        self.context = context

    def execute(
        self, name: str, requested_by: str = "cli:user", kind: str = "DELETE"
    ) -> dict[str, Any] | None:
        ctx = self.context
        with ctx.registry.lock(name):
            return _delete_locked(ctx, name, requested_by, kind)


def _delete_locked(
    ctx: Context, name: str, requested_by: str, kind: str
) -> dict[str, Any] | None:
    with ctx.registry.transaction() as db:
        old = ctx.registry.get(name, db)
        op = None
        if old and old["state"] != "DELETED":
            op = _operation(db, old["id"], kind, requested_by)
            db.execute(
                "UPDATE environments SET state='DELETING',version=version+1,updated_at=? WHERE id=?",
                (now(), old["id"]),
            )
    try:
        if op is not None:
            with _heartbeat(ctx, op):
                ctx.runner.destroy(name)
        else:
            ctx.runner.destroy(name)
        inventory = ctx.runner.inventory(name)
        if not inventory.empty:
            raise RuntimeError(f"Objects remain: {inventory}")
        if op is not None and old:
            _state(ctx, old["id"], "DELETED", op, "SUCCEEDED")
    except Exception as exc:
        failure = FailureInfo("delete", None, str(exc), str(exc)[-2000:])
        if op is not None and old:
            _state(ctx, old["id"], "DELETING", op, "FAILED", failure)
        raise OperationFailed(failure) from exc
    return ctx.registry.get(name)


class ExpireEnvironments:
    def __init__(self, context: Context):
        self.context = context

    def execute(self) -> list[str]:
        ctx = self.context
        deleted: list[str] = []
        for row in ctx.registry.list():
            if row["state"] == "DELETED":
                continue
            try:
                with ctx.registry.lock(row["name"]):
                    current = ctx.registry.get(row["name"])
                    assert current is not None
                    if current["state"] == "DELETING" or (
                        current["state"] in {"READY", "FAILED"}
                        and current["ttl_expires_at"] < now()
                    ):
                        _delete_locked(ctx, row["name"], "cli:gc", "EXPIRE")
                        deleted.append(row["name"])
            except BusyError:
                continue
            except OperationFailed as exc:
                logging.getLogger(__name__).warning(
                    "Failed to expire environment %s: %s", row["name"], exc
                )
        return deleted


class DescribeEnvironment:
    def __init__(self, context: Context):
        self.context = context

    def execute(self, name: str) -> dict[str, Any]:
        with self.context.registry.lock(name):
            result = self.context.registry.get(name)
            if result is None:
                raise InvalidInput(f"Unknown environment: {name}")
            return result
