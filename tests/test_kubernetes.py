import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from preview_hub.contracts import Catalog, InvalidInput, ServiceManifest
from preview_hub.plan import PlanBuilder
from preview_hub.runner import Health
from preview_hub.runners.kubernetes import KubernetesRunner, namespace, render

AUTH = "http://hub.preview-hub.svc.cluster.local:8080/auth/verify"


def catalog(public: bool) -> Catalog:
    data = {
        "apiVersion": "preview-hub/v1",
        "public_url_template": "http://{subdomain}.{env}.localhost:18080",
        "services": {
            name: {"repo": f"org/{name}", "default_ref": "main"}
            for name in ("backend", "frontend")
        },
        "limits": {
            "max_environments": 5,
            "build_concurrency": 2,
            "default_ttl": "24h",
            "max_ttl": "7d",
        },
    }
    if public:
        data["public_access"] = {
            "host_template": "phub-{env}.cafitac.com",
            "entry_service": "frontend",
            "path_template": "/_svc/{subdomain}",
            "dashboard_host": "preview-hub.cafitac.com",
        }
    return Catalog.parse(data)


def make_plan(tmp_path: Path, public: bool = True):
    manifests = {
        name: ServiceManifest.parse(
            yaml.safe_load(Path(f"tests/fixtures/{name}.yaml").read_text())
        )
        for name in ("backend", "frontend")
    }
    return PlanBuilder().build(
        "test-one",
        manifests,
        catalog(public),
        {name: "a" * 40 for name in manifests},
        {name: tmp_path for name in manifests},
        {name: f"phub/{name}:aaaaaaaaaaaa" for name in manifests},
    )


class Kubectl:
    """Records argv (and stdin documents); answers by argv prefix."""

    def __init__(self, hub_namespace: bool = True):
        self.calls: list[list[str]] = []
        self.applied: list[list[dict]] = []
        self.responses: dict[tuple[str, ...], str] = {}
        self.failures: dict[tuple[str, ...], str] = {}
        self.hub_namespace = hub_namespace

    def __call__(self, args, timeout, stdin=None):
        assert timeout > 0
        assert all(type(arg) is str for arg in args)
        assert args[0] == "kubectl"
        self.calls.append(args)
        if stdin is not None:
            self.applied.append(list(yaml.safe_load_all(stdin)))
        rest = tuple(args[1:])
        if rest[:3] == ("get", "namespace", "preview-hub") and not self.hub_namespace:
            return subprocess.CompletedProcess(args, 1, "", "NotFound")
        for prefix, error in self.failures.items():
            if rest[: len(prefix)] == prefix:
                return subprocess.CompletedProcess(args, 1, "", error)
        for prefix, output in self.responses.items():
            if rest[: len(prefix)] == prefix:
                return subprocess.CompletedProcess(args, 0, output, "")
        return subprocess.CompletedProcess(args, 0, "", "")


def runner(tmp_path: Path, kubectl: Kubectl, builder=None) -> KubernetesRunner:
    return KubernetesRunner(tmp_path, builder=builder, auth_url=AUTH, executor=kubectl)


def kinds(groups, group):
    return [(o["kind"], o["metadata"]["name"]) for o in groups[group]]


def test_render_golden(tmp_path):
    groups = render(make_plan(tmp_path), AUTH)
    assert yaml.safe_load(yaml.safe_dump(groups)) == groups
    assert groups == yaml.safe_load(Path("tests/golden/kubernetes.yaml").read_text())


def test_render_shape(tmp_path):
    plan = make_plan(tmp_path)
    groups = render(plan, AUTH)
    assert list(groups) == ["shared", "backend", "frontend"]
    assert kinds(groups, "shared") == [
        ("Namespace", "phub-test-one"),
        ("ResourceQuota", "environment"),
        ("NetworkPolicy", "environment"),
    ]
    assert kinds(groups, "backend") == [
        ("StatefulSet", "backend--db"),
        ("Service", "backend--db"),
        ("Job", "backend--db--init-0"),
        ("Job", "backend--db--init-1"),
        ("Deployment", "backend"),
        ("Service", "backend"),
        ("Middleware", "backend-auth"),
        ("Middleware", "backend-strip"),
        ("Ingress", "backend"),
    ]
    objects = [o for group in groups.values() for o in group]
    for o in objects:
        assert o["metadata"]["labels"]["dev.phub.managed"] == "true"
        assert o["metadata"]["labels"]["dev.phub.env"] == "test-one"
        if o["kind"] != "Namespace":
            assert o["metadata"]["namespace"] == "phub-test-one"
        template = o.get("spec", {}).get("template", {}).get("spec")
        if template:
            # Service links once injected SERVER_PORT=tcp://… and broke a Spring app.
            assert template["enableServiceLinks"] is False
    # The resource URL baked into env by the plan resolves to the rendered Service.
    url = plan.services[0].env["DATABASE_URL"]
    assert "@backend--db:5432/" in url


def test_public_routes_authenticate_and_strip(tmp_path):
    groups = render(make_plan(tmp_path), AUTH)
    backend = {(o["kind"], o["metadata"]["name"]): o for o in groups["backend"]}
    ingress = backend[("Ingress", "backend")]
    rule = ingress["spec"]["rules"][0]
    assert rule["host"] == "phub-test-one.cafitac.com"
    assert rule["http"]["paths"][0]["path"] == "/_svc/api"
    notes = ingress["metadata"]["annotations"]
    assert notes["traefik.ingress.kubernetes.io/router.middlewares"] == (
        "phub-test-one-backend-auth@kubernetescrd,"
        "phub-test-one-backend-strip@kubernetescrd"
    )
    assert notes["traefik.ingress.kubernetes.io/router.priority"] == "100"
    assert backend[("Middleware", "backend-auth")]["spec"]["forwardAuth"] == {
        "address": AUTH,
        "trustForwardHeader": False,
    }
    frontend = {(o["kind"], o["metadata"]["name"]): o for o in groups["frontend"]}
    entry = frontend[("Ingress", "frontend")]
    assert entry["spec"]["rules"][0]["http"]["paths"][0]["path"] == "/"
    assert (
        entry["metadata"]["annotations"][
            "traefik.ingress.kubernetes.io/router.priority"
        ]
        == "10"
    )
    assert ("Middleware", "frontend-strip") not in frontend


def test_local_only_routes_have_no_auth(tmp_path):
    groups = render(make_plan(tmp_path, public=False), AUTH)
    ingress = next(o for o in groups["backend"] if o["kind"] == "Ingress")
    assert ingress["spec"]["rules"][0]["host"] == "api.test-one.localhost"
    assert ingress["metadata"]["annotations"] == {}
    assert not [o for o in groups["backend"] if o["kind"] == "Middleware"]


def test_probes_carry_manifest_deadline(tmp_path):
    groups = render(make_plan(tmp_path), AUTH)
    deployment = next(o for o in groups["backend"] if o["kind"] == "Deployment")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert container["startupProbe"]["httpGet"] == {"path": "/healthz", "port": 8000}
    assert container["startupProbe"]["failureThreshold"] == 45  # 90s / 2s
    assert container["resources"]["limits"]["memory"] == "512Mi"
    cmd = make_plan(tmp_path)
    service = replace(
        cmd.services[0],
        manifest=replace(
            cmd.services[0].manifest, health={"cmd": ["true"], "timeout": "10s"}
        ),
    )
    groups = render(replace(cmd, services=(service, *cmd.services[1:])), AUTH)
    deployment = next(o for o in groups["backend"] if o["kind"] == "Deployment")
    probe = deployment["spec"]["template"]["spec"]["containers"][0]["startupProbe"]
    assert probe["exec"] == {"command": ["true"]}
    assert probe["failureThreshold"] == 5


def test_revision_rolls_only_on_image_or_env_change(tmp_path):
    plan = make_plan(tmp_path)

    def revision(p):
        groups = render(p, AUTH)
        deployment = next(o for o in groups["backend"] if o["kind"] == "Deployment")
        return deployment["spec"]["template"]["metadata"]["annotations"][
            "dev.phub.revision"
        ]

    base = revision(plan)
    assert revision(plan) == base
    newer = replace(plan.services[0], image="phub/backend:bbbbbbbbbbbb")
    assert revision(replace(plan, services=(newer, *plan.services[1:]))) != base


def test_quota_covers_services_resources_and_one_init(tmp_path):
    groups = render(make_plan(tmp_path), AUTH)
    hard = groups["shared"][1]["spec"]["hard"]
    # backend 512Mi + frontend 512Mi + postgres 512Mi + one init beside them (512Mi)
    assert hard == {
        "limits.memory": "2048Mi",
        "limits.cpu": "4",
        "requests.storage": "1Gi",
    }


def test_refuses_wrong_cluster(tmp_path):
    with pytest.raises(ValueError, match="cluster mismatch"):
        runner(tmp_path, Kubectl(hub_namespace=False))


def test_apply_order_and_prune(tmp_path):
    kubectl = Kubectl()
    result = runner(tmp_path, kubectl).apply(make_plan(tmp_path))
    assert result.success, result.message
    applied = iter(kubectl.applied)
    flow = []
    for call in kubectl.calls[1:]:
        if call[1] == "apply":
            flow.append("apply:" + ",".join(o["kind"] for o in next(applied)))
        else:
            flow.append(" ".join(call[1:3]))
    assert flow == [
        "apply:Namespace,ResourceQuota,NetworkPolicy",
        "apply:StatefulSet,Service",
        "rollout status",
        "delete job",
        "apply:Job",
        "wait -n",
        "delete job",
        "apply:Job",
        "wait -n",
        "apply:Deployment,Service,Middleware,Middleware,Ingress",
        "apply:Deployment,Service,Middleware,Ingress",
        "delete -n",
    ]
    prune = kubectl.calls[-1]
    assert (
        "dev.phub.managed=true,dev.phub.service notin (backend,frontend,shared)"
        in prune
    )
    apply_call = next(c for c in kubectl.calls if c[1] == "apply")
    assert apply_call[2:] == [
        "--server-side",
        "--force-conflicts",
        "--field-manager",
        "phub",
        "-f",
        "-",
    ]
    written = list(
        yaml.safe_load_all((tmp_path / "envs/test-one/kubernetes.yaml").read_text())
    )
    assert len(written) == 3 + 9 + 4  # shared, backend, frontend


def test_unchanged_services_are_not_reapplied(tmp_path):
    kubectl = Kubectl()
    plan = make_plan(tmp_path)
    plan = replace(
        plan, services=tuple(replace(s, changed=False) for s in plan.services)
    )
    assert runner(tmp_path, kubectl).apply(plan).success
    flow = [c[1] for c in kubectl.calls[1:]]
    assert flow == ["apply", "delete"]  # shared objects, then prune


def test_apply_failure_names_the_service(tmp_path):
    kubectl = Kubectl()
    kubectl.failures[("wait", "-n", "phub-test-one")] = "job failed"
    result = runner(tmp_path, kubectl).apply(make_plan(tmp_path))
    assert not result.success
    assert result.service == "backend"
    assert "job failed" in result.log_excerpt


def pod(service, reason=None):
    state = {"waiting": {"reason": reason}} if reason else {"running": {}}
    return {
        "metadata": {"labels": {"dev.phub.service": service}},
        "status": {"containerStatuses": [{"state": state}]},
    }


def deployment(service, ready):
    return {
        "metadata": {"labels": {"dev.phub.service": service}},
        "status": {"readyReplicas": 1} if ready else {},
    }


def test_health(tmp_path):
    kubectl = Kubectl()
    kubectl.responses[("get", "deployment")] = json.dumps(
        {
            "items": [
                deployment("backend", True),
                deployment("frontend", False),
                deployment("notifier", False),
            ]
        }
    )
    kubectl.responses[("get", "pod")] = json.dumps(
        {
            "items": [
                pod("backend"),
                pod("frontend"),
                pod("notifier", "CrashLoopBackOff"),
            ]
        }
    )
    assert runner(tmp_path, kubectl).health("test-one") == {
        "backend": Health.HEALTHY,
        "frontend": Health.STARTING,
        "notifier": Health.UNHEALTHY,
    }


def test_inventory_and_destroy(tmp_path):
    kubectl = Kubectl()
    kubectl.responses[("get", "namespace", "-l")] = "namespace/phub-test-one\n"
    kubectl.responses[("get", "pod,pvc")] = json.dumps(
        {
            "items": [
                {
                    "kind": "Pod",
                    "metadata": {"namespace": "phub-test-one", "name": "a"},
                },
                {
                    "kind": "PersistentVolumeClaim",
                    "metadata": {"namespace": "phub-test-one", "name": "data"},
                },
            ]
        }
    )
    hub = runner(tmp_path, kubectl)
    inventory = hub.inventory("test-one")
    assert inventory.containers == ("phub-test-one/a",)
    assert inventory.networks == ("namespace/phub-test-one",)
    assert inventory.volumes == ("phub-test-one/data",)
    assert not inventory.empty
    hub.destroy("test-one")
    deletes = [c for c in kubectl.calls if c[1] == "delete"]
    assert deletes and deletes[0][2:4] == ["namespace", "phub-test-one"]
    selector = kubectl.calls[1][kubectl.calls[1].index("-l") + 1]
    assert selector == "dev.phub.managed=true,dev.phub.env=test-one"


def test_destroy_skips_unowned_namespace(tmp_path):
    kubectl = Kubectl()
    hub = runner(tmp_path, kubectl)
    assert hub.destroy("test-one").empty
    assert not [c for c in kubectl.calls if c[1] == "delete"]


def test_build_delegates_or_fails(tmp_path):
    with pytest.raises(OSError, match="No image builder"):
        runner(tmp_path, Kubectl()).build("backend", "a" * 40, tmp_path, None)  # type: ignore[arg-type]
    seen = []

    def builder(service, commit, source, manifest):
        seen.append((service, commit))
        return f"registry/{service}:{commit[:12]}"

    built = runner(tmp_path, Kubectl(), builder).build(
        "backend", "a" * 40, tmp_path, None
    )  # type: ignore[arg-type]
    assert built == "registry/backend:aaaaaaaaaaaa"
    assert seen == [("backend", "a" * 40)]


def test_logs(tmp_path):
    kubectl = Kubectl()
    kubectl.responses[("logs",)] = "hello\n"
    assert runner(tmp_path, kubectl).logs("test-one", "backend", 5) == "hello\n"
    assert kubectl.calls[-1][1:] == [
        "logs",
        "-n",
        "phub-test-one",
        "deployment/backend",
        "--tail",
        "5",
        "--all-containers",
    ]


def test_namespace_validates_env():
    assert namespace("test-one") == "phub-test-one"
    with pytest.raises(InvalidInput):
        namespace("Bad_Name")
