import sqlite3

import pytest

from preview_hub.bot.links import LinkReconciler, marker
from preview_hub.github import GitHubError
from preview_hub.registry import Registry


class Api:
    def __init__(self, registry):
        self.registry = registry
        self.comments = []
        self.edits = []
        self.users = 0
        self.failure = None
        self.edit_attempts = 0
        self.next_id = 1

    def check_transaction(self):
        # Every API call can independently acquire the SQLite writer lock.
        with self.registry.transaction():
            pass

    def get_authenticated_user(self):
        self.check_transaction()
        self.users += 1
        return "bot"

    def list_pr_comments(self, repo, number):
        self.check_transaction()
        return [c for c in self.comments if (c["repo"], c["number"]) == (repo, number)]

    def post_comment(self, repo, number, body):
        self.check_transaction()
        if self.failure == "post":
            raise RuntimeError("secret")
        cid = max(self.next_id, max((c["id"] for c in self.comments), default=0) + 1)
        self.next_id = cid + 1
        self.comments.append(
            {
                "id": cid,
                "repo": repo,
                "number": number,
                "body": body,
                "user": {"login": "bot"},
            }
        )
        if self.failure == "crash":
            self.failure = None
            raise RuntimeError("secret")
        return cid

    def edit_comment(self, repo, comment_id, body):
        self.check_transaction()
        self.edit_attempts += 1
        if isinstance(self.failure, GitHubError):
            raise self.failure
        if self.failure == "edit":
            raise RuntimeError("secret")
        if not any(c["id"] == comment_id for c in self.comments):
            raise GitHubError("gone", status=404)
        self.edits.append((repo, comment_id, body))
        next(c for c in self.comments if c["id"] == comment_id)["body"] = body


def create(registry, name="demo"):
    with registry.transaction() as db:
        eid = db.execute(
            "INSERT INTO environments (name,state,spec_json,ttl_expires_at,created_at,updated_at) VALUES (?,'READY','{}','future','now','now')",
            (name,),
        ).lastrowid
        for service, ref in [("backend", "pr-4"), ("frontend", "pr-7")]:
            db.execute(
                "INSERT INTO environment_services VALUES (?,?,?,?,?,?,?,?)",
                (
                    eid,
                    service,
                    f"owner/{service}",
                    ref,
                    "a" * 40,
                    "image",
                    f"https://{service}.example",
                    "HEALTHY",
                ),
            )


def rows(registry):
    db = registry.connect()
    try:
        return [dict(r) for r in db.execute("SELECT * FROM pr_links ORDER BY repo")]
    finally:
        db.close()


@pytest.fixture
def rig(tmp_path):
    registry = Registry(tmp_path)
    create(registry)
    api = Api(registry)
    return registry, api, LinkReconciler(registry, api)


def test_create_restart_version_and_body(rig):
    registry, api, links = rig
    links.reconcile()
    assert len(api.comments) == 2
    assert api.users == 1
    body = api.comments[0]["body"]
    assert body.startswith("preview demo: READY\n" + marker("demo"))
    assert "https://frontend.example" in body
    assert "| backend | pr-4 | aaaaaaaaaaaa |" in body
    links.reconcile()
    LinkReconciler(registry, api).reconcile()
    assert len(api.comments) == 2 and not api.edits
    with registry.transaction() as db:
        db.execute("UPDATE environments SET version=2,state='FAILED'")
    links.reconcile()
    assert len(api.edits) == 2
    assert all(r["rendered_version"] == 2 for r in rows(registry))


def test_origin_and_strict_refs(tmp_path):
    registry = Registry(tmp_path)
    create(registry, "pr-backend-4")
    api = Api(registry)
    LinkReconciler(registry, api).reconcile()
    assert [(c["repo"], c["number"]) for c in api.comments] == [("owner/frontend", 7)]
    with registry.transaction() as db:
        db.execute("UPDATE environment_services SET requested_ref='pr-01'")
    LinkReconciler(registry, api).reconcile()
    assert rows(registry)[0]["status"] == "REMOVED"


@pytest.mark.parametrize("action", ["ref", "delete", "missing"])
def test_removal(rig, action):
    registry, api, links = rig
    links.reconcile()
    with registry.transaction() as db:
        if action == "ref":
            db.execute("UPDATE environment_services SET requested_ref='main'")
        elif action == "delete":
            db.execute("UPDATE environments SET state='DELETED'")
        else:
            db.execute("DELETE FROM environment_services")
            db.execute("DELETE FROM environments")
    links.reconcile()
    assert all(r["status"] == "REMOVED" for r in rows(registry))
    assert all(
        c["body"] == "preview demo: removed\n" + marker("demo") for c in api.comments
    )
    links.reconcile()
    assert len(api.edits) == 2


def test_crash_adopts_own_marker_and_refreshes(rig):
    registry, api, links = rig
    api.comments.append(
        {
            "id": 1,
            "repo": "owner/backend",
            "number": 4,
            "body": marker("demo"),
            "user": {"login": "other"},
        }
    )
    api.failure = "crash"
    links.reconcile()
    assert rows(registry)[0]["attempts"] == 1
    with registry.transaction() as db:
        db.execute("UPDATE environments SET version=2")
    LinkReconciler(registry, api).reconcile()
    assert len(api.comments) == 3
    assert all(
        r["attempts"] == 0 and r["rendered_version"] == 2 for r in rows(registry)
    )


def test_failure_retry_and_no_secret(rig, caplog):
    registry, api, links = rig
    api.failure = "post"
    links.reconcile()
    assert all(r["attempts"] == 1 for r in rows(registry))
    assert "secret" not in caplog.text
    assert "repo=owner/backend pr=4 env=demo reason=post_comment" in caplog.text
    api.failure = None
    links.reconcile()
    assert len(api.comments) == 2
    with registry.transaction() as db:
        db.execute("UPDATE environments SET state='DELETED'")
    api.failure = "edit"
    links.reconcile()
    assert all(r["status"] == "ACTIVE" and r["attempts"] == 1 for r in rows(registry))
    api.failure = None
    links.reconcile()
    create(registry)
    links.reconcile()
    assert len(api.comments) == 4
    assert all(r["status"] == "ACTIVE" and r["attempts"] == 0 for r in rows(registry))


def test_revision_two_upgrade(tmp_path):
    from pathlib import Path

    db = sqlite3.connect(tmp_path / "state.db")
    for name in ["0001_initial.sql", "0002_bot.sql"]:
        db.executescript(
            (Path(__file__).parents[1] / "preview_hub/migrations" / name).read_text()
        )
    db.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("INSERT INTO schema_meta VALUES ('version','2')")
    db.commit()
    db.close()
    registry = Registry(tmp_path)
    registry.migrate()
    with registry.connect() as db:
        assert (
            db.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()[
                0
            ]
            == "3"
        )
        assert [
            r["name"]
            for r in db.execute("PRAGMA index_list(pr_links)")
            if r["name"] == "ix_links_status"
        ] == ["ix_links_status"]


def test_entry_url_selection(rig):
    registry, api, _links = rig
    LinkReconciler(registry, api, entry_service="backend").reconcile()
    assert "\nhttps://backend.example\n" in api.comments[0]["body"]
    with registry.transaction() as db:
        db.execute(
            "UPDATE environment_services SET public_url=NULL WHERE service='frontend'"
        )
        db.execute("UPDATE environments SET version=2")
    LinkReconciler(registry, api).reconcile()
    assert "\nhttps://backend.example\n" in api.comments[0]["body"]


def test_process_exit_after_post_recovers_on_restart(rig, monkeypatch):
    registry, api, links = rig
    post = api.post_comment

    def interrupted(repo, number, body):
        post(repo, number, body)
        raise SystemExit

    monkeypatch.setattr(api, "post_comment", interrupted)
    with pytest.raises(SystemExit):
        links.reconcile()
    assert rows(registry)[0]["comment_id"] is None
    monkeypatch.setattr(api, "post_comment", post)
    LinkReconciler(registry, api).reconcile()
    assert len(api.comments) == 2
    assert all(row["comment_id"] is not None for row in rows(registry))


@pytest.mark.parametrize("missing_comment_id", [False, True])
def test_recreated_name_retires_old_instance(rig, missing_comment_id):
    registry, api, links = rig
    with registry.transaction() as db:
        db.execute("UPDATE environments SET version=5")
    links.reconcile()
    old_id = rows(registry)[0]["environment_id"]
    assert all(row["rendered_version"] == 5 for row in rows(registry))
    with registry.transaction() as db:
        db.execute("UPDATE environments SET state='DELETED'")
        if missing_comment_id:
            db.execute("UPDATE pr_links SET comment_id=NULL")
    create(registry)
    with registry.transaction() as db:
        new_id = db.execute(
            "SELECT id FROM environments WHERE state='READY'"
        ).fetchone()["id"]
        db.execute(
            "UPDATE environment_services SET commit_sha=?, public_url=? WHERE environment_id=?",
            ("b" * 40, "https://new.example", new_id),
        )
    LinkReconciler(registry, api).reconcile()
    assert new_id != old_id
    assert len(api.comments) == 4
    assert len(api.edits) == 2
    assert all(
        comment["body"] == "preview demo: removed\n" + marker("demo")
        for comment in api.comments[:2]
    )
    assert all(
        "https://new.example" in comment["body"]
        and "| backend | pr-4 | bbbbbbbbbbbb |" in comment["body"]
        for comment in api.comments[2:]
    )
    assert all(
        row["environment_id"] == new_id
        and row["rendered_version"] == 1
        and row["status"] == "ACTIVE"
        and row["attempts"] == 0
        and row["comment_id"] in {3, 4}
        for row in rows(registry)
    )
    links.reconcile()
    assert len(api.comments) == 4 and len(api.edits) == 2


def test_process_exit_after_post_then_removal_recovers_marker(rig, monkeypatch):
    registry, api, links = rig
    post = api.post_comment

    def interrupted(repo, number, body):
        post(repo, number, body)
        raise SystemExit

    monkeypatch.setattr(api, "post_comment", interrupted)
    with pytest.raises(SystemExit):
        links.reconcile()
    assert len(api.comments) == 1
    assert rows(registry)[0]["comment_id"] is None
    assert rows(registry)[0]["attempts"] == 0
    with registry.transaction() as db:
        db.execute("UPDATE environments SET state='DELETED'")
    monkeypatch.setattr(api, "post_comment", post)
    restarted = LinkReconciler(registry, api)
    restarted.reconcile()
    assert api.edits == [
        ("owner/backend", 1, "preview demo: removed\n" + marker("demo"))
    ]
    assert rows(registry)[0]["status"] == "REMOVED"
    assert rows(registry)[0]["comment_id"] == 1
    restarted.reconcile()
    assert len(api.comments) == 1 and len(api.edits) == 1


def test_deleted_comment_on_update_posts_fresh(rig):
    registry, api, links = rig
    links.reconcile()
    old_ids = {c["id"] for c in api.comments}
    api.comments.clear()
    with registry.transaction() as db:
        db.execute("UPDATE environments SET version=2")
    links.reconcile()
    assert len(api.comments) == 2
    assert old_ids.isdisjoint({c["id"] for c in api.comments})
    assert all(
        r["rendered_version"] == 2 and r["attempts"] == 0 for r in rows(registry)
    )
    links.reconcile()
    assert api.edit_attempts == 2


def test_deleted_comment_on_removal_is_terminal(rig):
    registry, api, links = rig
    links.reconcile()
    api.comments.clear()
    with registry.transaction() as db:
        db.execute("UPDATE environments SET state='DELETED', version=2")
    links.reconcile()
    assert all(r["status"] == "REMOVED" and r["attempts"] == 0 for r in rows(registry))
    LinkReconciler(registry, api).reconcile()
    assert api.edit_attempts == 2
    assert not api.comments


@pytest.mark.parametrize(
    "failure",
    [
        None,
        GitHubError("locked", status=403),
        GitHubError("temporary", status=503, retryable=True),
    ],
)
def test_recreated_instance_posts_despite_retirement_failure(rig, failure):
    registry, api, links = rig
    links.reconcile()
    old_ids = {c["id"] for c in api.comments}
    if failure is None:
        api.comments.clear()
    api.failure = failure
    with registry.transaction() as db:
        db.execute("UPDATE environments SET state='DELETED'")
    create(registry)
    links.reconcile()
    assert all(
        r["comment_id"] not in old_ids
        and r["status"] == "ACTIVE"
        and r["attempts"] == 0
        for r in rows(registry)
    )
    assert len(api.comments) == (2 if failure is None else 4)
    LinkReconciler(registry, api).reconcile()
    assert api.edit_attempts == 2


@pytest.mark.parametrize("status", [403, 422])
@pytest.mark.parametrize("removing", [False, True])
def test_nonretryable_cap_survives_restart_and_version_change(
    rig, caplog, status, removing
):
    registry, api, links = rig
    links.reconcile()
    with registry.transaction() as db:
        db.execute("UPDATE environments SET version=2")
        if removing:
            db.execute("UPDATE environments SET state='DELETED'")
    api.failure = GitHubError("secret", status=status)
    for _ in range(8):
        LinkReconciler(registry, api).reconcile()
    assert api.edit_attempts == 10
    assert all(r["attempts"] == 5 for r in rows(registry))
    assert caplog.text.count("retry cap reached") == 2
    assert "secret" not in caplog.text
    with registry.transaction() as db:
        db.execute("UPDATE environments SET version=3")
    api.failure = None
    links.reconcile()
    assert api.edit_attempts == 12
    assert all(r["attempts"] == 0 for r in rows(registry))
    assert all(
        r["status"] == ("REMOVED" if removing else "ACTIVE") for r in rows(registry)
    )


@pytest.mark.parametrize("status", [404, 503])
def test_retryable_failures_continue_past_cap(rig, status):
    registry, api, links = rig
    links.reconcile()
    with registry.transaction() as db:
        db.execute("UPDATE environments SET version=2")
    api.failure = GitHubError("temporary", status=status, retryable=True)
    for _ in range(7):
        LinkReconciler(registry, api).reconcile()
    assert api.edit_attempts == 14
    assert all(r["attempts"] == 7 for r in rows(registry))
    assert len(api.comments) == 2


def test_failed_fresh_post_does_not_adopt_unretired_comment(rig):
    registry, api, links = rig
    links.reconcile()
    old_ids = {c["id"] for c in api.comments}
    with registry.transaction() as db:
        db.execute("UPDATE environments SET state='DELETED'")
    create(registry)
    # Both retirement and posting fail; the old marker must remain excluded on restart.
    original_edit = api.edit_comment

    def fail_edit(*args):
        raise GitHubError("locked", status=403)

    api.edit_comment = fail_edit
    api.failure = "post"
    links.reconcile()
    assert all(r["comment_id"] is None and r["attempts"] == 1 for r in rows(registry))
    api.edit_comment = original_edit
    api.failure = None
    LinkReconciler(registry, api).reconcile()
    assert len(api.comments) == 4
    assert all(r["comment_id"] not in old_ids for r in rows(registry))


def test_deleted_comment_clears_id_even_when_repost_fails(rig):
    registry, api, links = rig
    links.reconcile()
    api.comments.clear()
    with registry.transaction() as db:
        db.execute("UPDATE environments SET version=2")
    api.failure = "post"
    links.reconcile()
    assert all(
        r["comment_id"] is None and r["rendered_version"] == 0 and r["attempts"] == 1
        for r in rows(registry)
    )
    api.failure = None
    LinkReconciler(registry, api).reconcile()
    assert len(api.comments) == 2
    assert api.edit_attempts == 2
    assert all(r["rendered_version"] == 2 for r in rows(registry))
