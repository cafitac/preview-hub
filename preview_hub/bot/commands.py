from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast

from preview_hub.contracts import Catalog, CompositionSpec, EnvName, InvalidInput


@dataclass(frozen=True)
class Command:
    action: str
    refs: dict[str, str]
    ttl: str | None = None

    def normalized(self) -> str:
        return " ".join(
            [
                "/preview",
                self.action,
                *(f"{key}={value}" for key, value in sorted(self.refs.items())),
                *([f"ttl={self.ttl}"] if self.ttl else []),
            ]
        )


def parse_command(body: str, catalog: Catalog) -> Command:
    words = body.strip().split()
    if (
        len(words) < 2
        or words[0] != "/preview"
        or words[1] not in {"up", "update", "down", "status"}
    ):
        raise InvalidInput("Expected /preview up|update|down|status")
    action = words[1]
    refs: dict[str, str] = {}
    ttl = None
    for word in words[2:]:
        key, sep, value = word.partition("=")
        if not sep or not value or action in {"down", "status"}:
            raise InvalidInput("Invalid command arguments")
        if key == "ttl":
            if action != "up" or ttl is not None:
                raise InvalidInput("ttl is allowed once, on up only")
            ttl = value
        elif key in catalog.services and key not in refs:
            refs[key] = value
        else:
            raise InvalidInput("Unknown or repeated service")
    if action == "update" and not refs:
        raise InvalidInput("update requires service=ref")
    if action in {"up", "update"}:
        catalog.complete(CompositionSpec(EnvName("pr-validation"), refs, ttl))
    return Command(action, refs, ttl)


def authorize(catalog: Catalog, repo: str, association: str, pr: dict[str, Any]) -> str:
    matches = [
        service for service, entry in catalog.services.items() if entry.repo == repo
    ]
    if len(matches) != 1:
        raise InvalidInput("Repository must identify one catalog service")
    if association not in {"OWNER", "MEMBER", "COLLABORATOR"}:
        raise InvalidInput("Author is not a repository collaborator")
    base = repository(pr, "base")
    head = repository(pr, "head")
    if base != repo or head != base:
        raise InvalidInput("Fork PRs are not allowed")
    if pr.get("state") != "open":
        raise InvalidInput("PR is not open")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", str(pr.get("head", {}).get("sha", ""))):
        raise InvalidInput("PR head SHA is invalid")
    return matches[0]


def environment_name(service: str, number: int) -> str:
    return EnvName(f"pr-{service}-{number}")


def repository(pr: dict[str, Any], side: str) -> str | None:
    branch = pr.get(side)
    if not isinstance(branch, dict):
        return None
    repo = cast(dict[str, Any], branch).get("repo")
    if not isinstance(repo, dict):
        return None
    name = cast(dict[str, Any], repo).get("full_name")
    return name if isinstance(name, str) else None
