from __future__ import annotations

import argparse
import fcntl
import getpass
import json
import math
import os
import sys
import time
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

from .contracts import (
    Catalog,
    CompositionSpec,
    EnvName,
    InvalidInput,
    load_yaml,
    validate,
)
from .git import GitCliSource
from .lifecycle import (
    CapacityError,
    Context,
    CreateEnvironment,
    DeleteEnvironment,
    DescribeEnvironment,
    ExpireEnvironments,
    OperationFailed,
    UpdateEnvironment,
)
from .registry import BusyError, Registry
from .runner import Health, ImageCollector, Runner


class LogReader(Protocol):
    def logs(self, env: str, service: str, tail: int = 100) -> str: ...


def descriptor(env: dict[str, Any], template: str) -> dict[str, Any]:
    services = [
        {
            "name": s["service"],
            "repo": s["repo"],
            "ref": s["requested_ref"],
            "commit": s["commit_sha"],
            "publicUrl": s["public_url"],
            "health": s["health"] or "UNKNOWN",
        }
        for s in env["services"]
    ]
    urls = {s["name"]: s["publicUrl"] for s in services if s["publicUrl"]}
    result = {
        "apiVersion": "preview-hub/v1",
        "kind": "EnvironmentDescriptor",
        "name": env["name"],
        "state": env["state"],
        "createdAt": env["created_at"],
        "expiresAt": env["ttl_expires_at"],
        "entryUrl": urls.get("frontend", next(iter(urls.values()), None)),
        "proxy": {
            "hostPort": urlsplit(template).port or 80,
            "inNetworkAddress": "phub-proxy:80",
        },
        "services": services,
        "testAccounts": [],
        "readiness": {
            "allHealthy": env["state"] == "READY"
            and bool(services)
            and all(s["health"] == Health.HEALTHY for s in services),
            "checkedAt": env["updated_at"],
        },
    }
    return validate("environment-descriptor", result)


def config_override(config: dict[str, Any], env: str, key: str, default: str) -> str:
    value = os.environ.get(env) or config.get(key)
    return default if value is None else str(value)


def create_context() -> Context:
    config_path = os.environ.get("PHUB_CONFIG")
    loaded_config = load_yaml(Path(config_path)) if config_path else None
    if loaded_config is not None and not isinstance(loaded_config, dict):
        raise InvalidInput("PHUB_CONFIG must contain a mapping")
    config = cast(dict[str, Any], loaded_config) if loaded_config is not None else {}
    state_dir = Path(config_override(config, "PHUB_STATE_DIR", "state_dir", "/state"))
    catalog_path = Path(
        config_override(config, "PHUB_CATALOG", "catalog", "/etc/phub/catalog.yaml")
    )
    catalog = Catalog.parse(load_yaml(catalog_path))
    runner_name = config_override(config, "PHUB_RUNNER", "runner", "fake")
    runner: Runner
    free_space = None
    poll_interval = 0.1
    if runner_name == "compose":
        from .runners.compose import ComposeRunner, vm_free_bytes

        poll_interval = float(os.environ.get("PHUB_HEALTH_POLL_INTERVAL", "2"))
        if not math.isfinite(poll_interval) or poll_interval <= 0:
            raise InvalidInput("Health poll interval must be finite and positive")
        runner = ComposeRunner(
            state_dir,
            config_override(
                config, "PHUB_DAEMON_NAME", "daemon_name", "colima-preview-hub"
            ),
        )
        free_space = lambda: vm_free_bytes(state_dir)
    elif runner_name == "fake":
        from .runners.fake import FakeRunner

        runner = FakeRunner()
    else:
        raise InvalidInput(f"Runner unavailable: {runner_name}")

    return Context(
        Registry(state_dir),
        catalog,
        GitCliSource(
            Path(config_override(config, "PHUB_SOURCE_DIR", "source_dir", "/src")),
            {v.repo: k for k, v in catalog.services.items()},
        ),
        runner,
        free_space=free_space,
        poll_interval=poll_interval,
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="phub")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("bot")
    serve = commands.add_parser("serve")
    serve.add_argument(
        "--interval",
        type=float,
        default=None,
    )
    inventory = commands.add_parser("inventory")
    inventory.add_argument("name", nargs="?")
    inventory.add_argument("--format", choices=("json",), default="json")
    for command in ("up", "update", "status", "list", "down", "logs", "gc"):
        sub = commands.add_parser(command)
        sub.add_argument(
            "--format",
            choices=("text", "json", "descriptor")
            if command in {"up", "update", "status"}
            else ("text", "json"),
            default="text",
        )
        if command not in {"list", "gc"}:
            sub.add_argument("name", nargs="?" if command == "up" else None)
        if command in {"up", "update"}:
            sub.add_argument("--set", dest="refs", action="append", default=[])
        if command == "up":
            sub.add_argument("-f", dest="file")
            sub.add_argument("--ttl")
        if command == "logs":
            sub.add_argument("service")
            sub.add_argument("--tail", type=int, default=100)
    return root


def main(argv: list[str] | None = None, context: Context | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "bot":
            from .bot.polling import serve

            serve()
            return 0
        if args.command == "serve":
            if args.interval is None:
                args.interval = float(os.environ.get("PHUB_GC_INTERVAL", "900"))
            if not math.isfinite(args.interval) or args.interval <= 0:
                raise InvalidInput("GC interval must be finite and positive")
        ctx = context or create_context()
        if args.command == "serve":
            while True:
                main(["gc", "--format", "json"], ctx)
                time.sleep(args.interval)
        actor = f"cli:{getpass.getuser()}"
        refs: dict[str, str] = {}
        for value in getattr(args, "refs", []):
            key, sep, ref = value.partition("=")
            if not sep or not key or not ref:
                raise InvalidInput("--set requires service=ref")
            refs[key] = ref
        result: Any
        if args.command == "inventory":
            result = asdict(ctx.runner.inventory(args.name))
        elif args.command == "up":
            if args.file:
                spec = CompositionSpec.parse(load_yaml(Path(args.file)))
                if args.name and args.name != spec.name:
                    raise InvalidInput("Name differs from spec file")
                spec = CompositionSpec(
                    spec.name, {**spec.services, **refs}, args.ttl or spec.ttl
                )
            else:
                if not args.name:
                    raise InvalidInput("up requires a name or -f")
                spec = CompositionSpec(EnvName(args.name), refs, args.ttl)
            result = CreateEnvironment(ctx).execute(spec, actor)
        elif args.command == "update":
            result = UpdateEnvironment(ctx).execute(args.name, refs, actor)
        elif args.command == "status":
            result = DescribeEnvironment(ctx).execute(args.name)
        elif args.command == "down":
            result = DeleteEnvironment(ctx).execute(args.name, actor)
        elif args.command == "list":
            for row in ctx.registry.list():
                if row["state"] != "DELETED":
                    try:
                        DescribeEnvironment(ctx).execute(row["name"])
                    except BusyError:
                        pass
            result = ctx.registry.list()
        elif args.command == "gc":
            result = ExpireEnvironments(ctx).execute()
            if hasattr(ctx.runner, "gc_images"):
                # Exclude builds while taking the active-image snapshot and collecting.
                with ExitStack() as stack:
                    folder = ctx.registry.state_dir / "locks"
                    folder.mkdir(exist_ok=True)
                    for index in range(ctx.catalog.build_concurrency):
                        handle = stack.enter_context(
                            (folder / f"build-{index}.lock").open("a")
                        )
                        fcntl.flock(handle, fcntl.LOCK_EX)
                    db = ctx.registry.connect()
                    try:
                        retained = {
                            str(row[0])
                            for row in db.execute(
                                "SELECT s.image FROM environment_services s JOIN environments e ON e.id=s.environment_id WHERE e.state!='DELETED'"
                            )
                        }
                    finally:
                        db.close()
                    cast(ImageCollector, ctx.runner).gc_images(retained)
        else:
            DescribeEnvironment(ctx).execute(args.name)
            if args.tail < 0:
                raise InvalidInput("--tail must be nonnegative")
            if not hasattr(ctx.runner, "logs"):
                raise InvalidInput("Runner does not support logs")
            result = cast(LogReader, ctx.runner).logs(
                args.name, args.service, args.tail
            )
        if args.format == "descriptor":
            if not isinstance(result, dict) or "services" not in result:
                raise InvalidInput("Descriptor format requires one environment")
            result = descriptor(
                cast(dict[str, Any], result), ctx.catalog.public_url_template
            )
        if args.format in {"json", "descriptor"}:
            print(json.dumps(result, indent=2))
        elif isinstance(result, dict):
            print(f"{result['name']}: {result['state']}")
            for service in cast(dict[str, Any], result).get("services", []):
                print(
                    f"  {service['service']} {service['commit_sha']} {service['public_url'] or ''}"
                )
        else:
            print(result if isinstance(result, str) else json.dumps(result, indent=2))
        return 0
    except (InvalidInput, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except BusyError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except CapacityError as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except OperationFailed as exc:
        print(json.dumps(as_failure(exc)), file=sys.stderr)
        return 5


def as_failure(exc: OperationFailed) -> dict[str, Any]:
    from dataclasses import asdict

    return asdict(exc.failure)
