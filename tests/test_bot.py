from __future__ import annotations

import copy
import json
import logging
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from preview_hub.bot.commands import Command, authorize, environment_name, parse_command
from preview_hub.bot.executor import Executor, Result, format_reply
from preview_hub.bot.github import GitHubError
from preview_hub.bot.ledger import Ledger, overlap
from preview_hub.bot.polling import PollingBot, parse_interval
from preview_hub.cli import main
from preview_hub.contracts import Catalog, CatalogEntry, InvalidInput
from preview_hub.registry import Registry

REPO = "owner/backend"
SHA = "a" * 40
NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)
PR = {
    "number": 42,
    "state": "open",
    "head": {"sha": SHA, "repo": {"full_name": REPO}},
    "base": {"repo": {"full_name": REPO}},
    "updated_at": NOW.isoformat(),
}


@pytest.fixture
def catalog():
    return Catalog(
        {
            "backend": CatalogEntry(REPO, "main"),
            "frontend": CatalogEntry("owner/frontend", "main"),
        },
        "http://{subdomain}.{env}.localhost:18080",
    )


class Api:
    def __init__(self):
        self.comments = [
            {
                "id": 100,
                "body": "/preview up backend=old frontend=release ttl=2h",
                "issue_url": f"https://api.github.com/repos/{REPO}/issues/42",
                "user": {"login": "owner"},
                "author_association": "OWNER",
                "updated_at": NOW.isoformat(),
            }
        ]
        self.pr = copy.deepcopy(PR)
        self.closed = []
        self.posts = []
        self.polls = []
        self.closed_polls = []
        self.fail_post = False
        self.fail_get = False

    def list_issue_comments(self, repo, since):
        self.polls.append((repo, since))
        return self.comments if repo == REPO else []

    def get_pr(self, repo, number):
        if self.fail_get:
            raise GitHubError("unavailable")
        return self.pr

    def list_closed_prs(self, repo, since):
        self.closed_polls.append((repo, since))
        return self.closed if repo == REPO else []

    def post_comment(self, repo, number, body):
        self.posts.append((repo, number, body))
        if self.fail_post:
            raise GitHubError("unavailable")
        return 900 + len(self.posts)


class Runner:
    def __init__(self):
        self.calls = []
        self.code = 0

    def __call__(self, args):
        self.calls.append(args)
        return subprocess.CompletedProcess(
            args,
            self.code,
            json.dumps(
                {
                    "state": "DELETED" if args[4] == "down" else "READY",
                    "services": [
                        {
                            "service": "backend",
                            "commit_sha": SHA,
                            "public_url": "http://api.localhost",
                        }
                    ],
                }
            ),
            json.dumps(
                {
                    "stage": "build",
                    "service": "backend",
                    "message": "build failed",
                    "log_excerpt": "compiler error",
                }
            ),
        )


@pytest.fixture
def rig(tmp_path, catalog):
    api, runner = Api(), Runner()
    ledger = Ledger(Registry(tmp_path))
    bot = PollingBot(catalog, api, Executor(runner), ledger, clock=lambda: NOW)
    return bot, api, runner, ledger


@pytest.mark.parametrize(
    "body,action,refs,ttl",
    [
        ("/preview up", "up", {}, None),
        (" /preview up frontend=topic/a ttl=2h\n", "up", {"frontend": "topic/a"}, "2h"),
        ("/preview update backend=main", "update", {"backend": "main"}, None),
        ("/preview down", "down", {}, None),
        ("/preview status", "status", {}, None),
    ],
)
def test_parser(catalog, body, action, refs, ttl):
    assert parse_command(body, catalog) == Command(action, refs, ttl)


@pytest.mark.parametrize(
    "body",
    [
        "/preview",
        "/preview destroy",
        "/preview update",
        "/preview down backend=main",
        "/preview status ttl=2h",
        "/preview up unknown=main",
        "/preview up backend=",
        "/preview up backend=x backend=y",
        "/preview up ttl=1h ttl=2h",
        "/preview update backend=main ttl=1h",
        "/preview up ttl=0h",
        "/preview up ttl=8d",
        "/preview up\nplease run this",
        "/previewevil up",
    ],
)
def test_bad_parser(catalog, body):
    with pytest.raises(InvalidInput):
        parse_command(body, catalog)


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_authorized(catalog, association):
    assert authorize(catalog, REPO, association, PR) == "backend"


@pytest.mark.parametrize(
    "change",
    [
        "NONE",
        "CONTRIBUTOR",
        "FIRST_TIMER",
        "fork",
        "closed",
        "repo",
        "deleted_head",
        "sha",
    ],
)
def test_authorization_rejects(catalog, change):
    pr = copy.deepcopy(PR)
    association, repo = "OWNER", REPO
    if change == "fork":
        pr["head"]["repo"]["full_name"] = "outsider/backend"
    elif change == "closed":
        pr["state"] = "closed"
    elif change == "repo":
        repo = "outsider/backend"
    elif change == "deleted_head":
        pr["head"]["repo"] = None
    elif change == "sha":
        pr["head"]["sha"] = "main"
    else:
        association = change
    with pytest.raises(InvalidInput):
        authorize(catalog, repo, association, pr)


def test_exactly_once_and_pinning_across_restart(rig, catalog):
    bot, api, runner, ledger = rig
    bot.poll()
    bot.poll()
    restarted = PollingBot(
        catalog,
        api,
        Executor(runner),
        Ledger(Registry(ledger.registry.state_dir)),
        clock=lambda: NOW,
    )
    restarted.poll()
    assert len(runner.calls) == len(api.posts) == 1
    args = runner.calls[0]
    assert args == [
        "docker",
        "exec",
        "phub-hub",
        "phub",
        "up",
        "pr-backend-42",
        "--set",
        f"backend={SHA}",
        "--set",
        "frontend=release",
        "--ttl",
        "2h",
        "--format",
        "json",
    ]
    assert ledger.rows(("DONE",))[0]["reply_comment_id"] == 901
    assert api.polls[2][1] == (NOW - timedelta(seconds=60)).isoformat()
    assert ledger.cursor(REPO)[0] == NOW.isoformat()


@pytest.mark.parametrize("kind", ["association", "fork", "closed", "malformed"])
def test_rejected_commands_never_execute(rig, kind):
    bot, api, runner, ledger = rig
    if kind == "association":
        api.comments[0]["author_association"] = "NONE"
    elif kind == "fork":
        api.pr["head"]["repo"]["full_name"] = "fork/backend"
    elif kind == "closed":
        api.pr["state"] = "closed"
    else:
        api.comments[0]["body"] = "/preview up garbage"
    bot.poll()
    assert not runner.calls
    assert len(api.posts) == 1
    assert api.posts[0][2].startswith("preview pr-backend-42: REJECTED\n\nReason:")
    rejected = ledger.rows(("REJECTED",))
    assert len(rejected) == 1
    if kind != "malformed":
        assert (
            rejected[0]["command"] == "/preview up backend=old frontend=release ttl=2h"
        )


def test_reply_format_and_busy():
    success = format_reply(
        "pr-backend-42",
        Result(
            0,
            {
                "state": "READY",
                "services": [
                    {
                        "service": "backend",
                        "commit_sha": SHA,
                        "public_url": "http://api.localhost",
                    }
                ],
            },
        ),
    )
    assert (
        success
        == "preview pr-backend-42: READY\n\n| service | commit | URL |\n| --- | --- | --- |\n| backend | aaaaaaaaaaaa | http://api.localhost |"
    )
    failure = format_reply(
        "pr-backend-42",
        Result(
            5,
            {
                "stage": "build",
                "service": "backend",
                "message": "failed",
                "log_excerpt": "compile\nerror",
            },
        ),
    )
    assert (
        "FAILED" in failure
        and "Stage: build" in failure
        and "Service: backend" in failure
        and "compile<br>error" in failure
    )
    executor = Executor(lambda args: subprocess.CompletedProcess(args, 3, "", "busy"))
    assert "busy, retry" in format_reply(
        "pr-backend-42", executor.execute(Command("status", {}), "pr-backend-42")
    )


def test_closed_pr_sweep_retries_failure_without_advancing(rig):
    bot, api, runner, ledger = rig
    api.comments = []
    api.closed = [{**copy.deepcopy(PR), "state": "closed"}]
    with ledger.registry.transaction() as db:
        db.execute(
            "INSERT INTO environments(name,state,spec_json,ttl_expires_at,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (
                "pr-backend-42",
                "READY",
                "{}",
                NOW.isoformat(),
                NOW.isoformat(),
                NOW.isoformat(),
            ),
        )
    initial = ledger.cursor(REPO)[1]
    runner.code = 5
    bot.poll()
    assert ledger.cursor(REPO)[1] == initial
    assert runner.calls[0] == [
        "docker",
        "exec",
        "phub-hub",
        "phub",
        "down",
        "pr-backend-42",
        "--format",
        "json",
    ]
    runner.code = 0
    bot.poll()
    assert len(runner.calls) == 2
    assert ledger.cursor(REPO)[1] == NOW.isoformat()


@pytest.mark.parametrize("status", ["RUNNING", "RECEIVED"])
def test_crash_recovery_does_not_reexecute(rig, status):
    bot, api, runner, ledger = rig
    ledger.receive(
        100, REPO, 42, "owner", "/preview up", (NOW - timedelta(minutes=11)).isoformat()
    )
    if status == "RUNNING":
        ledger.running(100, "pr-backend-42", "/preview up")
    bot.poll()
    bot.poll()
    assert not runner.calls
    assert len(api.posts) == 1
    assert "interrupted, run the command again" in api.posts[0][2]
    assert ledger.rows(("FAILED",))[0]["error"] == "interrupted, run the command again"


def test_fresh_running_not_recovered(rig):
    bot, api, runner, ledger = rig
    ledger.receive(100, REPO, 42, "owner", "/preview up", NOW.isoformat())
    ledger.running(100, "pr-backend-42", "/preview up")
    bot.poll()
    assert not runner.calls and not api.posts


def test_reply_limit_resets_on_restart(rig, catalog):
    bot, api, runner, ledger = rig
    api.fail_post = True
    for _ in range(6):
        bot.poll()
    assert len(api.posts) == 3
    restarted = PollingBot(
        catalog,
        api,
        Executor(runner),
        Ledger(Registry(ledger.registry.state_dir)),
        clock=lambda: NOW,
    )
    for _ in range(6):
        restarted.poll()
    assert len(api.posts) == 6
    assert [args[4] for args in runner.calls] == ["up"] + ["status"] * 5
    assert ledger.rows(("DONE",))[0]["reply_comment_id"] is None
    with ledger.registry.connect() as db:
        assert [row[0] for row in db.execute("SELECT key FROM schema_meta")] == [
            "version"
        ]


def test_unsent_reply_succeeds_on_next_poll(rig):
    bot, api, runner, ledger = rig
    api.fail_post = True
    bot.poll()
    api.fail_post = False
    bot.poll()
    bot.poll()
    assert len(api.posts) == 2
    assert [args[4:] for args in runner.calls[1:]] == [
        ["status", "pr-backend-42", "--format", "json"]
    ]
    assert ledger.rows(("DONE",))[0]["reply_comment_id"] == 902


def test_noncommands_advance_cursor_without_ledger(rig):
    bot, api, runner, ledger = rig
    api.comments[0]["body"] = "hello"
    bot.poll()
    assert not runner.calls and not api.posts
    assert ledger.rows(("RECEIVED", "DONE")) == []
    assert ledger.cursor(REPO)[0] == NOW.isoformat()


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "invalid", ""])
def test_interval_invalid(value, monkeypatch, capsys):
    monkeypatch.setenv("PHUB_BOT_INTERVAL", value)
    with pytest.raises(InvalidInput):
        parse_interval(value)
    assert main(["bot"]) == 2
    assert "PHUB_BOT_INTERVAL" in capsys.readouterr().err


def test_interval_lazy(monkeypatch, tmp_path):
    monkeypatch.setenv("PHUB_BOT_INTERVAL", "invalid")
    from preview_hub.git import GitCliSource
    from preview_hub.lifecycle import Context
    from preview_hub.runners.fake import FakeRunner

    ctx = Context(
        Registry(tmp_path),
        Catalog({}, ""),
        GitCliSource(tmp_path / "src", {}),
        FakeRunner(),
    )
    assert main(["list", "--format", "json"], ctx) == 0
    assert parse_interval("0.5") == 0.5


def test_revision_one_migration(tmp_path):
    db = sqlite3.connect(tmp_path / "state.db")
    db.executescript(
        (
            Path(__file__).parents[1] / "preview_hub/migrations/0001_initial.sql"
        ).read_text()
    )
    db.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("INSERT INTO schema_meta VALUES ('version', '1')")
    db.commit()
    db.close()
    registry = Registry(tmp_path)
    registry.migrate()
    with registry.connect() as db:
        assert (
            db.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()[
                0
            ]
            == "2"
        )
        assert [row[1] for row in db.execute("PRAGMA table_info(bot_comments)")] == [
            "comment_id",
            "repo",
            "pr_number",
            "author",
            "command",
            "status",
            "environment",
            "reply_comment_id",
            "error",
            "received_at",
            "finished_at",
        ]
        assert [row[1] for row in db.execute("PRAGMA table_info(bot_cursors)")] == [
            "repo",
            "comments_since",
            "closed_checked_at",
        ]


def test_missing_token_logs_once_and_idles(tmp_path, catalog, monkeypatch, caplog):
    from preview_hub.bot import polling

    class MissingApi:
        def token_present(self):
            return False

    monkeypatch.setattr(polling, "UrllibGitHubApi", MissingApi)
    monkeypatch.setattr(polling, "load_yaml", lambda path: None)
    monkeypatch.setattr(polling.Catalog, "parse", lambda value: catalog)
    monkeypatch.setenv("PHUB_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("PHUB_BOT_INTERVAL", "1")
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise KeyboardInterrupt

    with caplog.at_level(logging.WARNING), pytest.raises(KeyboardInterrupt):
        polling.serve(sleep=sleep)
    assert sleeps == [1, 1, 1]
    assert caplog.text.count("token missing") == 1


def test_name_and_overlap():
    assert environment_name("backend", 42) == "pr-backend-42"
    assert overlap(NOW.isoformat()) == (NOW - timedelta(seconds=60)).isoformat()


def test_crash_after_effect_does_not_repeat(rig, catalog):
    bot, api, runner, ledger = rig

    def interrupted(args):
        runner(args)
        raise KeyboardInterrupt

    bot.executor = Executor(interrupted)
    with pytest.raises(KeyboardInterrupt):
        bot.poll()
    assert len(runner.calls) == 1
    assert len(ledger.rows(("RUNNING",))) == 1
    restarted = PollingBot(
        catalog,
        api,
        Executor(runner),
        Ledger(Registry(ledger.registry.state_dir)),
        clock=lambda: NOW + timedelta(minutes=11),
    )
    restarted.poll()
    assert len(runner.calls) == 1
    assert len(api.posts) == 1
    assert "interrupted" in api.posts[0][2]


def test_reply_retry_after_is_in_memory(rig):
    bot, api, _runner, ledger = rig

    def rate_limited(repo, number, body):
        raise GitHubError(
            "rate limited", retry_at=(NOW + timedelta(minutes=2)).timestamp()
        )

    api.post_comment = rate_limited
    bot.poll()
    restarted = Ledger(Registry(ledger.registry.state_dir))
    assert not ledger.claim_reply(100, (NOW + timedelta(minutes=1)).timestamp())
    assert restarted.claim_reply(100, (NOW + timedelta(minutes=1)).timestamp())
    assert ledger.claim_reply(100, (NOW + timedelta(minutes=3)).timestamp())


def test_failed_poll_does_not_advance_cursor(rig):
    bot, api, runner, ledger = rig

    def fail(repo, since):
        raise GitHubError("unavailable")

    api.list_issue_comments = fail
    before = ledger.cursor(REPO)[0]
    bot.poll()
    assert ledger.cursor(REPO)[0] == before
    assert not runner.calls


@pytest.mark.parametrize(
    "status,error",
    [("DONE", None), ("FAILED", "original failure"), ("REJECTED", "not allowed")],
)
def test_reply_rebuilds_from_row_and_fresh_status(rig, catalog, status, error):
    _bot, api, runner, ledger = rig
    ledger.receive(100, REPO, 42, "owner", "/preview up", NOW.isoformat())
    ledger.finish(100, status, "stale body", NOW.isoformat(), error, "pr-backend-42")
    restarted = PollingBot(
        catalog,
        api,
        Executor(runner),
        Ledger(Registry(ledger.registry.state_dir)),
        clock=lambda: NOW,
    )
    restarted.replies()
    assert runner.calls[0][4:] == ["status", "pr-backend-42", "--format", "json"]
    body = api.posts[0][2]
    assert "stale body" not in body
    assert (error or "http://api.localhost") in body
    assert (status if error else "READY") in body


def test_token_appearing_starts_polling_without_restart(
    tmp_path, catalog, monkeypatch, caplog
):
    from preview_hub.bot import polling
    from preview_hub.bot.github import UrllibGitHubApi

    token = tmp_path / "github_token"
    monkeypatch.setattr(
        polling, "UrllibGitHubApi", lambda: UrllibGitHubApi(token_path=token)
    )
    monkeypatch.setattr(polling, "load_yaml", lambda path: None)
    monkeypatch.setattr(polling.Catalog, "parse", lambda value: catalog)
    monkeypatch.setenv("PHUB_STATE_DIR", str(tmp_path))
    polls = []
    monkeypatch.setattr(polling.PollingBot, "poll", lambda self: polls.append(True))
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            token.write_text("test-token")
        if len(sleeps) == 3:
            raise KeyboardInterrupt

    with caplog.at_level(logging.WARNING), pytest.raises(KeyboardInterrupt):
        polling.serve(sleep=sleep)
    assert polls == [True]
    assert caplog.text.count("token missing") == 1
