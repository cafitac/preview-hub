from __future__ import annotations

import logging
from typing import Any

from preview_hub.git import PrRef
from preview_hub.github import GitHubApi, GitHubError
from preview_hub.registry import Registry, now

LOG = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


def marker(environment: str) -> str:
    return f"<!-- phub-link env={environment} -->"


def removed_body(environment: str) -> str:
    return f"preview {environment}: removed\n{marker(environment)}"


def render(environment: dict[str, Any], entry_service: str) -> str:
    services = environment["services"]
    urls = {row["service"]: row["public_url"] for row in services if row["public_url"]}
    url = urls.get(entry_service, next(iter(urls.values()), ""))
    lines = [
        f"preview {environment['name']}: {environment['state']}",
        marker(environment["name"]),
        "",
        url,
        "",
        "| service | ref | commit |",
        "| --- | --- | --- |",
    ]
    for row in services:
        ref = str(row["requested_ref"]).replace("&", "&amp;").replace("<", "&lt;")
        ref = ref.replace("|", "&#124;").replace("\n", " ").replace("\r", " ")
        lines.append(f"| {row['service']} | {ref} | {row['commit_sha'][:12]} |")
    return "\n".join(lines)


class LinkReconciler:
    def __init__(
        self, registry: Registry, api: GitHubApi, entry_service: str = "frontend"
    ):
        self.registry = registry
        self.api = api
        self.entry_service = entry_service
        self.login: str | None = None

    def _find(
        self, repo: str, number: int, environment: str, excluded_id: int | None = None
    ) -> int | None:
        if self.login is None:
            self.login = self.api.get_authenticated_user()
        for comment in self.api.list_pr_comments(repo, number):
            body = str(comment.get("body") or "")
            if (
                comment.get("user", {}).get("login") == self.login
                and comment["id"] != excluded_id
                and marker(environment) in body
                and body.splitlines()[0] != f"preview {environment}: removed"
            ):
                return int(comment["id"])
        return None

    def _edit(self, repo: str, comment_id: int, body: str) -> bool:
        try:
            self.api.edit_comment(repo, comment_id, body)
        except GitHubError as exc:
            if exc.status == 404 and not exc.retryable:
                return False
            raise
        return True

    def reconcile(self) -> None:
        # Finish the read snapshot before any network call.
        db = self.registry.connect()
        try:
            db.execute("BEGIN")
            environments = [
                self.registry.get(row["name"], db)
                for row in db.execute(
                    "SELECT name FROM environments WHERE state != 'DELETED'"
                ).fetchall()
            ]
            versions = {
                row["id"]: row["version"]
                for row in db.execute("SELECT id, version FROM environments")
            }
            links = {
                (row["environment"], row["repo"], row["pr_number"]): dict(row)
                for row in db.execute("SELECT * FROM pr_links")
            }
        finally:
            db.close()
        wanted: dict[tuple[str, str, int], dict[str, Any]] = {}
        for environment in environments:
            if environment is None:
                continue
            for service in environment["services"]:
                pr = PrRef.parse(service["requested_ref"])
                if pr is None:
                    continue
                # The originating PR already receives command replies.
                if any(
                    environment["name"] == f"pr-{origin['service']}-{pr.number}"
                    and origin["repo"] == service["repo"]
                    for origin in environment["services"]
                ):
                    continue
                wanted[(environment["name"], service["repo"], pr.number)] = environment
        for key in sorted(wanted.keys() | links.keys()):
            environment, repo, number = key
            row = links.get(key)
            target = wanted.get(key)
            reason = "registry_write"
            replacing = (
                row is not None
                and target is not None
                and row["environment_id"] != target["id"]
            )
            version = (
                target["version"]
                if target
                else versions.get(row["environment_id"], 0)
                if row
                else 0
            )
            retired_id = row["retired_comment_id"] if row else None
            try:
                if row is not None and not replacing:
                    if row["attempted_version"] != version:
                        with self.registry.transaction() as db:
                            db.execute(
                                "UPDATE pr_links SET attempts=0, retryable=1, attempted_version=? WHERE environment=? AND repo=? AND pr_number=?",
                                (version, *key),
                            )
                    elif not row["retryable"] and row["attempts"] >= MAX_ATTEMPTS:
                        continue
                if (
                    row is not None
                    and row["status"] != "REMOVED"
                    and (target is None or row["environment_id"] != target["id"])
                ):
                    comment_id = row["comment_id"]
                    # A previous POST may have succeeded without recording its ID.
                    try:
                        if comment_id is None:
                            reason = "marker_search"
                            comment_id = self._find(
                                repo, number, environment, retired_id
                            )
                        if comment_id is not None:
                            reason = "remove_comment"
                            self._edit(repo, comment_id, removed_body(environment))
                    except Exception:
                        if not replacing:
                            raise
                        # Retirement is best effort for an obsolete instance.
                        LOG.warning(
                            "Cross-link retirement failed: repo=%s pr=%s env=%s reason=%s",
                            repo,
                            number,
                            environment,
                            reason,
                        )
                    if replacing:
                        retired_id = comment_id
                    reason = "registry_write"
                    with self.registry.transaction() as db:
                        db.execute(
                            "UPDATE pr_links SET status='REMOVED', comment_id=?, retired_comment_id=?, attempts=0, updated_at=? WHERE environment=? AND repo=? AND pr_number=?",
                            (comment_id, retired_id, now(), *key),
                        )
                    row["status"] = "REMOVED"
                if target is None:
                    continue
                if row is None or row["status"] == "REMOVED":
                    with self.registry.transaction() as db:
                        db.execute(
                            "INSERT OR REPLACE INTO pr_links (environment,repo,pr_number,environment_id,status,attempted_version,retired_comment_id,updated_at) VALUES (?,?,?,?,'ACTIVE',?,?,?)",
                            (*key, target["id"], version, retired_id, now()),
                        )
                    row = {"comment_id": None, "rendered_version": 0}
                comment_id = row["comment_id"]
                body = render(target, self.entry_service)
                if comment_id is not None:
                    if row["rendered_version"] >= target["version"]:
                        continue
                    reason = "edit_comment"
                    if not self._edit(repo, comment_id, body):
                        with self.registry.transaction() as db:
                            db.execute(
                                "UPDATE pr_links SET comment_id=NULL, rendered_version=0 WHERE environment=? AND repo=? AND pr_number=?",
                                key,
                            )
                        comment_id = None
                if comment_id is None:
                    reason = "marker_search"
                    comment_id = self._find(repo, number, environment, retired_id)
                    if comment_id is not None:
                        reason = "edit_comment"
                        if not self._edit(repo, comment_id, body):
                            comment_id = None
                    if comment_id is None:
                        reason = "post_comment"
                        comment_id = self.api.post_comment(repo, number, body)
                reason = "registry_write"
                with self.registry.transaction() as db:
                    db.execute(
                        "UPDATE pr_links SET comment_id=?, rendered_version=?, attempts=0, updated_at=? WHERE environment=? AND repo=? AND pr_number=?",
                        (comment_id, target["version"], now(), *key),
                    )
            except Exception as exc:  # noqa: BLE001 - isolate rows without logging API data
                # Neither arbitrary exception messages nor API payloads enter logs.
                LOG.warning(
                    "Cross-link failed: repo=%s pr=%s env=%s reason=%s",
                    repo,
                    number,
                    environment,
                    reason,
                )
                try:
                    with self.registry.transaction() as db:
                        db.execute(
                            "UPDATE pr_links SET attempts=attempts+1, retryable=?, attempted_version=?, updated_at=? WHERE environment=? AND repo=? AND pr_number=?",
                            (
                                not isinstance(exc, GitHubError) or exc.retryable,
                                version,
                                now(),
                                *key,
                            ),
                        )
                        attempts = db.execute(
                            "SELECT attempts, retryable FROM pr_links WHERE environment=? AND repo=? AND pr_number=?",
                            key,
                        ).fetchone()
                    if (
                        attempts
                        and not attempts["retryable"]
                        and attempts["attempts"] >= MAX_ATTEMPTS
                    ):
                        LOG.warning(
                            "Cross-link retry cap reached: repo=%s pr=%s env=%s",
                            repo,
                            number,
                            environment,
                        )
                except Exception:  # noqa: BLE001, S110 - row failure already logged
                    # A registry outage must not prevent attempts on other rows.
                    pass
