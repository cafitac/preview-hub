import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from conftest import manifest

from preview_hub.cli import main
from preview_hub.contracts import Catalog, InvalidInput, PublicAccess
from preview_hub.plan import PlanBuilder

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
    for service in public.services:
        assert service.local_url == local.routes[service.name]


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


@pytest.mark.parametrize("fail_apply", [False, True])
def test_update_applies_catalog_url_changes_without_new_commits(
    ctx, monkeypatch, fail_apply
):
    from preview_hub.contracts import CatalogEntry
    from preview_hub.runner import RunResult

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
    original_apply = ctx.runner.apply

    def apply(plan):
        # No planned URL may be published before the runner applies it.
        during = ctx.registry.get("demo")
        assert {
            s["service"]: s["public_url"] for s in during["services"]
        } == before_urls
        if fail_apply:
            return RunResult(False, "synthetic apply failure")
        return original_apply(plan)

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
    plan = ctx.runner.plans["demo"]
    assert {s.name for s in plan.services if s.changed} == {
        "backend",
        "frontend",
        "worker",
    }
    assert {s["service"]: s["public_url"] for s in after["services"]} == {
        s.name: s.public_url for s in plan.services
    }
    backend_url = "https://phub-demo.cafitac.com/_svc/api"
    envs = {s.name: s.env for s in plan.services}
    assert envs["frontend"]["API_URL"] == backend_url
    assert envs["worker"]["API_URL"] == "prefix=" + backend_url
    # Once the applied URLs match, another unchanged update remains a no-op.
    monkeypatch.setattr(ctx.runner, "apply", original_apply)
    assert main(["update", "demo", "--set", "backend=main"], ctx) == 0
    assert not any(s.changed for s in ctx.runner.plans["demo"].services)


def test_deployed_catalog_enables_approved_public_access():
    data = yaml.safe_load(Path("deploy/catalog.yaml").read_text())
    catalog = Catalog.parse(data)
    assert data["public_access"] == ACCESS
    assert catalog.public_access is not None
    assert catalog.public_url_template == "http://{subdomain}.{env}.localhost:18080"
