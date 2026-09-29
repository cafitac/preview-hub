from __future__ import annotations

import fcntl
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from .contracts import InvalidInput, ServiceManifest, load_yaml
from .github import GitHubApi, GitHubError, TokenMissing


@dataclass(frozen=True)
class PrRef:
    number: int

    @classmethod
    def parse(cls, ref: str) -> PrRef | None:
        if re.fullmatch(r"pr-[1-9][0-9]{0,6}", ref):
            return cls(int(ref[3:]))
        return None


class GitSource(Protocol):
    def resolve(self, repo: str, ref: str) -> str: ...
    def checkout(self, repo: str, commit_sha: str) -> Path: ...
    def read_manifest(self, repo: str, commit_sha: str) -> ServiceManifest: ...


class GitCliSource:
    def __init__(
        self,
        cache_dir: Path = Path("/src"),
        services: dict[str, str] | None = None,
        github: GitHubApi | None = None,
    ):
        self.cache_dir = cache_dir
        self.services = services or {}
        self.github = github

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
        pr_ref = PrRef.parse(ref)
        if pr_ref is not None:
            # PR refs require a GitHub owner/name, not a local Git path.
            if ".." in repo or not re.fullmatch(
                r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}", repo
            ):
                raise InvalidInput(
                    f"{repo} PR #{pr_ref.number}: pr refs need a GitHub repository"
                )
            sha = self._resolve_pr(repo, pr_ref)
            self.checkout(repo, sha)
            return sha
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

    def _resolve_pr(self, repo: str, ref: PrRef) -> str:
        label = f"{repo} PR #{ref.number}"
        if self.github is None:
            raise InvalidInput(f"{label}: GitHub token missing")
        try:
            pr = self.github.get_pr(repo, ref.number)
        except TokenMissing:
            raise InvalidInput(f"{label}: GitHub token missing") from None
        except GitHubError as exc:
            if exc.status == 404:
                reason = "PR not found"
            elif exc.status in {401, 403} and not exc.retryable:
                reason = "GitHub token unauthorized"
            else:
                reason = "GitHub request failed"
            raise InvalidInput(f"{label}: {reason}") from None
        if pr.get("state") != "open" or pr.get("merged"):
            raise InvalidInput(f"{label}: PR is closed or merged")
        head = pr.get("head")
        base = pr.get("base")
        if (
            not isinstance(head, dict)
            or not isinstance(base, dict)
            or not isinstance(cast(dict[str, Any], head).get("repo"), dict)
            or not isinstance(cast(dict[str, Any], base).get("repo"), dict)
            or cast(dict[str, Any], head)["repo"].get("full_name") != repo
            or cast(dict[str, Any], base)["repo"].get("full_name") != repo
        ):
            raise InvalidInput(f"{label}: fork or mismatched base repository")
        sha = cast(dict[str, Any], head).get("sha")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
            raise InvalidInput(f"{label}: invalid head SHA")
        return sha.lower()

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
