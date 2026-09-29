from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Self, cast

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError


class InvalidInput(ValueError):
    pass


class _Validator(Protocol):
    def iter_errors(self, instance: object) -> Iterator[ValidationError]: ...


def validate(kind: str, data: object) -> dict[str, Any]:
    root = Path(__file__).parent / "schemas"
    if not root.exists():
        root = Path(__file__).parent.parent / "schemas"
    schema = json.loads((root / f"{kind}.schema.json").read_text())
    errors = sorted(
        cast(
            _Validator, Draft202012Validator(schema, format_checker=FormatChecker())
        ).iter_errors(data),
        key=lambda e: str(e.path),
    )
    if errors:
        raise InvalidInput("; ".join(e.message for e in errors))
    return cast(dict[str, Any], data)


def load_yaml(path: Path) -> object:
    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise InvalidInput(str(exc)) from exc


def duration(value: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]*[smhd]", value):
        raise InvalidInput(f"Invalid duration: {value}")
    maximum = 3650 * 86400
    multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[value[-1]]
    if len(value[:-1]) > len(str(maximum // multiplier)):
        raise InvalidInput("Duration exceeds maximum of 3650d")
    seconds = int(value[:-1]) * multiplier
    if seconds > maximum:
        raise InvalidInput("Duration exceeds maximum of 3650d")
    return seconds


class EnvName(str):
    def __new__(cls, value: str) -> Self:
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,30}", value):
            raise InvalidInput(f"Invalid environment name: {value}")
        return super().__new__(cls, value)


@dataclass(frozen=True)
class ServiceManifest:
    service: str
    build: dict[str, Any]
    run: dict[str, Any]
    health: dict[str, Any]
    expose: dict[str, str] = field(default_factory=dict[str, str])
    requires: tuple[dict[str, Any], ...] = ()
    resources: dict[str, Any] = field(default_factory=dict[str, Any])
    env: dict[str, str] = field(default_factory=dict[str, str])

    @classmethod
    def parse(cls, value: object) -> ServiceManifest:
        d = validate("service-manifest", value)
        for key in d.get("resources", {}):
            if not re.fullmatch(r"[a-z][a-z0-9]{0,20}", key):
                raise InvalidInput(f"Invalid resource key: {key}")
        for values in (d.get("env", {}), d["build"].get("args", {})):
            for key in values:
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                    raise InvalidInput(
                        f"Invalid environment or build argument key: {key}"
                    )
        if "${" in json.dumps(d["build"]):
            raise InvalidInput("Build inputs must be constant")
        for key in ("context", "dockerfile"):
            p = Path(d["build"][key])
            if p.is_absolute() or ".." in p.parts:
                raise InvalidInput("Build paths must stay inside the source tree")
        return cls(
            d["service"],
            d["build"],
            d["run"],
            {"timeout": "90s", **d["health"]},
            d.get("expose", {}),
            tuple(d.get("requires", [])),
            d.get("resources", {}),
            d.get("env", {}),
        )


@dataclass(frozen=True)
class CompositionSpec:
    name: EnvName
    services: dict[str, str]
    ttl: str | None = None

    @classmethod
    def parse(cls, value: object) -> CompositionSpec:
        d = validate("composition-spec", value)
        return cls(EnvName(d["name"]), d["services"], d.get("ttl"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "apiVersion": "preview-hub/v1",
            "name": str(self.name),
            "services": self.services,
            **({"ttl": self.ttl} if self.ttl else {}),
        }


@dataclass(frozen=True)
class CatalogEntry:
    repo: str
    default_ref: str
    include: str = "always"


@dataclass(frozen=True)
class Catalog:
    services: dict[str, CatalogEntry]
    public_url_template: str
    max_environments: int = 5
    build_concurrency: int = 2
    default_ttl: str = "24h"
    max_ttl: str = "7d"

    @classmethod
    def parse(cls, value: object) -> Catalog:
        d = validate("catalog", value)
        return cls(
            {k: CatalogEntry(**v) for k, v in d["services"].items()},
            d["public_url_template"],
            **d["limits"],
        )

    def complete(self, spec: CompositionSpec) -> CompositionSpec:
        spec = CompositionSpec.parse(spec.as_dict())
        unknown = spec.services.keys() - self.services.keys()
        if unknown:
            raise InvalidInput(f"Unknown services: {sorted(unknown)}")
        refs = {
            k: v.default_ref for k, v in self.services.items() if v.include == "always"
        }
        refs.update(spec.services)
        ttl = spec.ttl or self.default_ttl
        if duration(ttl) > duration(self.max_ttl):
            raise InvalidInput("TTL exceeds maximum")
        if not refs:
            raise InvalidInput("Environment must contain a service")
        return CompositionSpec(spec.name, refs, ttl)
