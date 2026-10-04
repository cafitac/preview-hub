"""Kubernetes adapter. One environment is one namespace ``phub-<env>``.

Every object the hub creates carries the plan's ownership labels, and every discovery or
teardown query is restricted to them — the same rule as the Docker adapter. Deleting the
namespace is the whole teardown; ``inventory`` is the authority that it finished.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import yaml

from ..contracts import EnvName, ServiceManifest, duration
from ..runner import EnvironmentPlan, Health, Inventory, ResourcePlan, RunResult

Builder = Callable[[str, str, Path, ServiceManifest], str]
# argv, timeout seconds, stdin (manifests for `apply -f -`)
Executor = Callable[[list[str], int, str | None], subprocess.CompletedProcess[str]]


def execute(
    args: list[str], timeout: int, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, input=stdin, capture_output=True, text=True, timeout=timeout, check=False
    )


ROLE = "dev.phub.role"
# Pod states that will not recover on their own. Anything else that is not ready is STARTING.
FATAL_WAITING = {
    "CrashLoopBackOff",
    "ErrImagePull",
    "ImagePullBackOff",
    "ErrImageNeverPull",
    "InvalidImageName",
    "CreateContainerConfigError",
    "CreateContainerError",
}
RESOURCE_MEMORY = "512Mi"
PROBE_PERIOD = 2


def namespace(env: str) -> str:
    return f"phub-{EnvName(env)}"


def _quantity(value: str) -> int:
    """Bytes for the manifest's ``<n>Mi``/``<n>Gi`` memory strings."""
    return int(value[:-2]) * (1024 ** (2 if value.endswith("Mi") else 3))


def _mi(total: int) -> str:
    return f"{math.ceil(total / 1024**2)}Mi"


def _revision(*parts: Any) -> str:
    """Deterministic pod-template stamp: a changed image or env rolls the Deployment."""
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]


def _probes(check: dict[str, Any], port: int) -> dict[str, Any]:
    if "http" in check:
        handler: dict[str, Any] = {
            "httpGet": {"path": "/" + str(check["http"]).lstrip("/"), "port": port}
        }
    else:
        handler = {"exec": {"command": [str(c) for c in check["cmd"]]}}
    # The startup probe carries the manifest deadline; readiness then tracks steady state.
    budget = max(1, math.ceil(duration(str(check["timeout"])) / PROBE_PERIOD))
    return {
        "startupProbe": {
            **handler,
            "periodSeconds": PROBE_PERIOD,
            "timeoutSeconds": 5,
            "failureThreshold": budget,
        },
        "readinessProbe": {**handler, "periodSeconds": 5, "timeoutSeconds": 5},
    }


def _env(values: dict[str, str]) -> list[dict[str, str]]:
    return [{"name": str(k), "value": str(v)} for k, v in values.items()]


def _resource_objects(
    ns: str, resource: ResourcePlan, service_name: str
) -> list[dict[str, Any]]:
    # The resource URL in the plan is postgresql://preview:preview@<service>--<id>:5432 —
    # the Service name below is that host, so manifests need no runner-specific value.
    host = f"{service_name}--{resource.id}"
    labels = {**resource.labels, ROLE: "resource"}
    selector = {"dev.phub.env": labels["dev.phub.env"], "dev.phub.resource": host}
    pod_labels = {**labels, "dev.phub.resource": host}
    return [
        {
            "apiVersion": "apps/v1",
            "kind": "StatefulSet",
            "metadata": {"name": host, "namespace": ns, "labels": labels},
            "spec": {
                "serviceName": host,
                "replicas": 1,
                "selector": {"matchLabels": selector},
                "template": {
                    "metadata": {"labels": pod_labels},
                    "spec": {
                        "enableServiceLinks": False,
                        "containers": [
                            {
                                "name": "postgres",
                                "image": f"postgres:{resource.version}",
                                "env": _env(
                                    {
                                        "POSTGRES_USER": "preview",
                                        "POSTGRES_PASSWORD": "preview",
                                        "POSTGRES_DB": "preview",
                                        "PGDATA": "/var/lib/postgresql/data/pgdata",
                                    }
                                ),
                                "ports": [{"containerPort": 5432}],
                                "readinessProbe": {
                                    "exec": {
                                        "command": [
                                            "pg_isready",
                                            "-U",
                                            "preview",
                                            "-d",
                                            "preview",
                                        ]
                                    },
                                    "periodSeconds": 2,
                                    "timeoutSeconds": 2,
                                },
                                "resources": {
                                    "requests": {"cpu": "50m", "memory": "128Mi"},
                                    "limits": {"cpu": "1", "memory": RESOURCE_MEMORY},
                                },
                                "volumeMounts": [
                                    {
                                        "name": "data",
                                        "mountPath": "/var/lib/postgresql/data",
                                    }
                                ],
                            }
                        ],
                    },
                },
                "volumeClaimTemplates": [
                    {
                        "metadata": {"name": "data", "labels": labels},
                        "spec": {
                            "accessModes": ["ReadWriteOnce"],
                            "resources": {"requests": {"storage": "1Gi"}},
                        },
                    }
                ],
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": host, "namespace": ns, "labels": labels},
            "spec": {
                "selector": selector,
                "ports": [{"port": 5432, "targetPort": 5432}],
            },
        },
    ]


def init_job_name(service: str, resource: str, index: int) -> str:
    return f"{service}--{resource}--init-{index}"


def _init_jobs(ns: str, plan: EnvironmentPlan) -> dict[str, list[dict[str, Any]]]:
    jobs: dict[str, list[dict[str, Any]]] = {}
    for service in plan.services:
        for resource in service.resources:
            for index, command in enumerate(resource.init):
                labels = {**service.labels, ROLE: "init"}
                jobs.setdefault(service.name, []).append(
                    {
                        "apiVersion": "batch/v1",
                        "kind": "Job",
                        "metadata": {
                            "name": init_job_name(service.name, resource.id, index),
                            "namespace": ns,
                            "labels": labels,
                        },
                        "spec": {
                            "backoffLimit": 0,
                            "template": {
                                "metadata": {"labels": labels},
                                "spec": {
                                    "restartPolicy": "Never",
                                    "enableServiceLinks": False,
                                    "containers": [
                                        {
                                            "name": "init",
                                            "image": service.image,
                                            "imagePullPolicy": "IfNotPresent",
                                            # Same as Compose's entrypoint override.
                                            "command": [str(c) for c in command],
                                            "env": _env(service.env),
                                            "resources": {
                                                "requests": {
                                                    "cpu": "50m",
                                                    "memory": "64Mi",
                                                },
                                                "limits": {
                                                    "cpu": "1",
                                                    "memory": service.memory,
                                                },
                                            },
                                        }
                                    ],
                                },
                            },
                        },
                    }
                )
    return jobs


def render(plan: EnvironmentPlan, auth_url: str) -> dict[str, list[dict[str, Any]]]:
    """Objects grouped by apply step: ``shared``, then per service in plan order.

    ``auth_url`` is the hub's ``/auth/verify`` endpoint that Traefik's ForwardAuth calls for
    public routes (Cloudflare Access JWT check), replacing the Docker label middleware.
    """
    ns = namespace(plan.env)
    shared_labels = {**plan.labels, "dev.phub.service": "shared"}
    memory = sum(_quantity(s.memory) for s in plan.services) + len(
        plan.resources
    ) * _quantity(RESOURCE_MEMORY)
    # One init Job runs beside the running services; Recreate keeps rollouts in budget.
    largest = max((_quantity(s.memory) for s in plan.services), default=0)
    containers = len(plan.services) + len(plan.resources) + 1
    groups: dict[str, list[dict[str, Any]]] = {
        "shared": [
            {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {"name": ns, "labels": shared_labels},
            },
            {
                "apiVersion": "v1",
                "kind": "ResourceQuota",
                "metadata": {
                    "name": "environment",
                    "namespace": ns,
                    "labels": shared_labels,
                },
                "spec": {
                    "hard": {
                        "limits.memory": _mi(memory + largest),
                        "limits.cpu": str(containers),
                        "requests.storage": f"{max(1, len(plan.resources))}Gi",
                    }
                },
            },
            {
                "apiVersion": "networking.k8s.io/v1",
                "kind": "NetworkPolicy",
                "metadata": {
                    "name": "environment",
                    "namespace": ns,
                    "labels": shared_labels,
                },
                "spec": {
                    "podSelector": {},
                    "policyTypes": ["Ingress"],
                    "ingress": [
                        {"from": [{"podSelector": {}}]},
                        {
                            "from": [
                                {
                                    "namespaceSelector": {
                                        "matchLabels": {
                                            "kubernetes.io/metadata.name": "kube-system"
                                        }
                                    },
                                    "podSelector": {
                                        "matchLabels": {
                                            "app.kubernetes.io/name": "traefik"
                                        }
                                    },
                                }
                            ]
                        },
                    ],
                },
            },
        ]
    }
    jobs = _init_jobs(ns, plan)
    for service in plan.services:
        labels = {**service.labels, ROLE: "service"}
        selector = {
            "dev.phub.env": labels["dev.phub.env"],
            "dev.phub.service": service.name,
        }
        container: dict[str, Any] = {
            "name": service.name,
            "image": service.image,
            "imagePullPolicy": "IfNotPresent",
            "env": _env(service.env),
            "ports": [{"containerPort": service.port}],
            "resources": {
                "requests": {"cpu": "50m", "memory": "64Mi"},
                "limits": {"cpu": "1", "memory": service.memory},
            },
            **_probes(dict(service.manifest.health), service.port),
        }
        if service.manifest.run.get("command") is not None:
            # Compose's `command` replaces the image CMD, which is Kubernetes' `args`.
            container["args"] = [str(c) for c in service.manifest.run["command"]]
        objects: list[dict[str, Any]] = []
        for resource in service.resources:
            objects.extend(_resource_objects(ns, resource, service.name))
        objects.extend(jobs.get(service.name, []))
        objects.append(
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {
                    "name": service.name,
                    "namespace": ns,
                    "labels": labels,
                    "annotations": {
                        "dev.phub.health": json.dumps(dict(service.manifest.health)),
                        "dev.phub.port": str(service.port),
                    },
                },
                "spec": {
                    "replicas": 1,
                    "strategy": {"type": "Recreate"},
                    "selector": {"matchLabels": selector},
                    "template": {
                        "metadata": {
                            "labels": labels,
                            "annotations": {
                                "dev.phub.revision": _revision(
                                    service.image, service.env
                                )
                            },
                        },
                        "spec": {
                            # A Service named like an env var prefix would otherwise inject
                            # e.g. BACKEND_PORT=tcp://… into every container.
                            "enableServiceLinks": False,
                            "containers": [container],
                        },
                    },
                },
            }
        )
        objects.append(
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": service.name, "namespace": ns, "labels": labels},
                "spec": {
                    "selector": selector,
                    "ports": [{"port": service.port, "targetPort": service.port}],
                },
            }
        )
        objects.extend(
            _routes(
                ns,
                service.name,
                labels,
                service.public_url,
                service.local_url,
                service.port,
                auth_url,
            )
        )
        groups[service.name] = objects
    return cast(dict[str, list[dict[str, Any]]], json.loads(json.dumps(groups)))


def _routes(
    ns: str,
    name: str,
    labels: dict[str, str],
    public_url: str | None,
    local_url: str | None,
    port: int,
    auth_url: str,
) -> list[dict[str, Any]]:
    if not public_url:
        return []
    url = urlsplit(public_url)
    annotations: dict[str, str] = {}
    middlewares: list[dict[str, Any]] = []
    # With public access configured, only the authenticated public route exists: the
    # Compose-only `.localhost` route has no meaning inside a cluster.
    if local_url:
        auth = f"{name}-auth"
        middlewares.append(
            {
                "apiVersion": "traefik.io/v1alpha1",
                "kind": "Middleware",
                "metadata": {"name": auth, "namespace": ns, "labels": labels},
                "spec": {
                    "forwardAuth": {"address": auth_url, "trustForwardHeader": False}
                },
            }
        )
        chain = [f"{ns}-{auth}@kubernetescrd"]
        if url.path:
            strip = f"{name}-strip"
            middlewares.append(
                {
                    "apiVersion": "traefik.io/v1alpha1",
                    "kind": "Middleware",
                    "metadata": {"name": strip, "namespace": ns, "labels": labels},
                    "spec": {"stripPrefix": {"prefixes": [url.path]}},
                }
            )
            chain.append(f"{ns}-{strip}@kubernetescrd")
        annotations["traefik.ingress.kubernetes.io/router.middlewares"] = ",".join(
            chain
        )
        annotations["traefik.ingress.kubernetes.io/router.priority"] = (
            "100" if url.path else "10"
        )
    return [
        *middlewares,
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {
                "name": name,
                "namespace": ns,
                "labels": labels,
                "annotations": annotations,
            },
            "spec": {
                "rules": [
                    {
                        "host": url.hostname,
                        "http": {
                            "paths": [
                                {
                                    # Prefix matches the path and its subtree, like the
                                    # Compose rule Path(p) || PathPrefix(p/).
                                    "path": url.path or "/",
                                    "pathType": "Prefix",
                                    "backend": {
                                        "service": {
                                            "name": name,
                                            "port": {"number": port},
                                        }
                                    },
                                }
                            ]
                        },
                    }
                ]
            },
        },
    ]


class KubernetesRunner:
    """Runner port backed by ``kubectl`` with server-side apply under one field manager."""

    def __init__(
        self,
        state_dir: Path = Path("/state"),
        builder: Builder | None = None,
        auth_url: str = "http://hub.preview-hub.svc.cluster.local:8080/auth/verify",
        hub_namespace: str = "preview-hub",
        executor: Executor = execute,
    ):
        self.state_dir, self.builder, self.auth_url = state_dir, builder, auth_url
        self.executor = executor
        # Same role as the Docker daemon-name check: refuse to act on the wrong cluster.
        try:
            self._kubectl("get", "namespace", hub_namespace, "-o", "name")
        except OSError as exc:
            raise ValueError(
                f"Kubernetes cluster mismatch: namespace {hub_namespace!r} not found"
            ) from exc

    def _kubectl(self, *args: str, stdin: str | None = None, timeout: int = 120) -> str:
        argv = ["kubectl", *(str(arg) for arg in args)]
        try:
            result = self.executor(argv, timeout, stdin)
        except subprocess.TimeoutExpired as exc:
            raise OSError(f"kubectl timed out: {args}; stderr={exc.stderr!r}") from exc
        if result.returncode:
            raise OSError(
                f"kubectl failed ({result.returncode}): {args}: {result.stderr[-4000:]}"
            )
        return result.stdout

    def _json(self, *args: str) -> dict[str, Any]:
        output = self._kubectl(*args, "-o", "json")
        return cast(dict[str, Any], json.loads(output)) if output.strip() else {}

    def _apply(self, objects: list[dict[str, Any]]) -> None:
        if objects:
            self._kubectl(
                "apply",
                "--server-side",
                "--force-conflicts",
                "--field-manager",
                "phub",
                "-f",
                "-",
                stdin=yaml.safe_dump_all(objects, sort_keys=False),
            )

    def _file(self, env: str) -> Path:
        return self.state_dir / "envs" / EnvName(env) / "kubernetes.yaml"

    def build(
        self, service: str, commit: str, source: Path, manifest: ServiceManifest
    ) -> str:
        if self.builder is None:
            raise OSError("No image builder configured for the Kubernetes runner")
        return self.builder(service, commit, source, manifest)

    def apply(self, plan: EnvironmentPlan) -> RunResult:
        current = None
        ns = namespace(plan.env)
        try:
            groups = render(plan, self.auth_url)
            path = self._file(plan.env)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                yaml.safe_dump_all(
                    [o for objects in groups.values() for o in objects], sort_keys=False
                )
            )
            temporary.replace(path)
            self._apply(groups["shared"])
            for service in plan.services:
                current = service.name
                if not service.changed:
                    continue
                objects = groups[service.name]
                self._apply(
                    [
                        o
                        for o in objects
                        if o["kind"] in ("StatefulSet", "Service")
                        and o["metadata"]["labels"].get(ROLE) == "resource"
                    ]
                )
                for resource in service.resources:
                    self._kubectl(
                        "rollout",
                        "status",
                        "-n",
                        ns,
                        f"statefulset/{service.name}--{resource.id}",
                        "--timeout=90s",
                        timeout=120,
                    )
                for job in (o for o in objects if o["kind"] == "Job"):
                    name = job["metadata"]["name"]
                    # Jobs are immutable; a changed service reruns its init from scratch.
                    self._kubectl(
                        "delete",
                        "job",
                        "-n",
                        ns,
                        name,
                        "--ignore-not-found",
                        "--wait=true",
                    )
                    self._apply([job])
                    self._kubectl(
                        "wait",
                        "-n",
                        ns,
                        "--for=condition=complete",
                        f"job/{name}",
                        "--timeout=600s",
                        timeout=660,
                    )
                self._apply(
                    [
                        o
                        for o in objects
                        if o["metadata"]["labels"].get(ROLE) == "service"
                    ]
                )
            current = None
            self._prune(plan)
            return RunResult()
        except OSError as exc:
            return RunResult(False, str(exc), current, str(exc)[-2000:])

    def _prune(self, plan: EnvironmentPlan) -> None:
        """Remove services an update dropped. Only hub-labelled objects are candidates."""
        keep = ",".join(sorted({"shared", *(s.name for s in plan.services)}))
        self._kubectl(
            "delete",
            "-n",
            namespace(plan.env),
            "deployment,service,ingress,middlewares.traefik.io,statefulset,job,pvc",
            "-l",
            f"dev.phub.managed=true,dev.phub.service notin ({keep})",
            "--ignore-not-found",
            "--wait=false",
        )

    def health(self, env: str) -> dict[str, Health]:
        ns = namespace(env)
        deployments = self._json("get", "deployment", "-n", ns, "-l", f"{ROLE}=service")
        pods = self._json("get", "pod", "-n", ns, "-l", f"{ROLE}=service")
        stuck: set[str] = set()
        for pod in pods.get("items", []):
            for status in pod.get("status", {}).get("containerStatuses", []):
                reason = status.get("state", {}).get("waiting", {}).get("reason")
                if reason in FATAL_WAITING:
                    stuck.add(pod["metadata"]["labels"]["dev.phub.service"])
        result: dict[str, Health] = {}
        for item in deployments.get("items", []):
            service = item["metadata"]["labels"]["dev.phub.service"]
            if service in stuck:
                result[service] = Health.UNHEALTHY
            elif item.get("status", {}).get("readyReplicas", 0) >= 1:
                result[service] = Health.HEALTHY
            else:
                result[service] = Health.STARTING
        return result

    def inventory(self, env: str | None = None) -> Inventory:
        selector = "dev.phub.managed=true" + (
            f",dev.phub.env={EnvName(env)}" if env is not None else ""
        )
        namespaces = tuple(
            self._kubectl("get", "namespace", "-l", selector, "-o", "name").split()
        )
        objects = self._json("get", "pod,pvc", "-A", "-l", selector)
        pods: list[str] = []
        claims: list[str] = []
        for item in objects.get("items", []):
            ref = f"{item['metadata']['namespace']}/{item['metadata']['name']}"
            (pods if item["kind"] == "Pod" else claims).append(ref)
        # Images live in the cluster registry, collected separately (ImageCollector).
        return Inventory(tuple(pods), namespaces, tuple(claims), ())

    def destroy(self, env: str) -> Inventory:
        ns = namespace(env)
        owned = self._kubectl(
            "get",
            "namespace",
            "-l",
            f"dev.phub.managed=true,dev.phub.env={EnvName(env)}",
            "-o",
            "name",
        ).split()
        if f"namespace/{ns}" in owned:
            # Cascades every object, and local-path PVs are reclaimed with their claims.
            self._kubectl(
                "delete",
                "namespace",
                ns,
                "--ignore-not-found",
                "--wait=true",
                "--timeout=300s",
                timeout=330,
            )
        return self.inventory(env)

    def logs(self, env: str, service: str, tail: int = 100) -> str:
        return self._kubectl(
            "logs",
            "-n",
            namespace(env),
            f"deployment/{service}",
            "--tail",
            str(tail),
            "--all-containers",
        )
