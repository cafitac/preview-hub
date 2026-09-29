import json
import re
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from conftest import manifest

from preview_hub.cli import main
from preview_hub.contracts import Catalog, InvalidInput, PublicAccess
from preview_hub.plan import PlanBuilder
from preview_hub.runners.compose import render

ACCESS = {
    "host_template": "phub-{env}.cafitac.com",
    "entry_service": "frontend",
    "path_template": "/_svc/{subdomain}",
    "dashboard_host": "preview-hub.cafitac.com",
}


def catalog_data():
    return {
        "apiVersion": "preview-hub/v1",
        "public_url_template": "http://{subdomain}.{env}.localhost:18080",
        "services": {
            name: {"repo": f"org/{name}", "default_ref": "main"}
            for name in ("frontend", "backend")
        },
        "limits": {
            "max_environments": 5,
            "build_concurrency": 2,
            "default_ttl": "24h",
            "max_ttl": "7d",
        },
        "public_access": dict(ACCESS),
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("host_template", "phub.cafitac.com"),
        ("host_template", "phub-{env}-{env}.cafitac.com"),
        ("host_template", "phub.{env}.cafitac.com"),
        ("host_template", "other-{env}.cafitac.com"),
        ("host_template", "phub-{env}.{zone}"),
        ("host_template", "phub-" + "a" * 28 + "{env}.cafitac.com"),
        ("host_template", "https://phub-{env}.cafitac.com"),
        ("entry_service", "absent"),
        ("path_template", "_svc/{subdomain}"),
        ("path_template", "/api"),
        ("path_template", "/{other}/{subdomain}"),
        ("dashboard_host", "https://preview-hub.cafitac.com"),
        ("dashboard_host", "bad name.cafitac.com"),
        ("unknown", "value"),
    ],
)
def test_reject_public_access(field, value):
    data = catalog_data()
    data["public_access"][field] = value
    with pytest.raises(InvalidInput):
        Catalog.parse(data)


def test_label_maximum_and_optional_catalog():
    data = catalog_data()
    data["public_access"]["host_template"] = "phub-" + "a" * 27 + "{env}.cafitac.com"
    assert Catalog.parse(data).public_access is not None  # 5 + 27 + 31 = 63
    del data["public_access"]
    assert Catalog.parse(data).public_access is None


def build(public=True):
    data = catalog_data()
    if not public:
        del data["public_access"]
    manifests = {
        "frontend": manifest(
            "frontend",
            expose={"subdomain": "web"},
            env={"API_URL": "${services.backend.public_url}"},
        ),
        "backend": manifest(expose={"subdomain": "api"}),
    }
    return PlanBuilder().build(
        "demo",
        manifests,
        Catalog.parse(data),
        {n: "a" * 40 for n in manifests},
        {n: Path(".") for n in manifests},
        {n: f"phub/{n}:test" for n in manifests},
    )


def test_public_urls_and_local_routing_compatibility():
    local, public = build(False), build()
    assert public.routes == {
        "frontend": "https://phub-demo.cafitac.com",
        "backend": "https://phub-demo.cafitac.com/_svc/api",
    }
    assert local.routes["backend"] == "http://api.demo.localhost:18080"
    assert public.services[0].env["API_URL"] == public.routes["backend"]
    assert local.services[0].env["API_URL"] == local.routes["backend"]
    before, after = render(local), render(public)
    for service in public.services:
        assert service.local_url == local.routes[service.name]
        old = before["services"][service.name]["labels"]
        labels = after["services"][service.name]["labels"]
        assert all(labels[key] == value for key, value in old.items())
        route = f"demo-{service.name}-public"
        assert labels[f"traefik.http.routers.{route}.service"] == f"demo-{service.name}"
        assert (
            labels[f"traefik.http.middlewares.{route}-auth.forwardauth.address"]
            == "http://phub-hub:8080/auth/verify"
        )
        assert (
            labels[
                f"traefik.http.middlewares.{route}-auth.forwardauth.trustForwardHeader"
            ]
            == "false"
        )
        assert (
            labels[f"traefik.http.routers.{route}.middlewares"].split(",")[0]
            == route + "-auth"
        )
    backend = after["services"]["backend"]["labels"]
    frontend = after["services"]["frontend"]["labels"]
    assert (
        backend["traefik.http.routers.demo-backend-public.rule"]
        == "Host(`phub-demo.cafitac.com`) && (Path(`/_svc/api`) || PathPrefix(`/_svc/api/`))"
    )
    assert (
        frontend["traefik.http.routers.demo-frontend-public.rule"]
        == "Host(`phub-demo.cafitac.com`)"
    )
    assert (
        backend[
            "traefik.http.middlewares.demo-backend-public-strip.stripprefix.prefixes"
        ]
        == "/_svc/api"
    )
    assert int(backend["traefik.http.routers.demo-backend-public.priority"]) > int(
        frontend["traefik.http.routers.demo-frontend-public.priority"]
    )


def test_public_service_paths_do_not_overlap():
    data = catalog_data()
    data["services"]["backendz"] = {"repo": "org/backendz", "default_ref": "main"}
    manifests = {
        "frontend": manifest("frontend", expose={"subdomain": "web"}),
        "backend": manifest(expose={"subdomain": "api"}),
        "backendz": manifest("backendz", expose={"subdomain": "apiz"}),
    }
    plan = PlanBuilder().build(
        "demo",
        manifests,
        Catalog.parse(data),
        {n: "a" * 40 for n in manifests},
        {n: Path(".") for n in manifests},
        {n: f"phub/{n}:test" for n in manifests},
    )
    services = render(plan)["services"]
    matchers = {}
    for service, subdomain in (("backend", "api"), ("backendz", "apiz")):
        labels = services[service]["labels"]
        route = f"demo-{service}-public"
        rule = labels[f"traefik.http.routers.{route}.rule"]
        assert rule == (
            "Host(`phub-demo.cafitac.com`) && "
            f"(Path(`/_svc/{subdomain}`) || PathPrefix(`/_svc/{subdomain}/`))"
        )
        matchers[subdomain] = re.findall(r"(Path|PathPrefix)\(`([^`]+)`\)", rule)
        assert (
            labels[f"traefik.http.middlewares.{route}-strip.stripprefix.prefixes"]
            == f"/_svc/{subdomain}"
        )
        assert int(labels[f"traefik.http.routers.{route}.priority"]) > int(
            services["frontend"]["labels"][
                "traefik.http.routers.demo-frontend-public.priority"
            ]
        )
    for subdomain in ("api", "apiz", "apizz"):
        for suffix in ("", "/", "/items"):
            path = f"/_svc/{subdomain}{suffix}"
            matches = {
                name
                for name, predicates in matchers.items()
                if any(
                    path == value if kind == "Path" else path.startswith(value)
                    for kind, value in predicates
                )
            }
            assert matches == ({subdomain} if subdomain != "apizz" else set())


def test_descriptor_public_fields_and_entry(ctx, capsys):
    ctx.catalog = replace(
        ctx.catalog,
        public_access=PublicAccess(**{**ACCESS, "entry_service": "backend"}),
    )
    ctx.git.manifests["org/backend"] = manifest(expose={"subdomain": "api"})
    assert main(["up", "demo", "--format", "descriptor"], ctx) == 0
    descriptor = json.loads(capsys.readouterr().out)
    assert descriptor["access"] == {"provider": "cloudflare-access"}
    assert descriptor["entryUrl"] == "https://phub-demo.cafitac.com"
    assert descriptor["services"][0]["localUrl"] == "http://api.demo.localhost:18080"


def test_stack_public_is_opt_in_and_outbound_only():
    stack = yaml.safe_load(Path("deploy/hub-stack/compose.yaml").read_text())
    tunnel = stack["services"]["cloudflared"]
    assert tunnel["profiles"] == ["public"]
    assert tunnel["container_name"] == "phub-cloudflared"
    assert tunnel["image"] == "cloudflare/cloudflared:2025.2.1"
    assert "ports" not in tunnel
    assert "ports" not in stack["services"]["hub"]
    assert (
        "/opt/phub/secrets/tunnel.json:/etc/cloudflared/tunnel.json:ro"
        in tunnel["volumes"]
    )
    assert stack["services"]["hub"]["env_file"] == [
        {"path": "/opt/phub/public.env", "required": False}
    ]
    config = yaml.safe_load(Path("deploy/hub-stack/cloudflared.yml").read_text())
    assert "tunnel" not in config
    assert config["ingress"][-1] == {"service": "http_status:404"}
    assert tunnel["command"][-1] == "${PHUB_TUNNEL_ID:-}"


@pytest.mark.parametrize("fail_apply", [False, True])
def test_update_applies_catalog_url_changes_without_new_commits(
    ctx, tmp_path, monkeypatch, fail_apply
):
    from preview_hub.contracts import CatalogEntry
    from preview_hub.runners.compose import ComposeRunner

    data = catalog_data()
    del data["public_access"]
    ctx.catalog = Catalog.parse(data)
    ctx.catalog.services["worker"] = CatalogEntry("org/worker", "main")
    ctx.git.manifests = {
        "org/backend": manifest(expose={"subdomain": "api"}),
        "org/frontend": manifest(
            "frontend",
            expose={"subdomain": "web"},
            env={"API_URL": "${services.backend.public_url}"},
        ),
        "org/worker": manifest(
            "worker", env={"API_URL": "prefix=${services.backend.public_url}"}
        ),
    }
    assert main(["up", "demo"], ctx) == 0
    before = ctx.registry.get("demo")
    before_urls = {s["service"]: s["public_url"] for s in before["services"]}
    builds = list(ctx.runner.builds)
    ctx.catalog = replace(ctx.catalog, public_access=PublicAccess(**ACCESS))
    compose = ComposeRunner(
        tmp_path,
        "unused",
        executor=lambda args, timeout: subprocess.CompletedProcess(
            args, 0, "unused", ""
        ),
    )
    calls = []

    def compose_command(*args):
        calls.append(args)
        if fail_apply:
            raise OSError("synthetic apply failure")
        return ""

    monkeypatch.setattr(compose, "_compose", compose_command)
    monkeypatch.setattr(
        compose, "_ids", lambda kind, *args: ["proxy"] if kind == "container" else []
    )
    original_apply = ctx.runner.apply

    def apply(plan):
        # No planned URL may be published before the runner applies it.
        during = ctx.registry.get("demo")
        assert {
            s["service"]: s["public_url"] for s in during["services"]
        } == before_urls
        result = compose.apply(plan)
        if result.success:
            original_apply(plan)
        return result

    monkeypatch.setattr(ctx.runner, "apply", apply)
    assert main(["update", "demo", "--set", "backend=main"], ctx) == (
        5 if fail_apply else 0
    )
    after = ctx.registry.get("demo")
    assert ctx.runner.builds == builds
    assert {s["commit_sha"] for s in after["services"]} == {"a" * 40}
    if fail_apply:
        assert {s["service"]: s["public_url"] for s in after["services"]} == before_urls
        return
    assert {args[-1] for args in calls if "--force-recreate" in args} == {
        "backend",
        "frontend",
        "worker",
    }
    document = yaml.safe_load((tmp_path / "envs/demo/compose.yaml").read_text())
    for name in ("backend", "frontend"):
        labels = document["services"][name]["labels"]
        route = f"demo-{name}-public"
        assert f"traefik.http.routers.{route}.rule" in labels
        assert labels[f"traefik.http.routers.{route}.middlewares"].startswith(
            route + "-auth"
        )
        assert labels[f"traefik.http.middlewares.{route}-auth.forwardauth.address"] == (
            "http://phub-hub:8080/auth/verify"
        )
    plan = ctx.runner.plans["demo"]
    assert {s["service"]: s["public_url"] for s in after["services"]} == {
        s.name: s.public_url for s in plan.services
    }
    backend_url = "https://phub-demo.cafitac.com/_svc/api"
    assert document["services"]["frontend"]["environment"]["API_URL"] == backend_url
    assert (
        document["services"]["worker"]["environment"]["API_URL"]
        == "prefix=" + backend_url
    )
    # Once the applied URLs match, another unchanged update remains a no-op.
    monkeypatch.setattr(ctx.runner, "apply", original_apply)
    assert main(["update", "demo", "--set", "backend=main"], ctx) == 0
    assert not any(s.changed for s in ctx.runner.plans["demo"].services)
