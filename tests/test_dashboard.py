import json
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from starlette.testclient import TestClient
from test_web_server import SyntheticVerifier

from preview_hub.cli import main
from preview_hub.contracts import CatalogEntry, PublicAccess
from preview_hub.github import GitHubError
from preview_hub.web.dashboard import Dashboard, SpawnResult, spawn
from preview_hub.web.server import create_app

AUTH = {"Cf-Access-Jwt-Assertion": "synthetic-valid"}
HEADERS = {
    **AUTH,
    "Origin": "https://hub.example.com",
    "Content-Type": "application/json",
}
TITLE = '<script>alert("unsafe")</script>'


class GitHub:
    def __init__(self):
        self.calls = []
        self.fail = set()

    def list_branches(self, repo):
        self.calls.append((repo, "branches"))
        if repo in self.fail:
            raise GitHubError("synthetic secret")
        return [
            {"name": "main", "commit": {"sha": "a" * 40}},
            {"name": "feature", "commit": {"sha": "b" * 40}},
        ]

    def list_open_prs(self, repo):
        self.calls.append((repo, "prs"))
        return [
            {
                "number": n,
                "title": TITLE,
                "state": state,
                "head": {
                    "ref": "feature",
                    "sha": "b" * 40,
                    "repo": {"full_name": head} if head else None,
                },
                "base": {"repo": {"full_name": repo}},
            }
            for n, head, state in [
                (1, repo, "open"),
                (2, "fork/repo", "open"),
                (3, repo, "closed"),
                (4, None, "open"),
            ]
        ]


@pytest.fixture
def web(ctx):
    ctx.catalog = replace(
        ctx.catalog,
        public_access=PublicAccess(
            "phub-{env}.example.com", "backend", "/_svc/{subdomain}", "hub.example.com"
        ),
    )
    github = GitHub()
    calls = []
    result = [SpawnResult(None)]

    def spawner(argv, state):
        calls.append((argv, state))
        return result[0]

    dashboard = Dashboard(ctx, github, spawner)
    with TestClient(create_app(SyntheticVerifier(), dashboard=dashboard)) as client:
        yield client, dashboard, calls, result


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/"),
        ("GET", "/api/catalog"),
        ("GET", "/api/environments"),
        ("GET", "/api/environments/feat-a"),
        ("GET", "/api/environments/feat-a?format=descriptor"),
        ("POST", "/api/environments"),
        ("POST", "/api/environments/feat-a/update"),
        ("DELETE", "/api/environments/feat-a"),
    ],
)
def test_auth_on_every_route(web, method, path):
    client, _, calls, _ = web
    assert (
        client.request(method, path, headers={"Origin": HEADERS["Origin"]}).status_code
        == 401
    )
    assert not calls


def test_catalog_filter_failure_and_cache(web):
    client, dashboard, _, _ = web
    ctx = dashboard.context
    ctx.catalog = replace(
        ctx.catalog,
        services={
            **ctx.catalog.services,
            "alias": CatalogEntry("org/backend", "other"),
            "broken": CatalogEntry("org/broken", "main"),
        },
    )
    dashboard.github.fail.add("org/broken")
    clock = [0.0]
    dashboard.clock = lambda: clock[0]
    data = client.get("/api/catalog", headers=AUTH).json()
    assert data[0]["prs"] == [
        {"number": 1, "title": TITLE, "head_ref": "feature", "head_sha": "b" * 40}
    ]
    assert data[0]["branches"][0] == {"name": "main", "sha": "a" * 40}
    assert data[1]["default_ref"] == "other"
    assert "error" in data[2] and "synthetic secret" not in json.dumps(data)
    assert len(dashboard.github.calls) == 3
    clock[0] = 59
    assert client.get("/api/catalog", headers=AUTH).json() == data
    assert len(dashboard.github.calls) == 3
    clock[0] = 60
    client.get("/api/catalog", headers=AUTH)
    assert len(dashboard.github.calls) == 6


def test_catalog_cache_is_thread_safe(web):
    _, dashboard, _, _ = web
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: dashboard.catalog_data(), range(16)))
    assert all(result == results[0] for result in results)
    assert len(dashboard.github.calls) == 2


def test_catalog_refresh_does_not_block_environments_or_delete(web):
    client, dashboard, calls, _ = web
    entered = threading.Event()
    release = threading.Event()

    class BlockingGitHub(GitHub):
        def list_branches(self, repo):
            entered.set()
            assert release.wait(5), "Catalog refresh was not released"
            return super().list_branches(repo)

    dashboard.github = BlockingGitHub()
    with ThreadPoolExecutor(max_workers=3) as pool:
        catalog = pool.submit(client.get, "/api/catalog", headers=AUTH)
        try:
            assert entered.wait(2)
            environments = pool.submit(client.get, "/api/environments", headers=AUTH)
            delete = pool.submit(
                client.delete, "/api/environments/feat-a", headers=HEADERS
            )
            assert environments.result(timeout=2).status_code == 200
            assert delete.result(timeout=2).status_code == 202
            assert len(calls) == 1
            assert not catalog.done()
        finally:
            release.set()
        assert catalog.result(timeout=2).status_code == 200


@pytest.mark.parametrize("public", [True, False])
def test_registry_list_detail_descriptor_read_only(web, capsys, public):
    client, dashboard, _, _ = web
    ctx = dashboard.context
    ctx.git.manifests["org/backend"] = replace(
        ctx.git.manifests["org/backend"], expose={"subdomain": "api"}
    )
    if not public:
        ctx.catalog = replace(ctx.catalog, public_access=None)
    assert main(["up", "feat-a", "--set", "backend=main", "--ttl", "2h"], ctx) == 0
    assert main(["up", "feat-deleted"], ctx) == 0
    assert main(["down", "feat-deleted"], ctx) == 0
    assert main(["status", "feat-a", "--format", "descriptor"], ctx) == 0
    output = capsys.readouterr().out
    descriptor = json.loads(output[output.index("{") :])
    before = ctx.registry.path.read_bytes()
    data = client.get("/api/environments", headers=AUTH).json()
    assert len(data) == 1
    assert data[0]["name"] == "feat-a"
    assert data[0]["services"] == [
        {
            "name": "backend",
            "ref": "main",
            "commit": "a" * 12,
            "url": "https://phub-feat-a.example.com"
            if public
            else "http://api.feat-a.localhost:18080",
        }
    ]
    assert data[0]["created_at"] and data[0]["updated_at"] and data[0]["ttl"]
    assert client.get("/api/environments/feat-a", headers=AUTH).json() == data[0]
    assert (
        client.get("/api/environments/feat-a?format=descriptor", headers=AUTH).json()
        == descriptor
    )
    assert client.get("/api/environments/missing", headers=AUTH).status_code == 404
    assert client.get("/api/environments/INVALID", headers=AUTH).status_code == 400
    assert ctx.registry.path.read_bytes() == before


def test_last_error_summary(web):
    client, dashboard, _, _ = web
    main(["up", "feat-a"], dashboard.context)
    with dashboard.context.registry.transaction() as db:
        db.execute(
            "UPDATE environments SET last_error_json=?",
            (json.dumps({"message": "Build failed", "log_excerpt": "private logs"}),),
        )
    response = client.get("/api/environments", headers=AUTH)
    assert response.json()[0]["last_error"] == "Build failed"
    assert "private logs" not in response.text


@pytest.mark.parametrize(
    "action,method,path,body,tail",
    [
        (
            "up",
            "POST",
            "/api/environments",
            {"name": "feat-a", "services": {"backend": "pr-1"}, "ttl": "2h"},
            ["--set", "backend=pr-1", "--ttl", "2h"],
        ),
        (
            "update",
            "POST",
            "/api/environments/feat-a/update",
            {"services": {"backend": "feature"}},
            ["--set", "backend=feature"],
        ),
        ("down", "DELETE", "/api/environments/feat-a", None, []),
    ],
)
def test_mutations_spawn(web, caplog, action, method, path, body, tail):
    client, dashboard, calls, _ = web
    caplog.set_level("INFO", logger="uvicorn.error.dashboard")
    response = client.request(method, path, headers=HEADERS, json=body)
    assert response.status_code == 202
    assert response.json() == {"name": "feat-a"}
    assert calls == [
        (
            [
                sys.executable,
                "-m",
                "preview_hub",
                action,
                "feat-a",
                "--requested-by",
                "web:owner@example.com",
                *tail,
            ],
            dashboard.context.registry.state_dir,
        )
    ]
    records = [r for r in caplog.records if r.name == "uvicorn.error.dashboard"]
    assert len(records) == 1
    assert '"email": "owner@example.com"' in records[0].message
    assert '"exit_code": null' in records[0].message
    assert "synthetic-valid" not in caplog.text


@pytest.mark.parametrize(
    "code,status", [(2, 400), (3, 409), (4, 429), (5, 500), (0, 202), (None, 202)]
)
def test_early_exit_mapping(web, caplog, code, status):
    caplog.set_level("INFO", logger="uvicorn.error.dashboard")
    client, _, _, result = web
    result[0] = SpawnResult(code, "last error line")
    response = client.post("/api/environments", headers=HEADERS, json={"services": {}})
    assert response.status_code == status
    audit = json.loads(caplog.records[-1].message.removeprefix("mutation "))
    assert audit["exit_code"] == code
    assert "rejected" not in audit
    if status != 202:
        assert response.json() == {"exit_code": code, "error": "last error line"}


def test_generated_name(web):
    client, _, calls, _ = web
    names = [
        client.post("/api/environments", headers=HEADERS, json={"services": {}}).json()[
            "name"
        ]
        for _ in range(10)
    ]
    assert all(re.fullmatch("c-[a-z2-7]{6}", name) for name in names)
    assert [call[0][4] for call in calls] == names


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "http://hub.example.com",
        "https://evil.example",
        "null",
        "https://hub.example.com.evil",
        "https://hub.example.com/",
        "https://hub.example.com:443",
        "HTTPS://hub.example.com",
    ],
)
@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/environments"),
        ("POST", "/api/environments/feat-a/update"),
        ("DELETE", "/api/environments/feat-a"),
    ],
)
def test_origin_rejected(web, caplog, origin, method, path):
    caplog.set_level("INFO", logger="uvicorn.error.dashboard")
    client, _, calls, _ = web
    headers = {**AUTH, "Content-Type": "application/json"}
    if origin is not None:
        headers["Origin"] = origin
    assert (
        client.request(method, path, headers=headers, json={"services": {}}).status_code
        == 403
    )
    assert not calls
    audit = json.loads(caplog.records[-1].message.removeprefix("mutation "))
    assert audit["exit_code"] is None
    assert audit["rejected"] == "Origin not allowed"


@pytest.mark.parametrize(
    "origin,status",
    [
        ("https://preview-hub.cafitac.com", 202),
        ("https://PREVIEW-HUB.cafitac.com", 202),
        ("https://different.cafitac.com", 403),
    ],
)
def test_origin_host_case_insensitive(web, origin, status):
    client, dashboard, calls, _ = web
    ctx = dashboard.context
    ctx.catalog = replace(
        ctx.catalog,
        public_access=PublicAccess(
            "phub-{env}.cafitac.com",
            "backend",
            "/_svc/{subdomain}",
            "Preview-Hub.cafitac.com",
        ),
    )
    response = client.post(
        "/api/environments",
        headers={**HEADERS, "Origin": origin},
        json={"services": {}},
    )
    assert response.status_code == status
    assert len(calls) == (1 if status == 202 else 0)


@pytest.mark.parametrize(
    "content_type", [None, "text/plain", "application/x-www-form-urlencoded"]
)
def test_content_type(web, caplog, content_type):
    caplog.set_level("INFO", logger="uvicorn.error.dashboard")
    client, _, calls, _ = web
    headers = {**AUTH, "Origin": HEADERS["Origin"]}
    if content_type:
        headers["Content-Type"] = content_type
    assert (
        client.post(
            "/api/environments", headers=headers, content='{"services":{}}'
        ).status_code
        == 403
    )
    assert not calls
    audit = json.loads(caplog.records[-1].message.removeprefix("mutation "))
    assert audit["exit_code"] is None
    assert audit["rejected"] == "Content-Type must be application/json"


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/environments"),
        ("POST", "/api/environments/feat-a/update"),
        ("DELETE", "/api/environments/feat-a"),
    ],
)
def test_no_public_access(web, method, path):
    client, dashboard, calls, _ = web
    dashboard.context.catalog = replace(dashboard.context.catalog, public_access=None)
    assert (
        client.request(method, path, headers=HEADERS, json={"services": {}}).status_code
        == 403
    )
    assert not calls


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {},
        {"services": []},
        {"services": {"unknown": "main"}},
        {"services": {"backend": ""}},
        {"services": {"backend": " "}},
        {"services": {"backend": "-option"}},
        {"services": {"backend": "a\x00b"}},
        {"services": {"backend": 3}},
        {"services": {}, "name": "INVALID"},
        {"services": {}, "name": None},
        {"services": {}, "name": ""},
        {"services": {}, "ttl": "never"},
        {"services": {}, "ttl": "8d"},
        {"services": {}, "ttl": None},
        {"services": {}, "extra": True},
    ],
)
def test_validation(web, caplog, body):
    caplog.set_level("INFO", logger="uvicorn.error.dashboard")
    client, _, calls, _ = web
    assert (
        client.post(
            "/api/environments", headers=HEADERS, content=json.dumps(body)
        ).status_code
        == 400
    )
    assert not calls
    audit = json.loads(caplog.records[-1].message.removeprefix("mutation "))
    assert audit["exit_code"] is None
    assert audit["rejected"]


def test_malformed_json_and_update_fields(web):
    client, _, calls, _ = web
    assert (
        client.post("/api/environments", headers=HEADERS, content="{").status_code
        == 400
    )
    assert (
        client.post(
            "/api/environments/feat-a/update",
            headers=HEADERS,
            json={"services": {}, "ttl": "1h"},
        ).status_code
        == 400
    )
    assert (
        client.delete("/api/environments/INVALID", headers=HEADERS).status_code == 400
    )
    assert not calls


def test_html_render_and_escape(web):
    client, _, _, _ = web
    response = client.get("/", headers=AUTH)
    assert response.status_code == 200
    assert "owner@example.com" in response.text
    assert 'value="pr-1"' in response.text
    assert "main (default)" in response.text
    assert TITLE not in response.text
    assert "&lt;script&gt;" in response.text
    assert "textContent" in response.text and "innerHTML" not in response.text
    assert "아직 환경이 없습니다" in response.text


def test_cli_requested_by_reaches_registry(ctx):
    assert main(["up", "feat-a", "--requested-by", "web:owner@example.com"], ctx) == 0
    db = ctx.registry.connect()
    try:
        assert (
            db.execute("SELECT requested_by FROM operations").fetchone()[0]
            == "web:owner@example.com"
        )
    finally:
        db.close()


def test_spawn_logs_and_last_stderr_line(tmp_path):
    result = spawn(
        [
            sys.executable,
            "-c",
            "import sys; print('stdout only'); print('first', file=sys.stderr); print('last', file=sys.stderr); sys.exit(3)",
        ],
        tmp_path,
    )
    assert result == SpawnResult(3, "last")
    assert next(tmp_path.glob("logs/web/*/stdout.log")).read_text() == "stdout only\n"
    assert next(tmp_path.glob("logs/web/*/stderr.log")).read_text() == "first\nlast\n"


def test_spawn_detached_timeout_reaps(monkeypatch, tmp_path):
    finished = threading.Event()
    calls = []

    class Child:
        def wait(self, timeout=None):
            calls.append(timeout)
            if timeout:
                raise subprocess.TimeoutExpired("phub", timeout)
            finished.set()
            return 0

    def popen(argv, **kwargs):
        assert kwargs["start_new_session"] is True
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["stdout"].name.endswith("stdout.log")
        assert kwargs["stderr"].name.endswith("stderr.log")
        return Child()

    monkeypatch.setattr("preview_hub.web.dashboard.subprocess.Popen", popen)
    assert spawn(["phub"], tmp_path) == SpawnResult(None)
    assert finished.wait(2)
    assert calls == [2, None]


def test_spawn_wait_does_not_block_health(web):
    client, dashboard, _, _ = web
    entered = threading.Event()
    release = threading.Event()

    def wait_in_thread(argv, state):
        entered.set()
        assert release.wait(3), "Health request was blocked by the child wait"
        return SpawnResult(None)

    dashboard.spawner = wait_in_thread
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            client.post, "/api/environments", headers=HEADERS, json={"services": {}}
        )
        assert entered.wait(2)
        try:
            assert client.get("/healthz").status_code == 200
        finally:
            release.set()
        assert future.result().status_code == 202


def test_spawn_os_failure_is_safe(web, caplog):
    caplog.set_level("INFO", logger="uvicorn.error.dashboard")
    client, dashboard, _, _ = web

    def fail(argv, state):
        raise OSError("private filesystem details")

    dashboard.spawner = fail
    response = client.post("/api/environments", headers=HEADERS, json={"services": {}})
    assert response.status_code == 500
    assert response.json() == {"error": "Unable to start command", "exit_code": 5}

    audit = json.loads(caplog.records[-1].message.removeprefix("mutation "))
    assert audit["exit_code"] is None
    assert audit["rejected"] == "Unable to start command"


def test_requested_by_update_and_delete(ctx):
    assert main(["up", "feat-a"], ctx) == 0
    for action in ("update", "down"):
        assert (
            main(
                [
                    action,
                    "feat-a",
                    "--requested-by",
                    "web:owner@example.com",
                    *(["--set", "backend=main"] if action == "update" else []),
                ],
                ctx,
            )
            == 0
        )
    db = ctx.registry.connect()
    try:
        actors = [
            row[0]
            for row in db.execute("SELECT requested_by FROM operations ORDER BY id")
        ]
        assert actors[0].startswith("cli:")
        assert actors[1:] == ["web:owner@example.com", "web:owner@example.com"]
    finally:
        db.close()
