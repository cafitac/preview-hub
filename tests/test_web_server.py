import threading

import pytest
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from preview_hub.access import AccessDenied, AccessVerifier, Identity
from preview_hub.web.server import create_app, identity, serve


class SyntheticVerifier(AccessVerifier):
    def verify(self, token):
        if token == "synthetic-valid":
            return Identity("owner@example.com")
        raise AccessDenied("missing")


def test_auth_boundary_and_identity():
    app = create_app(SyntheticVerifier())
    app.router.routes.append(
        Route("/identity", lambda request: PlainTextResponse(identity(request).email))
    )
    with TestClient(app) as client:
        assert client.get("/healthz").text == "ok"
        assert client.get("/healthz").status_code == 200
        for path in ("/", "/api/environments", "/auth/verify", "/identity"):
            assert client.get(path).status_code == 401
        headers = {"Cf-Access-Jwt-Assertion": "synthetic-valid"}
        assert client.get("/auth/verify", headers=headers).status_code == 200
        assert client.get("/identity", headers=headers).text == "owner@example.com"
        assert client.get("/", headers=headers).status_code == 404
        assert client.post("/healthz").status_code == 401


def test_unconfigured_server_fails_closed(monkeypatch):
    monkeypatch.delenv("PHUB_ACCESS_TEAM_DOMAIN", raising=False)
    monkeypatch.delenv("PHUB_ACCESS_AUD", raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/healthz").status_code == 200
        assert (
            client.get(
                "/auth/verify", headers={"Cf-Access-Jwt-Assertion": "anything"}
            ).status_code
            == 401
        )


def test_gc_runs_immediately_repeats_and_stops_on_shutdown():
    calls = []
    repeated = threading.Event()

    def gc():
        calls.append(threading.current_thread())
        if len(calls) >= 2:
            repeated.set()

    with TestClient(create_app(SyntheticVerifier(), gc=gc, interval=0.01)) as client:
        assert repeated.wait(2)
        assert client.get("/healthz").status_code == 200
    assert not calls[0].is_alive()


def test_gc_retries_after_failure_and_stops_on_shutdown(caplog):
    calls = []
    repeated = threading.Event()

    def gc():
        calls.append(threading.current_thread())
        if len(calls) == 1:
            raise RuntimeError("synthetic-secret\nprivate command output")
        repeated.set()

    with TestClient(create_app(SyntheticVerifier(), gc=gc, interval=0.01)) as client:
        assert repeated.wait(2)
        assert client.get("/healthz").status_code == 200
    assert not calls[0].is_alive()
    records = [
        record for record in caplog.records if record.name == "preview_hub.web.server"
    ]
    assert len(records) == 1
    assert records[0].getMessage() == (
        "gc failed: RuntimeError; retrying next interval"
    )
    assert records[0].exc_info is None
    assert "synthetic-secret" not in caplog.text
    assert "private command output" not in caplog.text


@pytest.mark.parametrize("port", [None, "8181"])
def test_serve_port(monkeypatch, port):
    monkeypatch.delenv("PHUB_HTTP_PORT", raising=False)
    if port:
        monkeypatch.setenv("PHUB_HTTP_PORT", port)
    calls = []
    monkeypatch.setattr(
        "preview_hub.web.server.uvicorn.run", lambda app, **kwargs: calls.append(kwargs)
    )
    serve(lambda: None, 900)
    assert calls == [{"host": "0.0.0.0", "port": int(port or 8080)}]
