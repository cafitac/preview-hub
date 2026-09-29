import re
from dataclasses import replace as replace_dataclass
from pathlib import Path

from .contracts import Catalog, EnvName, InvalidInput, ServiceManifest
from .runner import EnvironmentPlan, ResourcePlan, ServicePlan


class PlanBuilder:
    def build(
        self,
        env: str,
        manifests: dict[str, ServiceManifest],
        catalog: Catalog,
        commits: dict[str, str],
        sources: dict[str, Path],
        images: dict[str, str],
        changed: set[str] | None = None,
        previous: EnvironmentPlan | None = None,
    ) -> EnvironmentPlan:
        EnvName(env)
        labels = {"dev.phub.managed": "true", "dev.phub.env": env}
        order: list[str] = []
        visiting: set[str] = set()

        def visit(name: str) -> None:
            if name in visiting:
                raise InvalidInput(f"Dependency cycle at {name}")
            if name in order:
                return
            visiting.add(name)
            for dep in manifests[name].requires:
                target = str(dep["service"])
                if target in manifests:
                    visit(target)
                elif not dep.get("optional", False):
                    raise InvalidInput(f"Missing required service: {target}")
            visiting.remove(name)
            order.append(name)

        for name in manifests:
            visit(name)
        local = {
            n: catalog.public_url_template.format(
                subdomain=m.expose["subdomain"], env=env
            )
            for n, m in manifests.items()
            if m.expose
        }
        public = dict(local)
        if access := catalog.public_access:
            origin = "https://" + access.host_template.format(env=env)
            public = {
                name: origin
                + (
                    ""
                    if name == access.entry_service
                    else access.path_template.format(
                        subdomain=manifests[name].expose["subdomain"]
                    )
                )
                for name in local
            }
        internal = {n: f"http://{n}:{m.run['port']}" for n, m in manifests.items()}
        prior_services = {s.name: s for s in previous.services} if previous else {}
        services: list[ServicePlan] = []
        resources: list[ResourcePlan] = []
        hostnames = set(manifests)
        container_names: set[str] = set()
        for name in order:
            m = manifests[name]
            own_labels = {**labels, "dev.phub.service": name}
            own: list[ResourcePlan] = []
            for key, r in m.resources.items():
                resource_name = f"{name}--{key}"
                container_name = f"phub-{env}--{name}--{key}"
                if resource_name in hostnames or container_name in container_names:
                    raise InvalidInput(f"Resource identity collision: {resource_name}")
                hostnames.add(resource_name)
                container_names.add(container_name)
                own.append(
                    ResourcePlan(
                        key,
                        name,
                        container_name,
                        r["type"],
                        r["version"],
                        f"postgresql://preview:preview@{resource_name}:5432/preview",
                        tuple(tuple(c) for c in r.get("init", [])),
                        own_labels,
                    )
                )
            urls = {r.id: r.url for r in own}
            optional = {
                str(d["service"]) for d in m.requires if d.get("optional", False)
            }
            injected: dict[str, str] = {}
            for key, value in m.env.items():
                omit = False

                def replace(
                    match: re.Match[str],
                    optional: set[str] = optional,
                    urls: dict[str, str] = urls,
                ) -> str:
                    nonlocal omit
                    expression = match[1]
                    if expression == "env.name":
                        return env
                    parts = expression.split(".")
                    if len(parts) == 3 and parts[0] == "services":
                        target, attr = parts[1:]
                        if target not in manifests and target in optional:
                            omit = True
                            return ""
                        values = (
                            public
                            if attr == "public_url"
                            else internal
                            if attr == "internal_url"
                            else {}
                        )
                        if target in values:
                            return values[target]
                    if (
                        len(parts) == 3
                        and parts[0] == "resources"
                        and parts[2] == "url"
                        and parts[1] in urls
                    ):
                        return urls[parts[1]]
                    raise InvalidInput(f"Unresolved interpolation: {expression}")

                rendered = re.sub(r"\$\{([^}]+)\}", replace, value)
                if "${" in rendered:
                    raise InvalidInput(f"Unresolved interpolation: {value}")
                if not omit:
                    injected[key] = rendered
            services.append(
                ServicePlan(
                    name,
                    commits[name],
                    images[name],
                    sources[name],
                    m,
                    m.run["port"],
                    injected,
                    public.get(name),
                    internal[name],
                    m.run.get("memory", "512Mi"),
                    own_labels,
                    tuple(own),
                    changed is None or name in changed,
                    local.get(name) if catalog.public_access else None,
                )
            )
            service = services[-1]
            prior = prior_services.get(name)
            if previous is not None:
                services[-1] = replace_dataclass(
                    service,
                    changed=service.changed
                    or prior is None
                    or {
                        str(dep["service"])
                        for dep in m.requires
                        if dep["service"] in manifests
                    }
                    != {
                        str(dep["service"])
                        for dep in prior.manifest.requires
                        if dep["service"] in prior_services
                    }
                    or replace_dataclass(service, source=prior.source, changed=False)
                    != replace_dataclass(prior, changed=False),
                )
            resources.extend(own)
        return EnvironmentPlan(env, tuple(services), labels, public, tuple(resources))
