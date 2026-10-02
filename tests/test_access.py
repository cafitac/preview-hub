import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from preview_hub.access import AccessDenied, AccessVerifier


@pytest.fixture
def keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update(kid="first", alg="RS256", use="sig")
    return private, jwk


def token(keys, claims=None, kid="first", algorithm="RS256"):
    now = int(time.time())
    payload = {
        "email": "owner@example.com",
        "iat": now,
        "exp": now + 300,
        "aud": "application",
        "iss": "https://team.cloudflareaccess.com",
    }
    payload.update(claims or {})
    key = (
        keys[0]
        if algorithm == "RS256"
        else "synthetic-hmac-key-that-is-long-enough"
        if algorithm == "HS256"
        else ""
    )
    return jwt.encode(payload, key, algorithm=algorithm, headers={"kid": kid})


def verifier(keys, **kwargs):
    return AccessVerifier(
        "team.cloudflareaccess.com",
        "application",
        fetcher=lambda _: {"keys": [keys[1]]},
        **kwargs,
    )


def test_valid_and_leeway(keys):
    assert verifier(keys).verify(token(keys)).email == "owner@example.com"
    assert verifier(keys).verify(token(keys, {"exp": int(time.time()) - 30})).email
    assert verifier(keys).verify(token(keys, {"nbf": int(time.time()) + 30})).email


@pytest.mark.parametrize(
    "claims,reason",
    [
        ({"aud": "wrong"}, "bad_audience"),
        ({"iss": "https://wrong.example.com"}, "bad_issuer"),
        ({"exp": 1}, "expired"),
        ({"nbf": int(time.time()) + 3600}, "malformed"),
        ({"email": ""}, "malformed"),
    ],
)
def test_rejected_claims(keys, claims, reason, caplog):
    encoded = token(keys, claims)
    with caplog.at_level("INFO"), pytest.raises(AccessDenied, match=reason):
        verifier(keys).verify(encoded)
    assert encoded not in caplog.text
    assert reason in caplog.text


@pytest.mark.parametrize("algorithm", ["none", "HS256"])
def test_only_rs256(keys, algorithm):
    with pytest.raises(AccessDenied, match="malformed"):
        verifier(keys).verify(token(keys, algorithm=algorithm))


@pytest.mark.parametrize("claim", ["exp", "iat", "aud", "iss"])
def test_required_claims(keys, claim):
    payload = jwt.decode(token(keys), options={"verify_signature": False})
    del payload[claim]
    encoded = jwt.encode(payload, keys[0], algorithm="RS256", headers={"kid": "first"})
    with pytest.raises(AccessDenied, match="malformed"):
        verifier(keys).verify(encoded)


def test_bad_signature(keys):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(AccessDenied, match="bad_signature"):
        verifier(keys).verify(token((other, keys[1])))


def test_unknown_kid_refresh_once_and_cache_expiry(keys):
    clock = [0.0]
    calls = []
    current = [keys[1]]

    def fetch(url):
        calls.append(url)
        return {"keys": current}

    check = AccessVerifier(
        "team.cloudflareaccess.com",
        "application",
        fetcher=fetch,
        clock=lambda: clock[0],
    )
    check.verify(token(keys))
    check.verify(token(keys))
    assert len(calls) == 1
    clock[0] = 61
    current.append({**keys[1], "kid": "rotated"})
    check.verify(token(keys, kid="rotated"))
    assert len(calls) == 2
    for _ in range(3):
        with pytest.raises(AccessDenied, match="unknown_kid"):
            check.verify(token(keys, kid="absent"))
    assert len(calls) == 2
    clock[0] = 3662
    check.verify(token(keys))
    assert len(calls) == 3
    assert calls[0] == "https://team.cloudflareaccess.com/cdn-cgi/access/certs"


def test_missing_configuration_and_token(keys):
    with pytest.raises(AccessDenied, match="config_missing"):
        AccessVerifier("", "").verify(token(keys))
    with pytest.raises(AccessDenied, match="missing"):
        verifier(keys).verify(None)
    with pytest.raises(AccessDenied, match="malformed"):
        verifier(keys).verify("not-a-jwt")


def test_jwks_unavailable_is_fail_closed_and_throttled(keys):
    calls = []

    def failed(url):
        calls.append(url)
        raise OSError("synthetic outage")

    check = AccessVerifier("team.cloudflareaccess.com", "application", fetcher=failed)
    for _ in range(3):
        with pytest.raises(AccessDenied, match="jwks_unavailable"):
            check.verify(token(keys))
    assert len(calls) == 1


@pytest.mark.parametrize(
    "data", [None, [], {}, {"keys": []}, {"keys": [None]}, {"keys": [{"kty": "RSA"}]}]
)
def test_malformed_jwks_fails_closed(keys, data):
    check = AccessVerifier(
        "team.cloudflareaccess.com", "application", fetcher=lambda _: data
    )
    with pytest.raises(AccessDenied, match="jwks_unavailable"):
        check.verify(token(keys))


def test_jwks_fetch_has_timeout_and_refuses_redirects(monkeypatch):
    from io import BytesIO
    from urllib.request import Request

    from preview_hub.access import fetch_jwks

    handlers = []
    calls = []

    class Opener:
        def open(self, url, timeout):
            calls.append((url, timeout))
            return BytesIO(b'{"keys": []}')

    def build(handler):
        handlers.append(handler)
        return Opener()

    monkeypatch.setattr("preview_hub.access.build_opener", build)
    url = "https://team.cloudflareaccess.com/cdn-cgi/access/certs"
    assert fetch_jwks(url) == {"keys": []}
    assert calls == [(url, 5)]
    assert (
        handlers[0].redirect_request(
            Request(url), None, 302, "redirect", {}, "https://other.example.com"
        )
        is None
    )


def service_token(keys, claims=None):
    payload = jwt.decode(token(keys, claims), options={"verify_signature": False})
    del payload["email"]
    return jwt.encode(payload, keys[0], algorithm="RS256", headers={"kid": "first"})


def test_service_identity_allowlist(keys, monkeypatch):
    from preview_hub.access import SERVICE_IDENTITY_CLAIM

    monkeypatch.setenv("PHUB_ACCESS_SERVICE_TOKENS", " first-client, ,second-client ")
    check = verifier(keys)
    human = check.verify(token(keys, {SERVICE_IDENTITY_CLAIM: "unknown"}))
    assert human.kind == "human"
    assert human.service_id is None
    service = check.verify(
        service_token(keys, {SERVICE_IDENTITY_CLAIM: "first-client"})
    )
    assert service.kind == "service"
    assert service.email is None
    assert service.service_id == "first-client"


@pytest.mark.parametrize("allowlist", [None, "", "other-client", "first-client"])
@pytest.mark.parametrize("claim", [None, "unknown", "first-client", [], ""])
def test_service_identity_rejections(keys, monkeypatch, allowlist, claim):
    from preview_hub.access import SERVICE_IDENTITY_CLAIM

    if allowlist is None:
        monkeypatch.delenv("PHUB_ACCESS_SERVICE_TOKENS", raising=False)
    else:
        monkeypatch.setenv("PHUB_ACCESS_SERVICE_TOKENS", allowlist)
    claims = {} if claim is None else {SERVICE_IDENTITY_CLAIM: claim}
    encoded = service_token(keys, claims)
    if allowlist == claim == "first-client":
        assert verifier(keys).verify(encoded).kind == "service"
    else:
        with pytest.raises(AccessDenied, match="service_not_allowed"):
            verifier(keys).verify(encoded)


def test_service_route_boundary(keys, monkeypatch, ctx, caplog):
    from starlette.testclient import TestClient

    from preview_hub.access import SERVICE_IDENTITY_CLAIM
    from preview_hub.web.dashboard import Dashboard
    from preview_hub.web.server import create_app

    class EmptyGitHub:
        def list_branches(self, repo):
            return []

        def list_open_prs(self, repo):
            return []

    monkeypatch.setenv("PHUB_ACCESS_SERVICE_TOKENS", "first-client")
    app = create_app(verifier(keys), dashboard=Dashboard(ctx, EmptyGitHub()))
    # A successful synthetic mutation proves middleware permits humans and
    # blocks services before any mutation handler runs.
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    mutations = []

    def mutate(request):
        mutations.append(request.state.identity.kind)
        return PlainTextResponse("mutated")

    app.router.routes.append(Route("/mutation", mutate, methods=["POST"]))
    human = {"Cf-Access-Jwt-Assertion": token(keys)}
    service = {
        "Cf-Access-Jwt-Assertion": service_token(
            keys, {SERVICE_IDENTITY_CLAIM: "first-client"}
        )
    }
    with TestClient(app) as client, caplog.at_level("INFO"):
        assert client.get("/healthz").status_code == 200
        assert client.get("/healthz", headers=service).status_code == 200
        for path in ("/auth/verify", "/", "/api/environments", "/api/catalog"):
            assert client.get(path, headers=human).status_code == 200
        assert client.post("/mutation", headers=human).status_code == 200
        assert client.get("/auth/verify", headers=service).status_code == 200
        for method, path in (
            ("GET", "/"),
            ("GET", "/api/environments"),
            ("GET", "/api/catalog"),
            ("POST", "/api/environments"),
            ("POST", "/mutation"),
            ("POST", "/auth/verify"),
            ("GET", "/auth/verify/"),
        ):
            response = client.request(method, path, headers=service)
            assert response.status_code == 403
            assert response.text == "service_forbidden_route"
        rejected = {
            "Cf-Access-Jwt-Assertion": service_token(
                keys, {SERVICE_IDENTITY_CLAIM: "other-client"}
            )
        }
        assert client.get("/auth/verify", headers=rejected).status_code == 401
    assert mutations == ["human"]
    assert "service_forbidden_route" in caplog.text
    assert service["Cf-Access-Jwt-Assertion"] not in caplog.text


def test_stack_service_allowlist_wiring():
    from pathlib import Path

    import yaml

    stack = yaml.safe_load(Path("deploy/hub-stack/compose.yaml").read_text())
    hub = stack["services"]["hub"]
    assert "PHUB_ACCESS_SERVICE_TOKENS" not in hub["environment"]
    assert {"path": "/opt/phub/public.env", "required": False} in hub["env_file"]
