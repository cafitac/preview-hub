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
                "html_url": f"https://github.com/{REPO}/pull/42#issuecomment-100",
                "user": {"login": "owner"},
                "author_association": "OWNER",
                "updated_at": NOW.isoformat(),
                "created_at": NOW.isoformat(),
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


def test_closed_pr_sweep_retries_failure_after_advancing(rig):
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
    initial = ledger.cursor(REPO, NOW.isoformat())[1]
    assert initial == NOW.isoformat()
    bot.clock = lambda: NOW + timedelta(minutes=2)
    runner.code = 5
    bot.poll()
    assert ledger.cursor(REPO)[1] == bot.clock().isoformat()
    assert bot.closed_retries[REPO] == {"pr-backend-42"}
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
    api.closed = []
    bot.poll()
    assert len(runner.calls) == 2
    assert not bot.closed_retries[REPO]
    assert api.closed_polls[2][1] == overlap(bot.clock().isoformat())


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
    assert [args[4] for args in runner.calls] == ["up"] + ["status"] * 3
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
    assert len(runner.calls) == 1
    assert api.posts[0][2] == api.posts[1][2]
    assert not ledger.initial_replies
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
    before = ledger.cursor(REPO, NOW.isoformat())[0]
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


@pytest.mark.parametrize("edited", [False, True])
def test_missing_cursor_skips_history_even_in_overlap(rig, edited):
    bot, api, runner, ledger = rig
    old = copy.deepcopy(api.comments[0])
    old["id"] = 99
    old["body"] = "/preview down"
    old["created_at"] = (NOW - timedelta(seconds=30)).isoformat()
    old["updated_at"] = NOW.isoformat() if edited else old["created_at"]
    api.comments = [old]
    bot.clock = lambda: NOW + timedelta(minutes=1)
    bot.poll()
    assert ledger.cursor(REPO)[0] == NOW.isoformat()
    assert api.polls[0] == (REPO, overlap(NOW.isoformat()))
    assert not runner.calls and not api.posts
    assert not ledger.rows(("DONE", "REJECTED"))
    api.comments.append({**old, "id": 101, "created_at": NOW.isoformat()})
    api.comments[-1]["updated_at"] = NOW.isoformat()
    bot.poll()
    assert len(runner.calls) == len(api.posts) == 1


@pytest.mark.parametrize("code", [0, 5])
def test_original_reply_survives_failed_post(rig, code):
    bot, api, runner, ledger = rig
    runner.code = code
    api.fail_post = True
    bot.poll()
    original = api.posts[0][2]
    assert ledger.initial_replies[100] == original
    if code:
        assert "Stage: build" in original
        assert "Service: backend" in original
        assert "compiler error" in original
    runner.code = 0
    api.fail_post = False
    bot.poll()
    assert api.posts[1][2] == original
    assert len(runner.calls) == 1
    assert not ledger.initial_replies


@pytest.mark.parametrize("where", ["cursor", "comments", "closed"])
def test_repository_exception_does_not_stop_other_repositories(
    rig, monkeypatch, caplog, where
):
    bot, api, _runner, ledger = rig
    target, name = {
        "cursor": (ledger, "cursor"),
        "comments": (api, "list_issue_comments"),
        "closed": (api, "list_closed_prs"),
    }[where]
    original = getattr(target, name)

    def fail(repo, *args):
        if repo == REPO:
            raise sqlite3.OperationalError("secret-token response-body")
        return original(repo, *args)

    monkeypatch.setattr(target, name, fail)
    with caplog.at_level(logging.WARNING):
        bot.poll()
    assert any(repo == "owner/frontend" for repo, _since in api.polls)
    assert "Repository poll failed" in caplog.text
    assert "secret-token" not in caplog.text and "response-body" not in caplog.text


@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit])
def test_serve_continues_after_poll_exception(
    tmp_path, catalog, monkeypatch, caplog, stop
):
    from preview_hub.bot import polling

    class PresentApi:
        def token_present(self):
            return True

    monkeypatch.setattr(polling, "UrllibGitHubApi", PresentApi)
    monkeypatch.setattr(polling, "load_yaml", lambda path: None)
    monkeypatch.setattr(polling.Catalog, "parse", lambda value: catalog)
    monkeypatch.setenv("PHUB_STATE_DIR", str(tmp_path))
    calls = []

    def poll(self):
        calls.append(True)
        if len(calls) == 1:
            raise TypeError("secret-token response-body")
        if len(calls) == 3:
            raise stop

    monkeypatch.setattr(polling.PollingBot, "poll", poll)
    sleeps = []
    with caplog.at_level(logging.WARNING), pytest.raises(stop):
        polling.serve(sleep=sleeps.append)
    assert len(calls) == 3 and len(sleeps) == 2
    assert caplog.text.count("Bot poll failed") == 1
    assert "secret-token" not in caplog.text and "response-body" not in caplog.text


def test_reply_body_and_budget_are_lost_on_restart(rig):
    bot, api, _runner, ledger = rig
    api.fail_post = True
    for _ in range(4):
        bot.poll()
    assert len(api.posts) == 3
    assert ledger.initial_replies
    restarted = Ledger(Registry(ledger.registry.state_dir))
    assert not restarted.initial_replies
    assert restarted.claim_reply(100, NOW.timestamp())


def test_hub_and_bot_share_configurable_uid_and_state_volume():
    from preview_hub.contracts import load_yaml

    services = load_yaml(Path("deploy/hub-stack/compose.yaml"))["services"]
    for name in ("hub", "bot"):
        assert services[name]["user"] == "${PHUB_UID_GID:-0:0}"
        assert "phub-state:/state" in services[name]["volumes"]
        assert "/var/run/docker.sock:/var/run/docker.sock" in services[name]["volumes"]


def test_overlap_still_accepts_delayed_comments_after_initial_floor(rig):
    bot, api, runner, _ledger = rig
    api.comments[0]["updated_at"] = (NOW + timedelta(seconds=30)).isoformat()
    bot.poll()
    api.comments = [
        {
            **api.comments[0],
            "id": 101,
            "created_at": (NOW + timedelta(seconds=10)).isoformat(),
            "updated_at": (NOW + timedelta(seconds=10)).isoformat(),
        }
    ]
    bot.poll()
    assert len(runner.calls) == len(api.posts) == 2


def test_existing_cursor_accepts_late_overlap_comment_after_restart(rig, catalog):
    bot, api, runner, ledger = rig
    bot.poll()
    api.comments = [
        {
            **api.comments[0],
            "id": 101,
            "created_at": (NOW - timedelta(seconds=5)).isoformat(),
            "updated_at": (NOW - timedelta(seconds=5)).isoformat(),
        }
    ]
    restarted = PollingBot(
        catalog,
        api,
        Executor(runner),
        Ledger(Registry(ledger.registry.state_dir)),
        clock=lambda: NOW,
    )
    restarted.poll()
    restarted.poll()
    assert len(runner.calls) == len(api.posts) == 2


@pytest.mark.parametrize(
    "error",
    [
        GitHubError("cooldown", attempted=False),
        GitHubError("rate limit", retry_at=123, retryable=True),
        GitHubError("temporary", retryable=True),
    ],
)
def test_retryable_pr_read_leaves_batch_unclaimed_and_cursor_unchanged(rig, error):
    bot, api, runner, ledger = rig
    api.comments.append({**api.comments[0], "id": 101})
    for comment in api.comments:
        comment["updated_at"] = (NOW + timedelta(seconds=10)).isoformat()
    reads = []
    original = api.get_pr

    def fail(repo, number):
        reads.append(number)
        raise error

    api.get_pr = fail
    bot.poll()
    assert reads == [42]
    assert not ledger.rows(("RECEIVED", "FAILED", "DONE"))
    assert ledger.cursor(REPO)[0] == NOW.isoformat()
    assert not runner.calls and not api.posts
    assert not any(repo == REPO for repo, _ in api.closed_polls)
    api.get_pr = original
    bot.poll()
    assert len(runner.calls) == len(api.posts) == 2


@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("field", ["user", "head", "head_repo", "base", "base_repo"])
def test_nullable_author_and_pr_fields_are_rejected(rig, field, missing):
    bot, api, runner, ledger = rig
    if field == "user":
        target, key = api.comments[0], "user"
    elif field.endswith("_repo"):
        target, key = api.pr[field.removesuffix("_repo")], "repo"
    else:
        target, key = api.pr, field
    if missing:
        target.pop(key)
    else:
        target[key] = None
    bot.poll()
    assert len(ledger.rows(("REJECTED",))) == 1
    assert not runner.calls
    assert any(repo == REPO for repo, _ in api.closed_polls)


def test_unclaimed_comment_error_stops_batch_and_sweep(rig, caplog):
    bot, api, runner, ledger = rig
    bad = {**api.comments[0], "id": None}
    api.comments = [
        bad,
        {
            **api.comments[0],
            "id": 101,
            "updated_at": (NOW + timedelta(seconds=20)).isoformat(),
        },
    ]
    with caplog.at_level(logging.WARNING):
        bot.poll()
    assert not runner.calls
    assert ledger.cursor(REPO)[0] == NOW.isoformat()
    assert not any(repo == REPO for repo, _ in api.closed_polls)
    assert "Repository poll failed" in caplog.text


def test_closed_retry_set_is_bounded_and_logs_overflow(rig, caplog):
    bot, _api, _runner, ledger = rig
    bot.closed_retry_limit = 1
    with ledger.registry.transaction() as db:
        for number in (42, 43):
            db.execute(
                "INSERT INTO environments(name,state,spec_json,ttl_expires_at,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (
                    f"pr-backend-{number}",
                    "READY",
                    "{}",
                    NOW.isoformat(),
                    NOW.isoformat(),
                    NOW.isoformat(),
                ),
            )
    _runner.code = 5
    with caplog.at_level(logging.WARNING):
        bot.cleanup(REPO, "pr-backend-42")
        bot.cleanup(REPO, "pr-backend-43")
    assert bot.closed_retries[REPO] == {"pr-backend-42"}
    assert "retry set full" in caplog.text


def test_invalid_closed_pr_does_not_block_sweep(rig, caplog):
    bot, api, runner, ledger = rig
    api.comments = []
    api.closed = [
        {**PR, "state": "closed", "base": None},
        {**PR, "state": "closed", "number": None},
    ]
    bot.clock = lambda: NOW + timedelta(minutes=1)
    with caplog.at_level(logging.WARNING):
        bot.poll()
    assert ledger.cursor(REPO)[1] == bot.clock().isoformat()
    assert not runner.calls
    assert caplog.text.count("Invalid closed PR skipped") == 2


@pytest.mark.parametrize("retry_at", [0, 123])
def test_nonretryable_pr_read_retains_failed_claim_behavior(rig, retry_at):
    bot, api, runner, ledger = rig

    def fail(repo, number):
        raise GitHubError("unavailable", retry_at=retry_at)

    api.get_pr = fail
    bot.poll()
    bot.poll()
    assert len(ledger.rows(("FAILED",))) == 1
    assert not runner.calls
    assert len(api.posts) == 1


@pytest.mark.parametrize("restart", [False, True])
def test_edited_comment_created_before_floor_is_never_executed(rig, catalog, restart):
    bot, api, runner, ledger = rig
    api.comments[0].update(
        body="ordinary comment",
        created_at=(NOW - timedelta(minutes=5)).isoformat(),
    )
    bot.poll()
    api.comments[0].update(
        body="/preview down", updated_at=(NOW + timedelta(minutes=1)).isoformat()
    )
    if restart:
        bot = PollingBot(
            catalog,
            api,
            Executor(runner),
            Ledger(Registry(ledger.registry.state_dir)),
            clock=lambda: NOW + timedelta(minutes=1),
        )
    bot.poll()
    assert not runner.calls
    assert not ledger.contains(100)


@pytest.mark.parametrize("offset,eligible", [(-61, False), (-60, True), (-59, True)])
def test_persisted_cursor_floor_boundary(rig, offset, eligible):
    bot, api, runner, ledger = rig
    ledger.cursor(REPO, NOW.isoformat())
    api.comments[0]["created_at"] = (NOW + timedelta(seconds=offset)).isoformat()
    bot.poll()
    assert bool(runner.calls) is eligible


def test_reply_query_excludes_acknowledged_rows_in_sql(rig, monkeypatch):
    bot, api, _runner, ledger = rig
    for comment_id, status in enumerate(("DONE", "FAILED", "REJECTED"), 1):
        for identifier in (comment_id, comment_id + 10):
            ledger.receive(identifier, REPO, 42, "owner", "/preview", NOW.isoformat())
            ledger.finish(identifier, status, "reply", NOW.isoformat())
        ledger.replied(comment_id, 900 + comment_id)
    original = ledger.rows
    selected = []

    def rows(statuses, *, unreplied=False):
        result = original(statuses, unreplied=unreplied)
        selected.extend(row["comment_id"] for row in result)
        return result

    monkeypatch.setattr(ledger, "rows", rows)
    bot.replies()
    assert selected == [11, 12, 13]
    assert len(api.posts) == 3


def test_503_cooldown_then_404_does_not_starve_comments(rig, tmp_path, monkeypatch):
    import io
    from email.message import Message
    from urllib.error import HTTPError

    from preview_hub.bot import github

    bot, api, runner, ledger = rig
    token = tmp_path / "token"
    token.write_text("test-token")
    now = [NOW.timestamp()]
    monkeypatch.setattr(github.time, "time", lambda: now[0])
    statuses = iter([503, 503, 503, 404])
    calls = []

    def transport(request, *, timeout):
        calls.append(request.full_url)
        raise HTTPError(
            request.full_url, next(statuses), "failure", Message(), io.BytesIO()
        )

    client = github.UrllibGitHubApi(token, transport=transport, sleep=lambda _: None)
    api.get_pr = client.get_pr
    api.comments[0].update(
        body="/preview status", updated_at=(NOW + timedelta(seconds=10)).isoformat()
    )
    bot.poll()
    assert len(calls) == 3
    assert client.retry_at > now[0]
    assert not ledger.contains(100)
    assert ledger.cursor(REPO)[0] == NOW.isoformat()

    # An active cooldown performs no request and cannot consume the comment.
    bot.poll()
    assert len(calls) == 3
    assert not ledger.contains(100)
    assert ledger.cursor(REPO)[0] == NOW.isoformat()

    now[0] = client.retry_at
    bot.poll()
    bot.poll()
    assert len(calls) == 4
    assert client.retry_at == 0
    assert len(ledger.rows(("REJECTED",))) == 1
    assert ledger.cursor(REPO)[0] == api.comments[0]["updated_at"]
    assert not runner.calls
    assert len(api.posts) == 1
    assert "not an open pull request" in api.posts[0][2]
    assert "run the command again" not in api.posts[0][2]


@pytest.mark.parametrize("method", ["contains", "receive"])
def test_unclaimed_database_failure_preserves_cursor_and_retries(
    rig, monkeypatch, method
):
    bot, api, runner, ledger = rig
    original = getattr(ledger, method)
    api.comments = [
        {
            **api.comments[0],
            "id": identifier,
            "updated_at": (NOW + timedelta(minutes=offset)).isoformat(),
        }
        for identifier, offset in [(100, 1), (101, 3)]
    ]

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ledger, method, fail)
    bot.poll()
    assert ledger.cursor(REPO)[0] == NOW.isoformat()
    assert not runner.calls and not api.posts
    assert not any(repo == REPO for repo, _ in api.closed_polls)
    monkeypatch.setattr(ledger, method, original)
    bot.poll()
    assert len(runner.calls) == len(api.posts) == 2


@pytest.mark.parametrize("issue", [None, {}, {"pull_request": {}}])
def test_comment_requires_pull_request_evidence(rig, issue):
    bot, api, runner, ledger = rig
    api.comments[0]["html_url"] = f"https://github.com/{REPO}/issues/42"
    api.comments[0]["issue"] = issue
    reads = []
    original = api.get_pr

    def get_pr(repo, number):
        reads.append(number)
        return original(repo, number)

    api.get_pr = get_pr
    bot.poll()
    expected = bool(issue)
    assert bool(reads) is expected
    assert ledger.contains(100) is expected
    assert bool(runner.calls) is expected
    assert bool(api.posts) is expected


@pytest.mark.parametrize("mode", ["config", "empty", "override", "defaults"])
def test_serve_resolves_shared_cli_configuration(tmp_path, catalog, monkeypatch, mode):
    from preview_hub.bot import polling

    config = tmp_path / "config.yaml"
    config.write_text(
        f"state_dir: {tmp_path / 'configured'}\ncatalog: /configured.yaml\n"
    )
    monkeypatch.setenv("PHUB_CONFIG", str(config))
    for key in ("PHUB_STATE_DIR", "PHUB_CATALOG"):
        monkeypatch.delenv(key, raising=False)
    expected_state, expected_catalog = tmp_path / "configured", Path("/configured.yaml")
    if mode == "empty":
        monkeypatch.setenv("PHUB_STATE_DIR", "")
        monkeypatch.setenv("PHUB_CATALOG", "")
    elif mode == "override":
        expected_state, expected_catalog = tmp_path / "override", Path("/override.yaml")
        monkeypatch.setenv("PHUB_STATE_DIR", str(expected_state))
        monkeypatch.setenv("PHUB_CATALOG", str(expected_catalog))
    elif mode == "defaults":
        monkeypatch.setenv("PHUB_CONFIG", "")
        expected_state, expected_catalog = (
            Path("/state"),
            Path("/etc/phub/catalog.yaml"),
        )
    paths, states = [], []

    def load(path):
        paths.append(path)

    def registry(path):
        states.append(path)
        return Registry(tmp_path / "actual")

    monkeypatch.setattr(polling, "load_yaml", load)
    monkeypatch.setattr(polling.Catalog, "parse", lambda value: catalog)
    monkeypatch.setattr(polling, "Registry", registry)
    monkeypatch.setattr(polling.UrllibGitHubApi, "token_present", lambda self: False)

    def stop(seconds):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        polling.serve(sleep=stop)
    assert paths == [expected_catalog]
    assert states == [expected_state]
