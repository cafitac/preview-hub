import json
import subprocess
from pathlib import Path

import pytest
import yaml

from preview_hub.cli import create_context
from preview_hub.contracts import ServiceManifest
from preview_hub.runners.buildkit import BuildKitBuilder

COMMIT = "abcdef012345" + "0" * 28


def manifest(args=None) -> ServiceManifest:
    data = yaml.safe_load(Path("tests/fixtures/backend.yaml").read_text())
    data["build"] = {
        "context": ".",
        "dockerfile": "docker/Dockerfile",
        "args": args or {},
    }
    return ServiceManifest.parse(data)


class Registry:
    """Answers the Distribution API calls the builder makes; records every request."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.manifests: dict[
            tuple[str, str], tuple[str, str]
        ] = {}  # (repo, tag) -> (digest, created)
        self.deleted: list[str] = []

    def add(self, repo, tag, digest, created):
        self.manifests[(repo, tag)] = (digest, created)

    def __call__(self, method, url, headers):
        path = url.split("/v2/", 1)[1]
        self.calls.append((method, path))
        if path == "_catalog":
            repos = sorted({r for r, _ in self.manifests} | {"other/app"})
            return 200, {}, json.dumps({"repositories": repos}).encode()
        repo, _, rest = (
            path.rpartition("/manifests/") if "/manifests/" in path else ("", "", "")
        )
        if path.endswith("/tags/list"):
            repo = path[: -len("/tags/list")]
            tags = [t for r, t in self.manifests if r == repo] + ["latest"]
            return 200, {}, json.dumps({"tags": tags}).encode()
        if "/blobs/" in path:
            digest = path.rsplit("/", 1)[1]
            created = next(
                c for d, c in self.manifests.values() if f"cfg-{d}" == digest
            )
            return 200, {}, json.dumps({"created": created}).encode()
        if repo:
            if method == "DELETE":
                self.deleted.append(f"{repo}@{rest}")
                return 202, {}, b""
            found = self.manifests.get((repo, rest))
            if not found:
                return 404, {}, b""
            digest, _ = found
            body = json.dumps({"config": {"digest": f"cfg-{digest}"}}).encode()
            return (
                200,
                {"Docker-Content-Digest": digest},
                body if method == "GET" else b"",
            )
        raise AssertionError(path)


class Buildctl:
    def __init__(self, code=0):
        self.calls = []
        self.code = code

    def __call__(self, args, timeout):
        assert timeout == 1800
        self.calls.append(args)
        return subprocess.CompletedProcess(args, self.code, "", "boom")


def test_build_pushes_by_cluster_name_and_returns_node_ref(tmp_path):
    registry, buildctl = Registry(), Buildctl()
    builder = BuildKitBuilder(executor=buildctl, request=registry)
    ref = builder("backend", COMMIT, tmp_path, manifest({"MODE": "preview"}))
    assert ref == "localhost:5000/phub/backend:abcdef012345"
    assert registry.calls == [("HEAD", "phub/backend/manifests/abcdef012345")]
    args = buildctl.calls[0]
    assert args[:4] == ["buildctl", "--addr", "tcp://buildkitd:1234", "build"]
    assert f"context={tmp_path}" in args
    assert f"dockerfile={tmp_path}/docker" in args
    assert "filename=Dockerfile" in args
    assert "build-arg:MODE=preview" in args
    assert "label:dev.phub.service=backend" in args
    assert args[-1] == (
        "type=image,name=registry:5000/phub/backend:abcdef012345,"
        "push=true,registry.insecure=true"
    )


def test_existing_tag_is_reused(tmp_path):
    registry, buildctl = Registry(), Buildctl()
    registry.add("phub/backend", "abcdef012345", "sha256:a", "2026-10-01")
    ref = BuildKitBuilder(executor=buildctl, request=registry)(
        "backend", COMMIT, tmp_path, manifest()
    )
    assert ref == "localhost:5000/phub/backend:abcdef012345"
    assert buildctl.calls == []


def test_build_failure_is_os_error(tmp_path):
    with pytest.raises(OSError, match="buildctl failed"):
        BuildKitBuilder(executor=Buildctl(code=1), request=Registry())(
            "backend", COMMIT, tmp_path, manifest()
        )


def test_gc_keeps_newest_and_retained_and_shared_digests():
    registry = Registry()
    for i, day in enumerate(["01", "02", "03", "04", "05"]):
        registry.add("phub/backend", f"{i:012x}", f"sha256:{i}", f"2026-10-{day}")
    # A tag on the same image as the retained one: deleting it would delete both.
    registry.add("phub/backend", "aaaaaaaaaaaa", "sha256:0", "2026-10-01")
    retained = {"localhost:5000/phub/backend:000000000000"}
    removed = BuildKitBuilder(request=registry).gc_images(retained, keep_per_service=2)
    # newest two: …004 (10-05), …003 (10-04); …000 retained; …001, …002 go
    assert removed == (
        "localhost:5000/phub/backend:000000000002",
        "localhost:5000/phub/backend:000000000001",
    )
    assert registry.deleted == ["phub/backend@sha256:2", "phub/backend@sha256:1"]
    assert all(not d.startswith("other/") for d in registry.deleted)


def test_cli_wires_kubernetes_runner(tmp_path, monkeypatch):
    from preview_hub.runners import kubernetes
    from preview_hub.runners.fake import FakeRunner

    seen = {}

    def factory(state_dir, builder, auth_url, hub_namespace):
        seen.update(
            state_dir=state_dir,
            addr=builder.addr,
            registry=builder.registry,
            pull=builder.pull_registry,
            auth_url=auth_url,
            hub_namespace=hub_namespace,
        )
        return FakeRunner()

    monkeypatch.setattr(kubernetes, "KubernetesRunner", factory)
    monkeypatch.delenv("PHUB_HEALTH_POLL_INTERVAL", raising=False)
    monkeypatch.setenv("PHUB_RUNNER", "kubernetes")
    monkeypatch.setenv("PHUB_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("PHUB_CATALOG", "deploy/hub-stack/catalog.yaml")
    monkeypatch.setenv("PHUB_REGISTRY", "registry.preview-hub:5000")
    ctx = create_context()
    assert seen == {
        "state_dir": tmp_path,
        "addr": "tcp://buildkitd:1234",
        "registry": "registry.preview-hub:5000",
        "pull": "localhost:5000",
        "auth_url": "http://hub.preview-hub.svc.cluster.local:8080/auth/verify",
        "hub_namespace": "preview-hub",
    }
    assert ctx.free_space() > 0
    assert ctx.poll_interval == 2


def test_runner_gc_delegates_to_builder(tmp_path):
    from preview_hub.runners.kubernetes import KubernetesRunner

    def kubectl(args, timeout, stdin=None):
        return subprocess.CompletedProcess(args, 0, "", "")

    class Collecting:
        def gc_images(self, retained, keep):
            return (f"{len(retained)}:{keep}",)

    hub = KubernetesRunner(tmp_path, builder=Collecting(), executor=kubectl)  # type: ignore[arg-type]
    assert hub.gc_images({"x"}, 3) == ("1:3",)
    assert KubernetesRunner(tmp_path, executor=kubectl).gc_images(set()) == ()
