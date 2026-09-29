from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


class GitHubError(RuntimeError):
    """Deliberately excludes response bodies, request objects and credentials."""

    def __init__(
        self,
        message: str,
        *,
        retry_at: float = 0,
        attempted: bool = True,
        retryable: bool = False,
        status: int | None = None,
    ):
        super().__init__(message)
        self.retry_at = retry_at
        self.attempted = attempted
        self.retryable = retryable
        self.status = status


class TokenMissing(GitHubError):
    pass


class GitHubApi(Protocol):
    def list_issue_comments(self, repo: str, since: str) -> list[dict[str, Any]]: ...
    def get_pr(self, repo: str, number: int) -> dict[str, Any]: ...
    def list_closed_prs(self, repo: str, since: str) -> list[dict[str, Any]]: ...
    def post_comment(self, repo: str, number: int, body: str) -> int: ...


class Response(Protocol):
    def read(self) -> bytes: ...
    def close(self) -> None: ...


class Transport(Protocol):
    def __call__(self, request: Request, *, timeout: float) -> Response: ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        # Never forward Authorization to a redirect target.
        raise GitHubError("GitHub redirects are not allowed")


def open_request(request: Request, *, timeout: float) -> Response:
    return build_opener(NoRedirect()).open(request, timeout=timeout)


class UrllibGitHubApi:
    def __init__(
        self,
        token_path: Path = Path("/run/secrets/github_token"),
        *,
        transport: Transport = open_request,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 20,
    ):
        self.token_path = token_path
        self.transport = transport
        self.sleep = sleep
        self.timeout = timeout
        self.retry_at = 0.0

    def token_present(self) -> bool:
        try:
            return bool(self.token_path.stat().st_size)
        except OSError:
            return False

    def _request(
        self, method: str, path: str, body: dict[str, str] | None = None
    ) -> Any:
        if time.time() < self.retry_at:
            raise GitHubError(
                "GitHub rate limit cooldown",
                retry_at=self.retry_at,
                attempted=False,
                retryable=True,
            )
        self.retry_at = 0.0
        # Token lives only in this request's Authorization header, never on self.
        try:
            token = self.token_path.read_text().strip()
        except (OSError, UnicodeError):
            raise TokenMissing("token missing") from None
        if not token:
            raise TokenMissing("token missing")
        for attempt in range(3):
            delay = float(2**attempt)
            try:
                request = Request(
                    "https://api.github.com" + path,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={
                        "Authorization": "Bearer " + token,
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                        "Content-Type": "application/json",
                    },
                    method=method,
                )
                response = self.transport(request, timeout=self.timeout)
                try:
                    result = json.loads(response.read())
                    self.retry_at = 0.0
                    return result
                finally:
                    response.close()
            except HTTPError as exc:
                retry = (
                    exc.code == 429
                    or exc.code >= 500
                    or (
                        exc.code == 403
                        and (
                            exc.headers.get("Retry-After") is not None
                            or exc.headers.get("X-RateLimit-Remaining") == "0"
                        )
                    )
                )
                retry_after = exc.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        try:
                            delay = (
                                parsedate_to_datetime(retry_after) - datetime.now(UTC)
                            ).total_seconds()
                        except (TypeError, ValueError, OverflowError):
                            delay = 60
                elif exc.headers.get("X-RateLimit-Remaining") == "0":
                    try:
                        delay = (
                            float(exc.headers.get("X-RateLimit-Reset", "0"))
                            - time.time()
                        )
                    except ValueError:
                        delay = 60
                exc.close()
                delay = max(0, delay) if math.isfinite(delay) else 60
                # POST retries are best-effort, in memory (at most three per process).
                # Never retry a potentially accepted POST within this HTTP call.
                if (
                    method == "POST"
                    or not retry
                    or attempt == 2
                    or not 0 <= delay <= 60
                ):
                    if retry:
                        self.retry_at = time.time() + delay
                    raise GitHubError(
                        "GitHub request failed",
                        retry_at=self.retry_at if retry else 0,
                        retryable=retry,
                        status=exc.code,
                    ) from None
            except (OSError, HTTPException):
                raise GitHubError("GitHub request failed", retryable=True) from None
            except (ValueError, TypeError):
                raise GitHubError("GitHub request failed") from None
            self.sleep(delay)
        raise GitHubError("GitHub request failed")

    def _pages(
        self, repo: str, resource: str, params: dict[str, str]
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self._request(
                "GET",
                f"/repos/{repo}/{resource}?"
                + urlencode({**params, "per_page": "100", "page": str(page)}),
            )
            if not isinstance(data, list):
                raise GitHubError("Invalid GitHub response")
            rows = cast(list[dict[str, Any]], data)
            result.extend(rows)
            if len(rows) < 100:
                return result
            page += 1

    def list_issue_comments(self, repo: str, since: str) -> list[dict[str, Any]]:
        return self._pages(
            repo,
            "issues/comments",
            {"since": since, "sort": "updated", "direction": "asc"},
        )

    def get_pr(self, repo: str, number: int) -> dict[str, Any]:
        result = self._request("GET", f"/repos/{repo}/pulls/{number}")
        if not isinstance(result, dict):
            raise GitHubError("Invalid GitHub response")
        return cast(dict[str, Any], result)

    def list_closed_prs(self, repo: str, since: str) -> list[dict[str, Any]]:
        # The pulls endpoint has no since parameter; stop sorted pagination at cutoff.
        result: list[dict[str, Any]] = []
        page = 1
        cutoff = datetime.fromisoformat(since)
        while True:
            rows = cast(
                list[dict[str, Any]],
                self._request(
                    "GET",
                    f"/repos/{repo}/pulls?"
                    + urlencode(
                        {
                            "state": "closed",
                            "sort": "updated",
                            "direction": "desc",
                            "per_page": 100,
                            "page": page,
                        }
                    ),
                ),
            )
            for row in rows:
                if datetime.fromisoformat(row["updated_at"]) < cutoff:
                    return result
                result.append(row)
            if len(rows) < 100:
                return result
            page += 1

    def post_comment(self, repo: str, number: int, body: str) -> int:
        return int(
            self._request(
                "POST", f"/repos/{repo}/issues/{number}/comments", {"body": body}
            )["id"]
        )
