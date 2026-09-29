import ast
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import manifest

from preview_hub.contracts import (
    CatalogEntry,
    CompositionSpec,
    EnvName,
    InvalidInput,
    ServiceManifest,
    load_yaml,
    validate,
)
from preview_hub.lifecycle import CreateEnvironment
from preview_hub.plan import PlanBuilder


def build(ctx, manifests, name="feat-x"):
    return PlanBuilder().build(
        name,
        manifests,
        ctx.catalog,
        {n: "a" * 40 for n in manifests},
        {n: Path(".") for n in manifests},
        {n: f"phub/{n}:aaaaaaaaaaaa" for n in manifests},
    )


def test_interpolation_order_optional_and_isolation(ctx):
    backend = manifest(
        requires=[{"service": "frontend"}, {"service": "notifier", "optional": True}],
        resources={
            "db": {
                "type": "postgres",
                "version": "16",
                "init": [["alembic", "upgrade", "head"]],
            }
        },
        env={
            "URL": "${services.frontend.public_url}",
            "INTERNAL": "${services.frontend.internal_url}",
            "DB": "${resources.db.url}",
            "ENV": "${env.name}",
            "OPTIONAL": "prefix-${services.notifier.internal_url}",
        },
    )
    frontend = manifest("frontend", expose={"subdomain": "app"})
    plan = build(ctx, {"backend": backend, "frontend": frontend})
    assert plan.order == ("frontend", "backend")
    service = plan.services[1]
    assert service.env["URL"] == "http://app.feat-x.localhost:18080"
    assert service.env["INTERNAL"] == "http://frontend:8000"
    assert service.env["DB"] == "postgresql://preview:preview@backend--db:5432/preview"
    assert service.env["ENV"] == "feat-x"
    assert "OPTIONAL" not in service.env
    assert service.memory == "512Mi"
    assert service.labels["dev.phub.service"] == "backend"
    other = build(ctx, {"backend": backend, "frontend": frontend}, "feat-y")
    assert plan.resources[0].name != other.resources[0].name


@pytest.mark.parametrize("order", [("backend", "frontend"), ("frontend", "backend")])
def test_interpolation_uses_each_services_resources_and_optional_dependencies(
    ctx, order
):
    manifests = {
        name: manifest(
            name,
            requires=[{"service": f"{name}-optional", "optional": True}],
            resources={"db": {"type": "postgres", "version": "16"}},
            env={
                "DB": "${resources.db.url}",
                "OPTIONAL": "prefix-${services." + name + "-optional.internal_url}",
                "COMBINED": "${env.name}:${resources.db.url}",
            },
        )
        for name in order
    }
    plan = build(ctx, manifests)
    for service in plan.services:
        url = f"postgresql://preview:preview@{service.name}--db:5432/preview"
        assert service.env == {"DB": url, "COMBINED": f"feat-x:{url}"}


@pytest.mark.parametrize("kind", ["cycle", "missing", "interpolation", "unexposed"])
def test_invalid_plans(ctx, kind):
    manifests = {"backend": manifest()}
    if kind == "cycle":
        manifests["backend"] = manifest(requires=[{"service": "backend"}])
    elif kind == "missing":
        manifests["backend"] = manifest(requires=[{"service": "unknown"}])
    elif kind == "interpolation":
        manifests["backend"] = manifest(env={"X": "${services.unknown.internal_url}"})
    else:
        manifests["backend"] = manifest(env={"X": "${services.backend.public_url}"})
    with pytest.raises(InvalidInput):
        build(ctx, manifests)


def test_required_catalog_completion(ctx):
    ctx.catalog = replace(
        ctx.catalog,
        services={
            **ctx.catalog.services,
            "notifier": CatalogEntry("org/notifier", "main", "on_request"),
        },
    )
    ctx.git.manifests["org/backend"] = manifest(requires=[{"service": "notifier"}])
    ctx.git.manifests["org/notifier"] = manifest("notifier")
    env = CreateEnvironment(ctx).execute(CompositionSpec(EnvName("feat-x"), {}))
    assert {s["service"] for s in env["services"]} == {"backend", "notifier"}
    assert CreateEnvironment(ctx).execute(CompositionSpec(EnvName("feat-x"), {})) == env


@pytest.mark.parametrize("name", ["a", "UPPER", "../xx", "x" * 32, "0abc"])
def test_invalid_names(name):
    with pytest.raises(InvalidInput):
        EnvName(name)


def test_strict_schemas_and_build_inputs():
    base = {"apiVersion": "preview-hub/v1", "name": "feat-x", "services": {}}
    with pytest.raises(InvalidInput):
        validate("composition-spec", {**base, "unknown": True})
    with pytest.raises(InvalidInput):
        manifest(
            build={
                "context": ".",
                "dockerfile": "Dockerfile",
                "args": {"X": "${services.backend.public_url}"},
            }
        )
    with pytest.raises(InvalidInput):
        manifest(run={"port": 8000, "unknown": True})


def test_lifecycle_import_boundary():
    root = Path(__file__).parents[1] / "preview_hub"
    pending = ["lifecycle"]
    seen = set()
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        tree = ast.parse((root / f"{module}.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert "runners" not in (node.module or "")
                if (
                    node.level == 1
                    and node.module
                    and (root / f"{node.module}.py").exists()
                ):
                    pending.append(node.module)
            elif isinstance(node, ast.Import):
                assert all(
                    "preview_hub.runners" not in alias.name for alias in node.names
                )


def test_manifest_fixtures():
    for path in (Path(__file__).parent / "fixtures").glob("*.yaml"):
        ServiceManifest.parse(load_yaml(path))


def test_on_request_is_not_implicitly_equal_when_omitted(ctx):
    ctx.catalog = replace(
        ctx.catalog,
        services={
            **ctx.catalog.services,
            "notifier": CatalogEntry("org/notifier", "main", "on_request"),
        },
    )
    ctx.git.manifests["org/notifier"] = manifest("notifier")
    CreateEnvironment(ctx).execute(
        CompositionSpec(EnvName("feat-x"), {"notifier": "main"})
    )
    with pytest.raises(InvalidInput):
        CreateEnvironment(ctx).execute(CompositionSpec(EnvName("feat-x"), {}))


def test_qa_report_schema():
    report = {
        "apiVersion": "preview-hub/v1",
        "kind": "QaReport",
        "environment": "feat-x",
        "commits": {"backend": "a" * 40},
        "startedAt": "2026-09-29T10:00:00Z",
        "finishedAt": "2026-09-29T10:01:00Z",
        "scenarios": [
            {
                "id": "notes",
                "status": "PASSED",
                "summary": "created",
                "evidence": [{"type": "http", "uri": "artifact://response"}],
            }
        ],
        "summary": {"passed": 1, "failed": 0, "skipped": 0},
    }
    validate("qa-report", report)
    report["summary"]["unexpected"] = 1
    with pytest.raises(InvalidInput):
        validate("qa-report", report)


@pytest.mark.parametrize("key", ["context", "dockerfile"])
def test_empty_build_paths_are_invalid(key):
    with pytest.raises(InvalidInput):
        manifest(build={"context": ".", "dockerfile": "Dockerfile", key: ""})


@pytest.mark.parametrize(
    "value",
    [
        "${",
        "prefix-${env.name",
        "${env.name}-${",
        "${}",
        "${services.notifier.internal_url}-${unfinished",
    ],
)
def test_malformed_interpolation_is_invalid(ctx, value):
    with pytest.raises(InvalidInput):
        build(
            ctx,
            {
                "backend": manifest(
                    requires=[{"service": "notifier", "optional": True}],
                    env={"X": value},
                )
            },
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("image", "new-image"),
        ("env", {"X": "new"}),
        ("public_url", "http://new.localhost"),
        ("memory", "1Gi"),
        ("resources", ()),
        ("manifest", manifest(requires=[{"service": "notifier", "optional": True}])),
    ],
)
def test_changed_compares_rendered_service_spec(ctx, field, value):
    manifests = {
        "backend": manifest(resources={"db": {"type": "postgres", "version": "16"}})
    }
    previous = build(ctx, manifests)
    previous = replace(
        previous, services=(replace(previous.services[0], **{field: value}),)
    )
    plan = PlanBuilder().build(
        "feat-x",
        manifests,
        ctx.catalog,
        {"backend": "a" * 40},
        {"backend": Path(".")},
        {"backend": "phub/backend:aaaaaaaaaaaa"},
        set(),
        previous,
    )
    assert plan.services[0].changed


@pytest.mark.parametrize("key", ["", "DB", "0db", "db-main", "db.main", "a" * 22])
@pytest.mark.parametrize("schema_enabled", [True, False])
def test_invalid_resource_keys(monkeypatch, key, schema_enabled):
    if not schema_enabled:
        monkeypatch.setattr("preview_hub.contracts.validate", lambda kind, data: data)
    with pytest.raises(InvalidInput):
        manifest(resources={key: {"type": "postgres", "version": "16"}})


@pytest.mark.parametrize("key", ["a", "db0", "a" * 21])
def test_resource_identity_names(ctx, key):
    plan = build(
        ctx,
        {"backend": manifest(resources={key: {"type": "postgres", "version": "16"}})},
    )
    resource = plan.resources[0]
    assert resource.name == f"phub-feat-x--backend--{key}"
    assert resource.url == f"postgresql://preview:preview@backend--{key}:5432/preview"


def test_resource_hostname_cannot_collide_with_service(ctx):
    with pytest.raises(InvalidInput, match="Resource identity collision"):
        build(
            ctx,
            {
                "backend": manifest(
                    resources={"db": {"type": "postgres", "version": "16"}}
                ),
                "backend--db": manifest("backend--db"),
            },
        )


def test_resource_collision_is_rejected_for_unparsed_manifests(ctx):
    resource = {"type": "postgres", "version": "16"}
    with pytest.raises(InvalidInput, match="Resource identity collision"):
        build(
            ctx,
            {
                "backend": replace(manifest(), resources={"db--main": resource}),
                "backend--db": manifest("backend--db", resources={"main": resource}),
            },
        )


@pytest.mark.parametrize(
    "key", ["", "0ARG", "ARG-NAME", "ARG.NAME", "A B", "é", "ARG\n"]
)
@pytest.mark.parametrize("field", ["env", "args"])
@pytest.mark.parametrize("schema_enabled", [True, False])
def test_invalid_environment_and_build_keys(monkeypatch, key, field, schema_enabled):
    if not schema_enabled:
        monkeypatch.setattr("preview_hub.contracts.validate", lambda kind, data: data)
    extra = (
        {"env": {key: "value"}}
        if field == "env"
        else {
            "build": {
                "context": ".",
                "dockerfile": "Dockerfile",
                "args": {key: "value"},
            }
        }
    )
    with pytest.raises(InvalidInput):
        manifest(**extra)


@pytest.mark.parametrize("key", ["_", "A", "a_0", "ARG_NAME"])
def test_valid_environment_and_build_keys(key):
    parsed = manifest(
        env={key: "value"},
        build={"context": ".", "dockerfile": "Dockerfile", "args": {key: "value"}},
    )
    assert parsed.env[key] == parsed.build["args"][key] == "value"


@pytest.mark.parametrize(
    "unit,maximum", [("d", 3650), ("h", 87600), ("m", 5256000), ("s", 315360000)]
)
@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_duration_bounds_in_parser_and_schemas(unit, maximum, offset):
    from preview_hub.contracts import duration

    value = f"{maximum + offset}{unit}"
    spec = {
        "apiVersion": "preview-hub/v1",
        "name": "feat-x",
        "services": {},
        "ttl": value,
    }
    catalog = {
        "apiVersion": "preview-hub/v1",
        "public_url_template": "http://localhost",
        "services": {},
        "limits": {
            "max_environments": 1,
            "build_concurrency": 1,
            "default_ttl": "1h",
            "max_ttl": "1h",
        },
    }
    checks = [
        lambda: duration(value),
        lambda: validate("composition-spec", spec),
        lambda: manifest(health={"http": "/", "timeout": value}),
    ]
    for field in ("default_ttl", "max_ttl"):
        data = {**catalog, "limits": {**catalog["limits"], field: value}}
        checks.append(lambda data=data: validate("catalog", data))
    for check in checks:
        if offset > 0:
            with pytest.raises(InvalidInput):
                check()
        else:
            check()


def test_duration_rejects_arbitrarily_large_integer():
    from preview_hub.contracts import duration

    with pytest.raises(InvalidInput):
        duration("9" * 5000 + "s")
