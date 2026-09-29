from __future__ import annotations

import fcntl
import re
import subprocess
from pathlib import Path
from typing import Protocol

from .contracts import InvalidInput, ServiceManifest, load_yaml


class GitSource(Protocol):
    def resolve(self, repo: str, ref: str) -> str: ...
    def checkout(self, repo: str, commit_sha: str) -> Path: ...
    def read_manifest(self, repo: str, commit_sha: str) -> ServiceManifest: ...


class GitCliSource:
    def __init__(
        self, cache_dir: Path = Path("/src"), services: dict[str, str] | None = None
    ):
        self.cache_dir = cache_dir
        self.services = services or {}

    def _url(self, repo: str) -> str:
        if Path(repo).is_absolute():
            return repo
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+", repo):
            raise InvalidInput("Invalid repository")
        return f"https://github.com/{repo}.git"

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=120, check=False
        )
        if result.returncode:
            raise InvalidInput(result.stderr[-2000:])
        return result.stdout.strip()

    def resolve(self, repo: str, ref: str) -> str:
        if not ref or ref.startswith("-"):
            raise InvalidInput("Invalid ref")
        output = self._git("ls-remote", "--", self._url(repo))
        refs = dict(line.split(None, 1)[::-1] for line in output.splitlines())
        for key in (
            f"refs/heads/{ref}",
            f"refs/tags/{ref}^{{}}",
            f"refs/tags/{ref}",
            ref,
        ):
            if key in refs:
                sha = refs[key].lower()
                self.checkout(repo, sha)
                return sha
        if re.fullmatch(r"[0-9a-fA-F]{7,40}", ref):
            candidates = {
                sha.lower()
                for sha in refs.values()
                if sha.lower().startswith(ref.lower())
            }
            if len(candidates) > 1:
                raise InvalidInput("Ambiguous abbreviated commit")
            sha = next(iter(candidates), ref.lower() if len(ref) == 40 else "")
            if not sha:
                raise InvalidInput(
                    "Abbreviated commit not advertised by remote; use full SHA"
                )
            self.checkout(
                repo, sha
            )  # existence is verified even for literal SHA inputs
            return sha
        raise InvalidInput(f"Ref not found: {ref}")

    def checkout(self, repo: str, commit_sha: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
            raise InvalidInput("Expected exact 40-hex commit")
        url = self._url(repo)
        service = self.services.get(
            repo, repo.rstrip("/").split("/")[-1].removesuffix(".git")
        )
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", service) or service in {".", ".."}:
            raise InvalidInput("Invalid cache service")
        parent = self.cache_dir / service
        parent.mkdir(parents=True, exist_ok=True)
        target = parent / commit_sha
        with (parent / f"{commit_sha}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if target.exists():
                try:
                    if self._git("-C", str(target), "rev-parse", "HEAD") == commit_sha:
                        return target
                except InvalidInput:
                    pass
            target.mkdir(exist_ok=True)
            self._git("init", "--quiet", str(target))
            self._git("-C", str(target), "fetch", "--depth=1", "--", url, commit_sha)
            actual = self._git("-C", str(target), "rev-parse", "FETCH_HEAD^{commit}")
            if actual != commit_sha:
                raise InvalidInput("Fetched object is not the requested commit")
            self._git("-C", str(target), "checkout", "--detach", "--force", commit_sha)
        return target

    def read_manifest(self, repo: str, commit_sha: str) -> ServiceManifest:
        return ServiceManifest.parse(
            load_yaml(self.checkout(repo, commit_sha) / "preview.yaml")
        )
