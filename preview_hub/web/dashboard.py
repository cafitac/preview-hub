from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from ..cli import create_context, environment_descriptor
from ..contracts import CompositionSpec, EnvName, InvalidInput
from ..github import GitHubError, UrllibGitHubApi
from ..lifecycle import Context

# Inherit the configured Uvicorn error handler so INFO audit lines reach container logs.
logger = logging.getLogger("uvicorn.error.dashboard")


class CatalogGitHub(Protocol):
    def list_branches(self, repo: str) -> list[dict[str, Any]]: ...
    def list_open_prs(self, repo: str) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class SpawnResult:
    code: int | None
    error: str = ""


def spawn(argv: list[str], state_dir: Path) -> SpawnResult:
    folder = state_dir / "logs" / "web" / secrets.token_hex(16)
    folder.mkdir(parents=True, mode=0o700)
    stderr = folder / "stderr.log"
    with (folder / "stdout.log").open("wb") as out, stderr.open("wb") as err:
        child = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            start_new_session=True,
        )
        try:
            code = child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            # Reap detached children after the request has returned.
            threading.Thread(target=child.wait, daemon=True).start()
            return SpawnResult(None)
    with stderr.open("rb") as handle:
        handle.seek(max(0, stderr.stat().st_size - 4096))
        lines = handle.read().decode("utf-8", errors="replace").splitlines()
    return SpawnResult(code, lines[-1] if lines else "")


class Dashboard:
    def __init__(
        self,
        context: Context | None = None,
        github: CatalogGitHub | None = None,
        spawner: Callable[[list[str], Path], SpawnResult] = spawn,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._context = context
        self.github = github or UrllibGitHubApi(
            Path(os.environ.get("PHUB_GITHUB_TOKEN_FILE", "/run/secrets/github_token"))
        )
        self.spawner = spawner
        self.clock = clock
        self.lock = threading.Lock()
        self.context_lock = threading.Lock()
        self.repo_locks: dict[str, threading.Lock] = {}
        self.cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

    @property
    def context(self) -> Context:
        # Lazy initialization keeps the unauthenticated health endpoint independent
        # of catalog/state availability. Production serve passes its existing context.
        with self.context_lock:
            if self._context is None:
                self._context = create_context()
            return self._context

    def catalog_data(self) -> list[dict[str, Any]]:
        catalog = self.context.catalog
        result: list[dict[str, Any]] = []
        for name, entry in catalog.services.items():
            with self.lock:
                repo_lock = self.repo_locks.setdefault(entry.repo, threading.Lock())
            # Only requests refreshing this repository wait for its GitHub I/O.
            with repo_lock:
                with self.lock:
                    cached = self.cache.get(entry.repo)
                if cached is None or self.clock() - cached[0] >= 60:
                    data: dict[str, Any] = {"branches": [], "prs": []}
                    try:
                        data["branches"] = [
                            {"name": b["name"], "sha": b["commit"]["sha"]}
                            for b in self.github.list_branches(entry.repo)
                        ]
                        data["prs"] = [
                            {
                                "number": p["number"],
                                "title": p["title"],
                                "head_ref": p["head"]["ref"],
                                "head_sha": p["head"]["sha"],
                            }
                            for p in self.github.list_open_prs(entry.repo)
                            if p.get("state") == "open"
                            and cast(
                                dict[str, Any], p.get("head", {}).get("repo") or {}
                            ).get("full_name")
                            == cast(
                                dict[str, Any], p.get("base", {}).get("repo") or {}
                            ).get("full_name")
                            == entry.repo
                        ]
                    except (GitHubError, KeyError, TypeError, ValueError):
                        data["error"] = "GitHub 목록을 불러오지 못했습니다."
                    cached = (self.clock(), data)
                    with self.lock:
                        self.cache[entry.repo] = cached
                result.append(
                    {
                        "name": name,
                        "repo": entry.repo,
                        "default_ref": entry.default_ref,
                        "include": entry.include,
                        **cached[1],
                    }
                )
        return result

    def read_environments(self, name: str | None = None) -> list[dict[str, Any]]:
        # One read-only snapshot; never run DescribeEnvironment or acquire a lifecycle lock.
        path = self.context.registry.path
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN")
            rows = db.execute(
                "SELECT * FROM environments WHERE name=? ORDER BY (state!='DELETED') DESC,id DESC LIMIT 1"
                if name
                else "SELECT * FROM environments WHERE state!='DELETED' ORDER BY id",
                (name,) if name else (),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                env = dict(row)
                env["services"] = [
                    dict(s)
                    for s in db.execute(
                        "SELECT * FROM environment_services WHERE environment_id=? ORDER BY service",
                        (row["id"],),
                    )
                ]
                result.append(env)
            return result
        finally:
            db.close()

    def summary(self, env: dict[str, Any]) -> dict[str, Any]:
        error = json.loads(env["last_error_json"]) if env["last_error_json"] else None
        services = [
            {
                "name": s["service"],
                "ref": s["requested_ref"],
                "commit": s["commit_sha"][:12],
                "url": s["public_url"],
            }
            for s in env["services"]
        ]
        urls = {s["name"]: s["url"] for s in services if s["url"]}
        access = self.context.catalog.public_access
        return {
            "name": env["name"],
            "state": env["state"],
            "ttl": env["ttl_expires_at"],
            "services": services,
            "urls": urls,
            "entry_url": urls.get(
                access.entry_service if access else "frontend",
                next(iter(urls.values()), None),
            ),
            "last_error": error.get("message") if error else None,
            "created_at": env["created_at"],
            "updated_at": env["updated_at"],
        }

    def catalog(self, request: Request) -> Response:
        return JSONResponse(self.catalog_data())

    def environments(self, request: Request) -> Response:
        return JSONResponse([self.summary(e) for e in self.read_environments()])

    def detail(self, request: Request) -> Response:
        try:
            name = EnvName(request.path_params["name"])
        except InvalidInput as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        rows = self.read_environments(name)
        if not rows:
            return JSONResponse({"error": "Environment not found"}, status_code=404)
        if request.query_params.get("format") == "descriptor":
            return JSONResponse(environment_descriptor(self.context, rows[0]))
        return JSONResponse(self.summary(rows[0]))

    def page(self, request: Request) -> Response:
        return self.templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "email": request.state.identity.email,
                "catalog": self.catalog_data(),
                "environments": [self.summary(e) for e in self.read_environments()],
                "enabled": self.context.catalog.public_access is not None,
            },
        )

    async def mutate(self, request: Request) -> Response:
        action = (
            "down"
            if request.method == "DELETE"
            else ("update" if "name" in request.path_params else "up")
        )
        name = request.path_params.get("name", "")
        email = request.state.identity.email
        code: int | None = None
        rejected: str | None = None
        try:
            ctx = await run_in_threadpool(lambda: self.context)
            access = ctx.catalog.public_access
            dashboard_host = access.dashboard_host.lower() if access else None
            scheme, separator, origin_host = request.headers.get(
                "origin", ""
            ).partition("://")
            if (
                dashboard_host is None
                or scheme != "https"
                or not separator
                or origin_host.lower() != dashboard_host
            ):
                rejected = "Origin not allowed"
                return JSONResponse({"error": rejected}, status_code=403)
            if (
                request.method == "POST"
                and request.headers.get("content-type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
                != "application/json"
            ):
                rejected = "Content-Type must be application/json"
                return JSONResponse({"error": rejected}, status_code=403)
            refs: dict[str, str] = {}
            ttl = None
            if request.method == "POST":
                body: object = await request.json()
                if not isinstance(body, dict):
                    raise InvalidInput("JSON object required")
                data = cast(dict[str, Any], body)
                allowed = (
                    {"name", "services", "ttl"} if action == "up" else {"services"}
                )
                if data.keys() - allowed or "services" not in data:
                    raise InvalidInput("Invalid request fields; services is required")
                if action == "up":
                    name = data.get(
                        "name",
                        "c-"
                        + "".join(
                            secrets.choice("abcdefghijklmnopqrstuvwxyz234567")
                            for _ in range(6)
                        ),
                    )
                spec = CompositionSpec.parse(
                    {
                        "apiVersion": "preview-hub/v1",
                        "name": name,
                        "services": data["services"],
                        **({"ttl": data["ttl"]} if "ttl" in data else {}),
                    }
                )
                ctx.catalog.complete(spec)
                refs = spec.services
                if any(
                    not ref.strip() or ref.startswith("-") or "\x00" in ref
                    for ref in refs.values()
                ):
                    raise InvalidInput("Invalid ref")
                ttl = spec.ttl
            name = str(EnvName(name))
            argv = [
                sys.executable,
                "-m",
                "preview_hub",
                action,
                name,
                "--requested-by",
                f"web:{email}",
            ]
            for service, ref in refs.items():
                argv.extend(["--set", f"{service}={ref}"])
            if ttl:
                argv.extend(["--ttl", ttl])
            result = await run_in_threadpool(self.spawner, argv, ctx.registry.state_dir)
            code = result.code
            if code not in (None, 0):
                return JSONResponse(
                    {"error": result.error or "Command failed", "exit_code": code},
                    status_code={2: 400, 3: 409, 4: 429, 5: 500}.get(code, 500),
                )
            return JSONResponse({"name": name}, status_code=202)
        except (InvalidInput, ValueError) as exc:
            rejected = str(exc)
            return JSONResponse({"error": rejected}, status_code=400)
        except OSError:
            rejected = "Unable to start command"
            return JSONResponse({"error": rejected, "exit_code": 5}, status_code=500)
        finally:
            # JSON encoding prevents user-controlled values from injecting log lines.
            logger.info(
                "mutation %s",
                json.dumps(
                    {
                        "email": email,
                        "action": action,
                        "env": name,
                        "exit_code": code,
                        **({"rejected": rejected} if rejected is not None else {}),
                    }
                ),
            )

    def routes(self) -> list[Route]:
        return [
            Route("/", self.page),
            Route("/api/catalog", self.catalog),
            Route("/api/environments", self.environments),
            Route("/api/environments", self.mutate, methods=["POST"]),
            Route("/api/environments/{name}", self.detail),
            Route("/api/environments/{name}", self.mutate, methods=["DELETE"]),
            Route("/api/environments/{name}/update", self.mutate, methods=["POST"]),
        ]
