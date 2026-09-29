from pathlib import Path

from ..contracts import ServiceManifest
from ..runner import EnvironmentPlan, Health, Inventory, RunResult


class FakeRunner:
    def __init__(self, fail_at: str | None = None):
        self.fail_at = fail_at
        self.plans: dict[str, EnvironmentPlan] = {}
        self.images: set[str] = set()
        self.builds: list[str] = []

    def build(
        self, service: str, commit: str, source: Path, manifest: ServiceManifest
    ) -> str:
        if self.fail_at == "build":
            raise RuntimeError("synthetic build failure")
        image = f"phub/{service}:{commit[:12]}"
        if image not in self.images:
            self.builds.append(image)
            self.images.add(image)
        return image

    def apply(self, plan: EnvironmentPlan) -> RunResult:
        self.plans[plan.env] = plan
        return RunResult(
            self.fail_at != "start",
            "synthetic start failure" if self.fail_at == "start" else "",
        )

    def health(self, env: str) -> dict[str, Health]:
        return {
            s.name: Health.UNHEALTHY if self.fail_at == "health" else Health.HEALTHY
            for s in self.plans[env].services
        }

    def destroy(self, env: str) -> Inventory:
        if self.fail_at != "delete":
            self.plans.pop(env, None)
        return self.inventory(env)

    def inventory(self, env: str | None = None) -> Inventory:
        plans = [p for k, p in self.plans.items() if env is None or k == env]
        return Inventory(
            tuple(f"{p.env}-{s.name}" for p in plans for s in p.services),
            tuple(f"phub-{p.env}" for p in plans),
            tuple(r.name for p in plans for r in p.resources),
        )

    def logs(self, env: str, service: str, tail: int = 100) -> str:
        return ""

    def gc_images(
        self, retained: set[str], keep_per_service: int = 3
    ) -> tuple[str, ...]:
        recent: dict[str, list[str]] = {}
        for image in reversed(self.builds):
            service = image.split(":")[0]
            if (
                image in self.images
                and image not in recent.setdefault(service, [])
                and len(recent[service]) < keep_per_service
            ):
                recent[service].append(image)
        keep = retained | {image for images in recent.values() for image in images}
        removed = tuple(sorted(self.images - keep))
        self.images.difference_update(removed)
        return removed
