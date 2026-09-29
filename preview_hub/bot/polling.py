from __future__ import annotations

import logging
import math
import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from preview_hub.contracts import Catalog, InvalidInput, load_yaml
from preview_hub.registry import Registry

from .commands import Command, authorize, environment_name, parse_command, repository
from .executor import Executor, Result, format_reply
from .github import GitHubApi, GitHubError, UrllibGitHubApi
from .ledger import Ledger, overlap

LOG = logging.getLogger(__name__)


class PollingBot:
    def __init__(
        self,
        catalog: Catalog,
        api: GitHubApi,
        executor: Executor,
        ledger: Ledger,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.catalog = catalog
        self.api = api
        self.executor = executor
        self.ledger = ledger
        self.clock = clock
        self.started_at = clock().astimezone(UTC).isoformat()
        self.comment_floors: dict[str, datetime] = {}

    def handle(self, repo: str, comment: dict[str, Any]) -> None:
        body = str(comment.get("body") or "").strip()
        if not re.match(r"^/preview(?:\s|$)", body):
            return
        # Only accept issue URLs belonging to the polled catalog repository.
        match = re.fullmatch(
            r"https://api.github.com/repos/"
            + re.escape(repo)
            + r"/issues/([1-9][0-9]*)",
            str(comment.get("issue_url", "")),
        )
        if not match:
            return
        number = int(match[1])
        comment_id = int(comment["id"])
        command = None
        parse_error = "Invalid command"
        try:
            command = parse_command(body, self.catalog)
        except InvalidInput as exc:
            parse_error = str(exc)
        # Parsing is pure; claim the ID before any API call or execution.
        # Do not retain arbitrary malformed bodies in the ledger or logs.
        if not self.ledger.receive(
            comment_id,
            repo,
            number,
            str(comment.get("user", {}).get("login", "")),
            command.normalized() if command else "/preview",
            self.clock().isoformat(),
        ):
            return
        environment = "unknown"
        action = "invalid"
        try:
            services = [
                name
                for name, entry in self.catalog.services.items()
                if entry.repo == repo
            ]
            if len(services) == 1:
                environment = environment_name(services[0], number)
            if command is None:
                raise InvalidInput(parse_error)
            action = command.action
            pr = self.api.get_pr(repo, number)
            service = authorize(
                self.catalog, repo, str(comment.get("author_association", "")), pr
            )
            environment = environment_name(service, number)
        except InvalidInput as exc:
            self.ledger.finish(
                comment_id,
                "REJECTED",
                format_reply(environment, rejection=str(exc)),
                self.clock().isoformat(),
                str(exc),
                environment,
            )
            status = "REJECTED"
        except GitHubError:
            self.ledger.finish(
                comment_id,
                "FAILED",
                format_reply(
                    environment,
                    Result(
                        5,
                        {
                            "stage": "authorize",
                            "message": "Unable to read PR; run the command again",
                        },
                    ),
                ),
                self.clock().isoformat(),
                "Unable to read PR",
                environment,
            )
            status = "FAILED"
        else:
            self.ledger.running(comment_id, environment, command.normalized())
            result = self.executor.execute(
                command, environment, service, pr["head"]["sha"]
            )
            status = "DONE" if result.code == 0 else "FAILED"
            self.ledger.finish(
                comment_id,
                status,
                format_reply(environment, result),
                self.clock().isoformat(),
                None
                if result.code == 0
                else str(result.data.get("message", "Command failed")),
            )
        LOG.info(
            "repo=%s pr=%s comment=%s command=%s outcome=%s",
            repo,
            number,
            comment_id,
            action,
            status,
        )

    def recover(self) -> None:
        now = self.clock()
        for row in self.ledger.rows(("RUNNING", "RECEIVED")):
            if datetime.fromisoformat(row["received_at"]) < now - timedelta(minutes=10):
                error = "interrupted, run the command again"
                reply = format_reply(
                    row["environment"] or "unknown",
                    Result(5, {"stage": "exec", "message": error}),
                )
                self.ledger.finish(
                    row["comment_id"], "FAILED", reply, now.isoformat(), error
                )

    def replies(self) -> None:
        for row in self.ledger.rows(("DONE", "FAILED", "REJECTED")):
            if row["reply_comment_id"] is not None or not self.ledger.claim_reply(
                row["comment_id"], self.clock().timestamp()
            ):
                continue
            body = self.ledger.initial_replies.get(row["comment_id"])
            if body is None:
                environment = row["environment"] or "unknown"
                data: dict[str, Any] = {"state": row["status"]}
                if row["environment"] and environment != "unknown":
                    current = self.executor.execute(Command("status", {}), environment)
                    if current.code == 0:
                        data.update(current.data)
                if row["status"] == "REJECTED":
                    body = format_reply(
                        environment, rejection=row["error"] or "Rejected"
                    )
                else:
                    if row["error"]:
                        data["message"] = row["error"]
                    body = format_reply(
                        environment, Result(0 if row["status"] == "DONE" else 5, data)
                    )
            try:
                reply_id = self.api.post_comment(row["repo"], row["pr_number"], body)
            except GitHubError as exc:
                self.ledger.defer_reply(row["comment_id"], exc.retry_at, exc.attempted)
                LOG.warning("Reply delivery failed: comment=%s", row["comment_id"])
            else:
                self.ledger.replied(row["comment_id"], reply_id)
                self.ledger.initial_replies.pop(row["comment_id"], None)

    def poll(self) -> None:
        self.recover()
        for repo in sorted({entry.repo for entry in self.catalog.services.values()}):
            try:
                comments_since, closed_since = self.ledger.cursor(repo, self.started_at)
                floor = self.comment_floors.setdefault(
                    repo, datetime.fromisoformat(comments_since)
                )
                try:
                    comments = self.api.list_issue_comments(
                        repo, overlap(comments_since)
                    )
                    newest = datetime.fromisoformat(comments_since)
                    for comment in sorted(
                        comments, key=lambda row: (row["updated_at"], row["id"])
                    ):
                        # The API overlap may return history, including edited old comments.
                        created = comment.get("created_at", comment["updated_at"])
                        if datetime.fromisoformat(created) < floor:
                            continue
                        self.handle(repo, comment)
                        newest = max(
                            newest, datetime.fromisoformat(comment["updated_at"])
                        )
                    self.ledger.advance(repo, comments=newest.isoformat())
                except GitHubError:
                    LOG.warning("Comment poll failed: repo=%s", repo)
                try:
                    scan_started = self.clock().isoformat()
                    closed = self.api.list_closed_prs(repo, overlap(closed_since))
                    services = [
                        name
                        for name, entry in self.catalog.services.items()
                        if entry.repo == repo
                    ]
                    if len(services) != 1:
                        continue
                    complete = True
                    for pr in closed:
                        if (
                            pr.get("state") != "closed"
                            or repository(pr, "base") != repo
                        ):
                            continue
                        name = environment_name(services[0], int(pr["number"]))
                        env = self.ledger.registry.get(name)
                        if env is not None and env["state"] != "DELETED":
                            result = self.executor.execute(Command("down", {}), name)
                            complete = complete and result.code == 0
                    if complete:
                        self.ledger.advance(repo, closed=scan_started)
                except (GitHubError, InvalidInput):
                    LOG.warning("Closed PR sweep failed: repo=%s", repo)
            except Exception:  # noqa: BLE001 - keep polling without leaking exception data
                # Exception text may contain credentials or response bodies.
                LOG.warning("Repository poll failed: repo=%s", repo)
        self.replies()


def parse_interval(value: str) -> float:
    try:
        result = float(value)
    except ValueError:
        raise InvalidInput("PHUB_BOT_INTERVAL must be finite and positive") from None
    if not math.isfinite(result) or result <= 0:
        raise InvalidInput("PHUB_BOT_INTERVAL must be finite and positive")
    return result


def serve(*, sleep: Callable[[float], None] = time.sleep) -> None:
    # Lazy parsing: unrelated CLI commands must not depend on bot settings.
    interval = parse_interval(os.environ.get("PHUB_BOT_INTERVAL", "20"))
    catalog = Catalog.parse(
        load_yaml(Path(os.environ.get("PHUB_CATALOG", "/etc/phub/catalog.yaml")))
    )
    registry = Registry(Path(os.environ.get("PHUB_STATE_DIR", "/state")))
    api = UrllibGitHubApi()
    bot = PollingBot(catalog, api, Executor(), Ledger(registry))
    logging.basicConfig(level=logging.INFO)
    missing_logged = False
    # A singleton lock prevents simultaneous polling and stale recovery during an
    # active command. Unlike environment locks this does not invoke hub recovery.
    import fcntl

    with (registry.state_dir / "bot.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            try:
                if not api.token_present():
                    if not missing_logged:
                        LOG.warning("token missing")
                        missing_logged = True
                else:
                    bot.poll()
            except Exception:  # noqa: BLE001 - keep polling without leaking exception data
                # Do not log exception messages or tracebacks containing API data.
                LOG.warning("Bot poll failed")
            sleep(interval)
