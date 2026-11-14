from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from starlette.testclient import TestClient

from preview_hub.metrics import STATES, Metrics, start_server
from preview_hub.web.server import create_app


def test_render(ctx):
    metrics = Metrics(ctx.registry.path, clock=lambda: 1000)
    assert "phub_operation_running_oldest_seconds 0" in metrics.render()
    with ctx.registry.transaction() as db:
        for state in (*STATES, "READY", "DELETED"):
            db.execute(
                "INSERT INTO environments(name,state,spec_json,ttl_expires_at,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (f"env-{db.total_changes}", state, "{}", "", "", ""),
            )
        for status, started in [("RUNNING", 100), ("RUNNING", 200), ("DONE", 0)]:
            db.execute(
                "INSERT INTO operations(environment_id,kind,status,requested_by,pid,heartbeat_at,started_at) VALUES (1,?,?,?,1,?,?)",
                (
                    "create",
                    status,
                    "test",
                    "",
                    f"1970-01-01T00:{started // 60:02}:{started % 60:02}+00:00",
                ),
            )
    rendered = metrics.render()
    assert "DELETED" not in rendered
    for state in STATES:
        assert (
            f'phub_environments{{state="{state}"}} {2 if state == "READY" else 1}'
            in rendered
        )
    assert "phub_operation_running_oldest_seconds 900.0" in rendered
    assert "phub_gc_last_success_timestamp_seconds 0.0" in rendered
    with ctx.registry.transaction() as db:
        db.execute("UPDATE environments SET state='DELETED'")
    assert all(
        f'phub_environments{{state="{state}"}} 0' in metrics.render()
        for state in STATES
    )


def test_gc_lifespan(ctx):
    metrics = Metrics(ctx.registry.path, clock=lambda: 1234)
    from threading import Event

    success = Event()
    calls = []

    def gc():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("private")
        success.set()

    with TestClient(create_app(gc=gc, interval=0.01, metrics=metrics)):
        assert success.wait(2)
    assert "phub_gc_failures_total 1" in metrics.render()
    assert "phub_gc_last_success_timestamp_seconds 1234" in metrics.render()


def test_http(ctx):
    server = start_server(Metrics(ctx.registry.path), 0)
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(url + "/metrics") as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "text/plain; version=0.0.4"
            assert b"phub_up 1\n" in response.read()
        for request in (url + "/other", Request(url + "/metrics", method="POST")):
            with pytest.raises(HTTPError) as error:
                urlopen(request)
            assert error.value.code == 404
        ctx.registry.path.unlink()
        with pytest.raises(HTTPError) as error:
            urlopen(url + "/metrics")
        assert error.value.code == 500
        assert error.value.read() == b""
    finally:
        server.shutdown()
        server.server_close()


def test_disabled(ctx, monkeypatch):
    def unexpected(*args):
        pytest.fail("disabled listener started")

    monkeypatch.setattr("preview_hub.web.server.start_server", unexpected)
    with TestClient(create_app(metrics=Metrics(ctx.registry.path), metrics_port=0)):
        pass
