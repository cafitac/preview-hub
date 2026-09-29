import ast
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from preview_hub.contracts import Catalog, CatalogEntry, EnvName, ServiceManifest
from preview_hub.plan import PlanBuilder
from preview_hub.runners.compose import ComposeRunner, render, vm_free_bytes


class Docker:
    def __init__(self):
        self.calls = []
        self.responses = {}

    def __call__(self, args, timeout):
        assert timeout > 0
        assert all(type(arg) is str for arg in args)
        self.calls.append(args)
        output = self.responses.get(tuple(args[1:]), "")
        if args[1:3] == ["info", "--format"]:
            output = "colima-preview-hub\n"
        return subprocess.CompletedProcess(args, 0, output, "")


class TypedString(str):
    pass


@pytest.fixture(params=[str, TypedString])
def plan(tmp_path, request):
    manifests = {
        name: ServiceManifest.parse(
            yaml.safe_load(Path(f"tests/fixtures/{name}.yaml").read_text())
        )
        for name in map(request.param, ("backend", "frontend"))
    }
    return PlanBuilder().build(
        EnvName("test-one"),
        manifests,
        Catalog(
            {name: CatalogEntry(f"org/{name}", "main") for name in manifests},
            "http://{subdomain}.{env}.localhost:18080",
        ),
        {name: "a" * 40 for name in manifests},
        {name: tmp_path for name in manifests},
        {name: f"phub/{name}:aaaaaaaaaaaa" for name in manifests},
    )


def assert_plain(value):
    assert type(value) in (str, int, bool, list, dict)
    if isinstance(value, dict):
        for key, item in value.items():
            assert_plain(key)
            assert_plain(item)
    elif isinstance(value, list):
        for item in value:
            assert_plain(item)


def test_render_golden(plan):
    assert isinstance(plan.env, EnvName)
    document = render(plan)
    assert_plain(document)
    assert yaml.safe_load(yaml.safe_dump(document)) == document
    assert render(plan) == yaml.safe_load(Path("tests/golden/compose.yaml").read_text())
    for section in ("services", "networks", "volumes"):
        for item in render(plan)[section].values():
            assert item["labels"]["dev.phub.managed"] == "true"
            assert item["labels"]["dev.phub.env"] == "test-one"
            assert item["labels"]["dev.phub.service"]


def test_apply_order_and_unchanged(plan, tmp_path):
    docker = Docker()
    docker.responses[
        (
            "container",
            "ls",
            "-q",
            "-a",
            "--filter",
            "label=dev.phub.managed=true",
            "--filter",
            "label=dev.phub.service=proxy",
        )
    ] = "proxy-id"
    runner = ComposeRunner(tmp_path, executor=docker)
    assert runner.apply(plan).success
    compose = [args[6:] for args in docker.calls if args[1] == "compose"]
    assert compose == [
        ["up", "-d", "--wait", "--wait-timeout", "90", "backend--db"],
        ["run", "--rm", "--no-deps", "backend--db--init-0"],
        ["run", "--rm", "--no-deps", "backend--db--init-1"],
        ["up", "-d", "--no-deps", "backend"],
        ["up", "-d", "--no-deps", "frontend"],
    ]
    docker.calls.clear()
    assert runner.apply(
        replace(plan, services=tuple(replace(s, changed=False) for s in plan.services))
    ).success
    assert not any(args[1] == "compose" for args in docker.calls)


def test_identity_guard(tmp_path):
    def wrong(args, timeout):
        return subprocess.CompletedProcess(args, 0, "colima-default", "")

    with pytest.raises(ValueError, match="daemon mismatch"):
        ComposeRunner(tmp_path, executor=wrong)


def test_inventory_and_stray_destroy_are_scoped(tmp_path):
    docker = Docker()
    runner = ComposeRunner(tmp_path, executor=docker)
    key = (
        "container",
        "ls",
        "-q",
        "-a",
        "--filter",
        "label=dev.phub.managed=true",
        "--filter",
        "label=dev.phub.env=test-one",
    )
    docker.responses[key] = "owned-id"
    runner.destroy("test-one")
    assert ["docker", "container", "rm", "-f", "owned-id"] in docker.calls
    for args in docker.calls:
        if "ls" in args:
            assert "label=dev.phub.managed=true" in args
            assert (
                "label=dev.phub.env=test-one" in args
                or "label=dev.phub.service=proxy" in args
            )
    docker.calls.clear()
    runner.inventory()
    assert all("label=dev.phub.managed=true" in args for args in docker.calls)


def test_build_skip_and_stderr(plan, tmp_path):
    docker = Docker()
    runner = ComposeRunner(tmp_path, executor=docker)
    docker.responses[
        (
            "image",
            "ls",
            "-q",
            "--filter",
            "label=dev.phub.managed=true",
            "--filter",
            "label=dev.phub.service=backend",
        )
    ] = "image-id"
    docker.responses[("image", "inspect", "image-id")] = json.dumps(
        [{"RepoTags": [plan.services[0].image]}]
    )
    service = plan.services[0]
    assert (
        runner.build(service.name, service.commit, service.source, service.manifest)
        == service.image
    )
    assert not any(args[1] == "build" for args in docker.calls)

    def failed(args, timeout):
        return subprocess.CompletedProcess(args, 1, "", "specific daemon error")

    runner.executor = failed
    with pytest.raises(OSError, match="specific daemon error"):
        runner.inventory()


def test_vm_disk_and_import_boundary(tmp_path):
    assert vm_free_bytes(tmp_path) > 0
    tree = ast.parse(Path("preview_hub/lifecycle.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert "runners" not in (node.module or "")
        elif isinstance(node, ast.Import):
            assert all("runners" not in item.name for item in node.names)


@pytest.mark.parametrize("foreign", [False, True])
def test_compose_down_requires_all_objects_owned(tmp_path, foreign):
    docker = Docker()
    runner = ComposeRunner(tmp_path, executor=docker)
    runner._file("test-one").parent.mkdir(parents=True)
    runner._file("test-one").write_text("services: {}")
    prefix = ("compose", "-f", str(runner._file("test-one")), "-p", "phub-test-one")
    docker.responses[(*prefix, "ps", "-aq")] = "other-id" if foreign else "owned-id"
    docker.responses[(*prefix, "config", "--format", "json")] = "{}"
    key = (
        "container",
        "ls",
        "-q",
        "-a",
        "--filter",
        "label=dev.phub.managed=true",
        "--filter",
        "label=dev.phub.env=test-one",
    )
    docker.responses[key] = "owned-id"
    runner.destroy("test-one")
    assert (["docker", *prefix, "down", "-v"] in docker.calls) is not foreign
    assert not any("other-id" in args for args in docker.calls)


def test_init_failure_stops_service_start(plan, tmp_path):
    docker = Docker()

    def fail_init(args, timeout):
        result = docker(args, timeout)
        if "run" in args:
            return subprocess.CompletedProcess(args, 1, "", "migration failed")
        return result

    runner = ComposeRunner(tmp_path, executor=fail_init)
    result = runner.apply(plan)
    assert not result.success and result.service == "backend"
    assert "migration failed" in result.log_excerpt
    assert not any(args[-1] == "frontend" for args in docker.calls)
    assert not any(args[-1] == "backend" for args in docker.calls)


def test_http_health_probe_and_logs(tmp_path):
    from preview_hub.runner import Health

    docker = Docker()
    runner = ComposeRunner(tmp_path, executor=docker)
    docker.responses[
        (
            "container",
            "ls",
            "-q",
            "-a",
            "--filter",
            "label=dev.phub.managed=true",
            "--filter",
            "label=dev.phub.role=service",
            "--filter",
            "label=dev.phub.env=test-one",
        )
    ] = "backend-id"
    docker.responses[("container", "inspect", "backend-id")] = json.dumps(
        [
            {
                "Config": {
                    "Labels": {
                        "dev.phub.service": "backend",
                        "dev.phub.health": '{"http":"/healthz"}',
                        "dev.phub.port": "8000",
                    }
                },
                "State": {"Running": True},
            }
        ]
    )
    assert runner.health("test-one") == {"backend": Health.HEALTHY}
    probe = next(args for args in docker.calls if args[1] == "run")
    assert "phub-test-one" in probe and "dev.phub.env=test-one" in probe
    assert probe[-1] == "http://backend:8000/healthz"
    image = "curlimages/curl:8.12.1"
    assert image in probe
    bootstrap = Path("scripts/vm-bootstrap.sh").read_text()
    pull = f'"$docker" --context colima-preview-hub pull {image}'
    assert pull in bootstrap
    assert bootstrap.index(pull) < bootstrap.index("compose -p phub-hub")

    def stderr_logs(args, timeout):
        return subprocess.CompletedProcess(args, 0, "stdout", "stderr")

    runner.executor = stderr_logs
    assert runner._docker("logs", "backend-id") == "stdoutstderr"


def test_proxy_disconnect_before_removal(tmp_path):
    docker = Docker()
    runner = ComposeRunner(tmp_path, executor=docker)
    docker.responses[
        (
            "network",
            "ls",
            "-q",
            "--filter",
            "label=dev.phub.managed=true",
            "--filter",
            "label=dev.phub.env=test-one",
        )
    ] = "network-id"
    docker.responses[
        (
            "container",
            "ls",
            "-q",
            "-a",
            "--filter",
            "label=dev.phub.managed=true",
            "--filter",
            "label=dev.phub.service=proxy",
        )
    ] = "abc123"
    docker.responses[("network", "inspect", "network-id")] = json.dumps(
        [{"Containers": {"abc123full": {"Name": "phub-proxy"}}}]
    )
    runner.destroy("test-one")
    disconnect = ["docker", "network", "disconnect", "-f", "network-id", "abc123"]
    remove = ["docker", "network", "rm", "network-id"]
    assert docker.calls.index(disconnect) < docker.calls.index(remove)
    assert not any(args[:3] == ["docker", "container", "rm"] for args in docker.calls)


def test_gc_preserves_active_and_recent_images(tmp_path):
    docker = Docker()
    runner = ComposeRunner(tmp_path, executor=docker)
    docker.responses[
        ("image", "ls", "-q", "--filter", "label=dev.phub.managed=true")
    ] = "one two three four five"
    for index, name in enumerate(["one", "two", "three", "four", "five"]):
        docker.responses[("image", "inspect", name)] = json.dumps(
            [
                {
                    "Id": name,
                    "RepoTags": [f"phub/backend:{index:012x}"],
                    "Created": str(index),
                    "Config": {"Labels": {"dev.phub.service": "backend"}},
                }
            ]
        )
    assert runner.gc_images({"phub/backend:000000000000"}) == (
        "phub/backend:000000000001",
    )
    assert ["docker", "image", "rm", "phub/backend:000000000001"] in docker.calls


def test_timeout_reports_stderr(tmp_path):
    docker = Docker()
    runner = ComposeRunner(tmp_path, executor=docker)

    def timeout(args, seconds):
        raise subprocess.TimeoutExpired(args, seconds, stderr="daemon stalled")

    runner.executor = timeout
    with pytest.raises(OSError, match="daemon stalled"):
        runner.inventory()


def test_build_uses_buildkit_and_loads_image(plan, tmp_path):
    docker = Docker()
    runner = ComposeRunner(tmp_path, executor=docker)
    service = plan.services[0]
    runner.build(service.name, service.commit, service.source, service.manifest)
    build = next(args for args in docker.calls if args[1] == "buildx")
    assert build[1:4] == ["buildx", "build", "--load"]
    assert "cli-plugins/docker-buildx" in Path("Dockerfile").read_text()


@pytest.mark.parametrize("timeout,retries", [("90s", 45), ("300s", 150), ("301s", 151)])
def test_cmd_healthcheck_respects_manifest_deadline(plan, timeout, retries):
    service = plan.services[0]
    service = replace(
        service,
        manifest=replace(
            service.manifest, health={"cmd": ["check-ready"], "timeout": timeout}
        ),
    )
    document = render(replace(plan, services=(service,)))
    check = document["services"][service.name]["healthcheck"]
    assert check == {
        "test": ["CMD", "check-ready"],
        "interval": "2s",
        "timeout": "5s",
        "retries": retries,
    }
    # Even immediate failures cannot exhaust retries before the deadline.
    assert retries * 2 >= int(timeout[:-1])


@pytest.mark.parametrize("failure", ["network", "proxy"])
def test_environment_apply_failure_has_no_service(plan, tmp_path, failure):
    docker = Docker()

    def fail_environment(args, timeout):
        result = docker(args, timeout)
        if failure == "network" and args[1:3] == ["network", "ls"]:
            return subprocess.CompletedProcess(args, 1, "", "network discovery failed")
        return result

    result = ComposeRunner(tmp_path, executor=fail_environment).apply(plan)
    assert not result.success
    assert result.service is None
    assert (
        "network discovery failed"
        if failure == "network"
        else "Expected one managed phub-proxy"
    ) in result.log_excerpt


@pytest.mark.parametrize("retain_first", [True, False])
def test_gc_removes_stale_tags_from_shared_image(tmp_path, retain_first):
    docker = Docker()
    runner = ComposeRunner(tmp_path, executor=docker)
    tags = ["phub/backend:aaaaaaaaaaaa", "phub/backend:bbbbbbbbbbbb"]
    docker.responses[
        ("image", "ls", "-q", "--filter", "label=dev.phub.managed=true")
    ] = "shared"
    docker.responses[("image", "inspect", "shared")] = json.dumps(
        [
            {
                "Id": "shared",
                "RepoTags": [*tags, "other:latest", "phub/backend:latest"],
                "Created": "1",
                "Config": {"Labels": {"dev.phub.service": "backend"}},
            }
        ]
    )
    retained = {tags[0]} if retain_first else set()
    expected = tags[1:] if retain_first else tags
    assert runner.gc_images(retained, keep_per_service=0) == tuple(expected)
    assert [call for call in docker.calls if call[1:3] == ["image", "rm"]] == [
        ["docker", "image", "rm", tag] for tag in expected
    ]


def test_gc_logs_failed_tag_removal_and_continues(tmp_path, caplog):
    docker = Docker()
    runner = ComposeRunner(tmp_path, executor=docker)
    tags = [f"phub/backend:{index:012x}" for index in range(3)]
    docker.responses[
        ("image", "ls", "-q", "--filter", "label=dev.phub.managed=true")
    ] = "shared other"
    for ident, repo_tags, created in [
        ("shared", tags[:2], "2"),
        ("other", tags[2:], "1"),
    ]:
        docker.responses[("image", "inspect", ident)] = json.dumps(
            [
                {
                    "Id": ident,
                    "RepoTags": repo_tags,
                    "Created": created,
                    "Config": {"Labels": {"dev.phub.service": "backend"}},
                }
            ]
        )

    def fail_first(args, timeout):
        result = docker(args, timeout)
        if args[1:] == ["image", "rm", tags[0]]:
            return subprocess.CompletedProcess(args, 1, "", "image in use")
        return result

    runner.executor = fail_first
    assert runner.gc_images(set(), keep_per_service=0) == tuple(tags[1:])
    assert tags[0] in caplog.text
    assert "image in use" in caplog.text
    assert [call for call in docker.calls if call[1:3] == ["image", "rm"]] == [
        ["docker", "image", "rm", tag] for tag in tags
    ]
