"""Docker adapter. Every discovery query is restricted to hub ownership labels."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import yaml

from ..contracts import EnvName, ServiceManifest, duration
from ..runner import EnvironmentPlan, Health, Inventory, RunResult

Executor = Callable[[list[str], int], subprocess.CompletedProcess[str]]


def execute(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=False
    )


def vm_free_bytes(path: Path) -> int:
    stat = os.statvfs(path)
    return stat.f_bavail * stat.f_frsize


def memory(value: str) -> int:
    return int(value[:-2]) * (1024 ** (2 if value.endswith("Mi") else 3))


def _plain(value: Any) -> Any:
    """Copy the document into built-ins; YAML cannot represent domain subclasses."""
    if isinstance(value, dict):
        return {
            _plain(key): _plain(item)
            for key, item in cast(dict[Any, Any], value).items()
        }
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in cast(list[Any] | tuple[Any, ...], value)]
    if isinstance(value, str):
        return str(value)
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    raise TypeError(f"Unsupported Compose value: {type(value).__name__}")


def render(plan: EnvironmentPlan) -> dict[str, Any]:
    network = f"phub-{plan.env}"
    services: dict[str, Any] = {}
    volumes: dict[str, Any] = {}
    for resource in plan.resources:
        key = f"{resource.service}--{resource.id}"
        volumes[key] = {"name": resource.name, "labels": resource.labels}
        services[key] = {
            "image": f"postgres:{resource.version}",
            "container_name": resource.name,
            "labels": resource.labels,
            "networks": ["environment"],
            "environment": {
                "POSTGRES_USER": "preview",
                "POSTGRES_PASSWORD": "preview",
                "POSTGRES_DB": "preview",
            },
            "volumes": [f"{key}:/var/lib/postgresql/data"],
            "mem_limit": memory("512Mi"),
            "healthcheck": {
                "test": ["CMD", "pg_isready", "-U", "preview", "-d", "preview"],
                "interval": "2s",
                "timeout": "2s",
                "retries": 45,
            },
        }
    for service in plan.services:
        labels = dict(service.labels)
        labels["dev.phub.role"] = "service"
        labels["dev.phub.health"] = json.dumps(_plain(service.manifest.health))
        labels["dev.phub.port"] = str(service.port)
        if service.public_url:
            route = f"{plan.env}-{service.name}"
            labels.update(
                {
                    "traefik.enable": "true",
                    "traefik.docker.network": network,
                    f"traefik.http.routers.{route}.rule": f"Host(`{urlsplit(service.public_url).hostname}`)",
                    f"traefik.http.routers.{route}.service": route,
                    f"traefik.http.services.{route}.loadbalancer.server.port": str(
                        service.port
                    ),
                }
            )
        entry: dict[str, Any] = {
            "image": service.image,
            "labels": labels,
            "networks": ["environment"],
            "environment": service.env,
            "mem_limit": memory(service.memory),
        }
        if service.manifest.run.get("command") is not None:
            entry["command"] = service.manifest.run["command"]
        if "cmd" in service.manifest.health:
            entry["healthcheck"] = {
                "test": ["CMD", *service.manifest.health["cmd"]],
                "interval": "2s",
                "timeout": "5s",
                # Budget consecutive failures for the full manifest deadline.
                "retries": (duration(str(service.manifest.health["timeout"])) + 1) // 2,
            }
        services[service.name] = entry
        for resource in service.resources:
            for index, command in enumerate(resource.init):
                services[f"{service.name}--{resource.id}--init-{index}"] = {
                    "image": service.image,
                    "entrypoint": list(command),
                    "environment": service.env,
                    "mem_limit": memory(service.memory),
                    "networks": ["environment"],
                    "labels": {**service.labels, "dev.phub.role": "init"},
                    "profiles": ["init"],
                    "restart": "no",
                }
    return _plain(
        {
            "services": services,
            "networks": {
                "environment": {
                    "name": network,
                    "labels": {**plan.labels, "dev.phub.service": "shared"},
                }
            },
            "volumes": volumes,
        }
    )


class ComposeRunner:
    def __init__(
        self,
        state_dir: Path = Path("/state"),
        daemon_name: str = "colima-preview-hub",
        executor: Executor = execute,
    ):
        self.state_dir, self.executor = state_dir, executor
        actual = self._docker("info", "--format", "{{.Name}}").strip()
        if actual != daemon_name:
            raise ValueError(
                f"Docker daemon mismatch: expected {daemon_name!r}, got {actual!r}"
            )

    def _docker(self, *args: str, timeout: int = 120) -> str:
        try:
            result = self.executor(["docker", *(str(arg) for arg in args)], timeout)
        except subprocess.TimeoutExpired as exc:
            raise OSError(f"Docker timed out: {args}; stderr={exc.stderr!r}") from exc
        if result.returncode:
            raise OSError(
                f"Docker failed ({result.returncode}): {args}: {result.stderr[-4000:]}"
            )
        return result.stdout + (result.stderr if args[0] == "logs" else "")

    def _file(self, env: str) -> Path:
        return self.state_dir / "envs" / EnvName(env) / "compose.yaml"

    def _compose(self, env: str, *args: str) -> str:
        return self._docker(
            "compose",
            "-f",
            str(self._file(env)),
            "-p",
            f"phub-{env}",
            *args,
            timeout=600,
        )

    def _ids(self, kind: str, env: str | None = None, *filters: str) -> tuple[str, ...]:
        args = [kind, "ls", "-q"]
        if kind == "container":
            args.append("-a")
        labels = ["dev.phub.managed=true", *filters]
        if env is not None:
            labels.append(f"dev.phub.env={EnvName(env)}")
        for label in labels:
            args.extend(["--filter", f"label={label}"])
        return tuple(dict.fromkeys(self._docker(*args).split()))

    def build(
        self, service: str, commit: str, source: Path, manifest: ServiceManifest
    ) -> str:
        image = f"phub/{service}:{commit[:12]}"
        ids = self._ids("image", None, f"dev.phub.service={service}")
        for ident in ids:
            info = json.loads(self._docker("image", "inspect", ident))[0]
            if image in (info.get("RepoTags") or []):
                return image
        args = [
            "buildx",
            "build",
            "--load",
            "-t",
            image,
            "--label",
            "dev.phub.managed=true",
            "--label",
            f"dev.phub.service={service}",
            "-f",
            str(source / manifest.build["dockerfile"]),
        ]
        for key, value in manifest.build.get("args", {}).items():
            args.extend(["--build-arg", f"{key}={value}"])
        self._docker(*args, str(source / manifest.build["context"]), timeout=1800)
        return image

    def apply(self, plan: EnvironmentPlan) -> RunResult:
        current = None
        try:
            path = self._file(plan.env)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Compose interpolation must not reinterpret literal dollars in manifest values.
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                yaml.safe_dump(render(plan), sort_keys=False).replace("$", "$$")
            )
            temporary.replace(path)
            for service in plan.services:
                current = service.name
                if not service.changed:
                    continue
                for resource in service.resources:
                    self._compose(
                        plan.env,
                        "up",
                        "-d",
                        "--wait",
                        "--wait-timeout",
                        "90",
                        f"{service.name}--{resource.id}",
                    )
                for resource in service.resources:
                    for index, _ in enumerate(resource.init):
                        self._compose(
                            plan.env,
                            "run",
                            "--rm",
                            "--no-deps",
                            f"{service.name}--{resource.id}--init-{index}",
                        )
                self._compose(plan.env, "up", "-d", "--no-deps", service.name)
            current = None
            networks = self._ids("network", plan.env)
            proxies = self._ids("container", None, "dev.phub.service=proxy")
            if len(proxies) != 1:
                raise OSError("Expected one managed phub-proxy container")
            for network in networks:
                attached = json.loads(self._docker("network", "inspect", network))[
                    0
                ].get("Containers", {})
                if not any(
                    item.get("Name") == "phub-proxy" for item in attached.values()
                ):
                    self._docker("network", "connect", network, proxies[0])
            return RunResult()
        except OSError as exc:
            return RunResult(False, str(exc), current, str(exc)[-2000:])

    def health(self, env: str) -> dict[str, Health]:
        result: dict[str, Health] = {}
        for ident in self._ids("container", env, "dev.phub.role=service"):
            info = json.loads(self._docker("container", "inspect", ident))[0]
            labels, state = info["Config"]["Labels"], info["State"]
            service = labels["dev.phub.service"]
            check = json.loads(labels["dev.phub.health"])
            if not state.get("Running"):
                result[service] = Health.UNHEALTHY
            elif "http" in check:
                try:
                    self._docker(
                        "run",
                        "--rm",
                        "--memory",
                        "32m",
                        "--network",
                        f"phub-{env}",
                        "--label",
                        "dev.phub.managed=true",
                        "--label",
                        f"dev.phub.env={env}",
                        "--label",
                        f"dev.phub.service={service}",
                        "curlimages/curl:8.12.1",
                        "--fail",
                        "--silent",
                        "--show-error",
                        "--max-time",
                        "5",
                        f"http://{service}:{labels['dev.phub.port']}/{check['http'].lstrip('/')}",
                        timeout=30,
                    )
                    result[service] = Health.HEALTHY
                except OSError:
                    result[service] = Health.STARTING
            else:
                result[service] = {
                    "healthy": Health.HEALTHY,
                    "unhealthy": Health.UNHEALTHY,
                }.get(state.get("Health", {}).get("Status"), Health.STARTING)
        return result

    def inventory(self, env: str | None = None) -> Inventory:
        return Inventory(
            *(
                self._ids(kind, env)
                for kind in ("container", "network", "volume", "image")
            )
        )

    def destroy(self, env: str) -> Inventory:
        inventory = self.inventory(env)
        proxies = self._ids("container", None, "dev.phub.service=proxy")
        for network in inventory.networks:
            attached = json.loads(self._docker("network", "inspect", network))[0].get(
                "Containers", {}
            )
            for proxy in proxies:
                if any(ident.startswith(proxy) for ident in attached):
                    self._docker("network", "disconnect", "-f", network, proxy)
        # A stale/corrupt Compose file cannot prevent a label-scoped sweep.
        if self._file(env).exists() and inventory.containers:
            try:
                if self._owns_compose_objects(env, inventory):
                    self._compose(env, "down", "-v")
            except (OSError, ValueError, KeyError):
                pass
        remaining = self.inventory(env)
        for kind, ids in [
            ("container", remaining.containers),
            ("network", remaining.networks),
            ("volume", remaining.volumes),
            ("image", remaining.images),
        ]:
            for ident in ids:
                self._docker(
                    kind, "rm", *(["-f"] if kind == "container" else []), ident
                )
        return self.inventory(env)

    def _owns_compose_objects(self, env: str, inventory: Inventory) -> bool:
        project = self._compose(env, "ps", "-aq").split()
        config = json.loads(self._compose(env, "config", "--format", "json"))
        if not all(
            any(ident.startswith(owned) for owned in inventory.containers)
            for ident in project
        ):
            return False
        for kind, ids, field in [
            ("network", inventory.networks, "networks"),
            ("volume", inventory.volumes, "volumes"),
        ]:
            owned = {
                json.loads(self._docker(kind, "inspect", ident))[0]["Name"]
                for ident in ids
            }
            configured = {
                item["name"]
                for item in config.get(field, {}).values()
                if not item.get("external")
            }
            if not configured <= owned:
                return False
        return True

    def logs(self, env: str, service: str, tail: int = 100) -> str:
        return "\n".join(
            self._docker("logs", "--tail", str(tail), ident)
            for ident in self._ids(
                "container", env, f"dev.phub.service={service}", "dev.phub.role=service"
            )
        )

    def gc_images(
        self, retained: set[str], keep_per_service: int = 3
    ) -> tuple[str, ...]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for ident in self._ids("image"):
            info = json.loads(self._docker("image", "inspect", ident))[0]
            service = info["Config"]["Labels"].get("dev.phub.service")
            if service:
                groups.setdefault(service, []).append(info)
        removed: list[str] = []
        for images in groups.values():
            for info in sorted(images, key=lambda i: i["Created"], reverse=True)[
                keep_per_service:
            ]:
                if not retained.intersection(info.get("RepoTags") or []):
                    self._docker("image", "rm", info["Id"])
                    removed.append(info["Id"])
        return tuple(removed)
