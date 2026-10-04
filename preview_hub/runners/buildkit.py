"""Image builder for the Kubernetes runner: BuildKit builds, an in-cluster registry stores.

The hub sends the pinned checkout to ``buildkitd`` (``buildctl --local``), which pushes to the
registry by its cluster name. Nodes pull the same repository by ``localhost:5000``: the k3s
node runs the Docker runtime, which cannot resolve cluster DNS, and the registry is published
on the node's loopback only (``hostIP: 127.0.0.1``) so it is never reachable from outside.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ..contracts import ServiceManifest

Executor = Callable[[list[str], int], subprocess.CompletedProcess[str]]
# method, url, headers -> (status, headers, body)
Http = Callable[[str, str, dict[str, str]], tuple[int, dict[str, str], bytes]]

MANIFEST_TYPES = (
    "application/vnd.oci.image.manifest.v1+json,"
    "application/vnd.docker.distribution.manifest.v2+json,"
    "application/vnd.oci.image.index.v1+json,"
    "application/vnd.docker.distribution.manifest.list.v2+json"
)
TAG = re.compile(r"[0-9a-f]{12}")


def execute(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=False
    )


def http(
    method: str, url: str, headers: dict[str, str]
) -> tuple[int, dict[str, str], bytes]:
    try:
        with urlopen(Request(url, method=method, headers=headers), timeout=30) as reply:
            return reply.status, dict(reply.headers.items()), reply.read()
    except HTTPError as exc:
        return exc.code, dict(exc.headers.items()), b""


class BuildKitBuilder:
    def __init__(
        self,
        addr: str = "tcp://buildkitd:1234",
        registry: str = "registry:5000",
        pull_registry: str = "localhost:5000",
        executor: Executor = execute,
        request: Http = http,
    ):
        self.addr, self.registry, self.pull_registry = addr, registry, pull_registry
        self.executor, self.request = executor, request

    def _api(self, method: str, path: str, accept: str = MANIFEST_TYPES):
        return self.request(
            method, f"http://{self.registry}/v2/{path}", {"Accept": accept}
        )

    def __call__(
        self, service: str, commit: str, source: Path, manifest: ServiceManifest
    ) -> str:
        repo, tag = f"phub/{service}", commit[:12]
        pulled = f"{self.pull_registry}/{repo}:{tag}"
        # Commit-addressed tags are immutable: an existing one is reused, as in Compose.
        if self._api("HEAD", f"{repo}/manifests/{tag}")[0] == 200:
            return pulled
        dockerfile = source / manifest.build["dockerfile"]
        args = [
            "buildctl",
            "--addr",
            self.addr,
            "build",
            "--frontend",
            "dockerfile.v0",
            "--local",
            f"context={source / manifest.build['context']}",
            "--local",
            f"dockerfile={dockerfile.parent}",
            "--opt",
            f"filename={dockerfile.name}",
            "--opt",
            "label:dev.phub.managed=true",
            "--opt",
            f"label:dev.phub.service={service}",
        ]
        for key, value in manifest.build.get("args", {}).items():
            args.extend(["--opt", f"build-arg:{key}={value}"])
        args.extend(
            [
                "--output",
                f"type=image,name={self.registry}/{repo}:{tag},push=true,registry.insecure=true",
            ]
        )
        try:
            result = self.executor(args, 1800)
        except subprocess.TimeoutExpired as exc:
            raise OSError(f"buildctl timed out for {service}@{tag}") from exc
        if result.returncode:
            raise OSError(
                f"buildctl failed ({result.returncode}) for {service}@{tag}: "
                f"{result.stderr[-4000:]}"
            )
        return pulled

    def _json(self, path: str, accept: str = MANIFEST_TYPES) -> dict[str, Any]:
        status, _, body = self._api("GET", path, accept)
        if status != 200:
            raise OSError(f"Registry GET {path} returned {status}")
        return cast(dict[str, Any], json.loads(body))

    def _created(self, repo: str, tag: str) -> str:
        manifest = self._json(f"{repo}/manifests/{tag}")
        if "manifests" in manifest:  # index: any platform's config carries the date
            manifest = self._json(
                f"{repo}/manifests/{manifest['manifests'][0]['digest']}"
            )
        config = self._json(f"{repo}/blobs/{manifest['config']['digest']}", "*/*")
        return str(config.get("created", ""))

    def _digest(self, repo: str, tag: str) -> str | None:
        status, headers, _ = self._api("HEAD", f"{repo}/manifests/{tag}")
        lowered = {k.lower(): v for k, v in headers.items()}
        return lowered.get("docker-content-digest") if status == 200 else None

    def gc_images(
        self, retained: set[str], keep_per_service: int = 3
    ) -> tuple[str, ...]:
        """Keep the newest tags per service and anything an environment still uses.

        Deleting a manifest only unlinks it; the registry's own garbage-collect frees blobs.
        """
        removed: list[str] = []
        catalog = self._json("_catalog", "application/json")
        listed = cast(list[Any], catalog.get("repositories") or [])
        repos = [str(r) for r in listed if str(r).startswith("phub/")]
        for repo in repos:
            found = self._json(f"{repo}/tags/list", "application/json")
            tags = [
                str(t)
                for t in cast(list[Any], found.get("tags") or [])
                if TAG.fullmatch(str(t))
            ]
            dated = sorted(tags, key=lambda t: self._created(repo, t), reverse=True)
            digests = {t: self._digest(repo, t) for t in dated}
            keep = set(dated[:keep_per_service]) | {
                t for t in dated if f"{self.pull_registry}/{repo}:{t}" in retained
            }
            # A manifest delete removes every tag on that digest — never one we keep.
            protected = {digests[t] for t in keep}
            for tag in dated:
                digest = digests[tag]
                if tag in keep or not digest or digest in protected:
                    continue
                if self._api("DELETE", f"{repo}/manifests/{digest}")[0] not in (
                    200,
                    202,
                ):
                    logging.getLogger(__name__).warning(
                        "Failed to delete %s:%s from the registry", repo, tag
                    )
                    continue
                protected.add(digest)  # already gone; later tags on it are gone too
                removed.append(f"{self.pull_registry}/{repo}:{tag}")
        return tuple(removed)
