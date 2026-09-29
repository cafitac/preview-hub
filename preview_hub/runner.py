from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from .contracts import ServiceManifest


class Health(StrEnum):
    UNKNOWN = "UNKNOWN"
    STARTING = "STARTING"
    HEALTHY = "HEALTHY"
    UNHEALTHY = "UNHEALTHY"


@dataclass(frozen=True)
class ResourcePlan:
    id: str
    service: str
    name: str
    type: str
    version: str
    url: str
    init: tuple[tuple[str, ...], ...]
    labels: dict[str, str]


@dataclass(frozen=True)
class ServicePlan:
    name: str
    commit: str
    image: str
    source: Path
    manifest: ServiceManifest
    port: int
    env: dict[str, str]
    public_url: str | None
    internal_url: str
    memory: str
    labels: dict[str, str]
    resources: tuple[ResourcePlan, ...] = ()
    changed: bool = True
    local_url: str | None = None


@dataclass(frozen=True)
class EnvironmentPlan:
    env: str
    services: tuple[ServicePlan, ...]
    labels: dict[str, str]
    routes: dict[str, str]
    resources: tuple[ResourcePlan, ...]

    @property
    def order(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.services)


@dataclass(frozen=True)
class RunResult:
    success: bool = True
    message: str = ""
    service: str | None = None
    log_excerpt: str = ""


@dataclass(frozen=True)
class Inventory:
    containers: tuple[str, ...] = ()
    networks: tuple[str, ...] = ()
    volumes: tuple[str, ...] = ()
    images: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.containers or self.networks or self.volumes or self.images)


@dataclass(frozen=True)
class FailureInfo:
    stage: str
    service: str | None
    message: str
    log_excerpt: str = ""


class Runner(Protocol):
    def build(
        self, service: str, commit: str, source: Path, manifest: ServiceManifest
    ) -> str: ...
    def apply(self, plan: EnvironmentPlan) -> RunResult: ...
    def health(self, env: str) -> dict[str, Health]: ...
    def destroy(self, env: str) -> Inventory: ...
    def inventory(self, env: str | None = None) -> Inventory: ...


class ImageCollector(Protocol):
    """Optional CLI maintenance capability, separate from the C4 lifecycle port."""

    def gc_images(
        self, retained: set[str], keep_per_service: int = 3
    ) -> tuple[str, ...]: ...
