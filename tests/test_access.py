import json
from datetime import UTC, datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from preview_hub.access import AccessDenied, AccessVerifier, Identity
from preview_hub.web.dashboard import Dashboard
from preview_hub.web.server import create_app

NOW = int(datetime(2026, 11, 15, 12, 0, tzinfo=UTC).timestamp())


class _Datetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime.fromtimestamp(NOW, tz)


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch):
    # PyJWT (api_jwt.py) validates exp/nbf/iat with its module-level datetime.now(); a
    # PyJWT that reads time another way makes every NOW-based token fail loudly here.
    monkeypatch.setattr("jwt.api_jwt.datetime", _Datetime)


@pytest.fixture
def keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update(kid="first", alg="RS256", use="sig")
    return private, jwk


def token(keys, claims=None, kid="first", algorithm="RS256"):
    now = NOW
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
    assert verifier(keys).verify(token(keys, {"exp": NOW - 30})).email
    assert verifier(keys).verify(token(keys, {"nbf": NOW + 30})).email


@pytest.mark.parametrize(
    "claims,reason",
    [
        ({"aud": "wrong"}, "bad_audience"),
        ({"iss": "https://wrong.example.com"}, "bad_issuer"),
        ({"exp": 1}, "expired"),
        ({"nbf": NOW + 3600}, "malformed"),
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


def service_token(keys, claims=None, common_name="client-a"):
    payload = {
        "iat": NOW,
        "exp": NOW + 300,
        "aud": "application",
        "iss": "https://team.cloudflareaccess.com",
    }
    if common_name is not None:
        payload["common_name"] = common_name
    payload.update(claims or {})
    return jwt.encode(payload, keys[0], algorithm="RS256", headers={"kid": "first"})


def test_service_identity_allowlist(keys, monkeypatch):
    monkeypatch.setenv("PHUB_ACCESS_SERVICE_TOKENS", " client-a, ,client-b ")
    service = verifier(keys).verify(service_token(keys, common_name="client-b"))
    assert (service.kind, service.email, service.service_id) == (
        "service",
        None,
        "client-b",
    )
    # An explicit parameter overrides the environment.
    with pytest.raises(AccessDenied, match="service_not_allowed"):
        verifier(keys, service_tokens="other").verify(service_token(keys))


def test_email_wins_over_common_name(keys):
    human = verifier(keys, service_tokens="client-a").verify(
        token(keys, {"common_name": "client-a"})
    )
    assert (human.kind, human.email, human.service_id) == (
        "human",
        "owner@example.com",
        None,
    )


@pytest.mark.parametrize(
    "allowlist,claims,common_name,reason",
    [
        (None, {}, "client-a", "service_not_allowed"),
        ("", {}, "client-a", "service_not_allowed"),
        ("other", {}, "client-a", "service_not_allowed"),
        ("client-a", {}, None, "malformed"),
        ("client-a", {"common_name": ["client-a"]}, "client-a", "service_not_allowed"),
        ("client-a", {"aud": "wrong"}, "client-a", "bad_audience"),
        ("client-a", {"exp": NOW - 3600}, "client-a", "expired"),
        ("client-a", {"email": None}, "client-a", "malformed"),
    ],
    ids=[
        "allowlist-unset",
        "allowlist-empty",
        "not-allowlisted",
        "neither-email-nor-common-name",
        "common-name-not-a-string",
        "wrong-audience",
        "expired",
        "email-null",
    ],
)
def test_service_token_rejections(
    keys, monkeypatch, caplog, allowlist, claims, common_name, reason
):
    monkeypatch.delenv("PHUB_ACCESS_SERVICE_TOKENS", raising=False)
    encoded = service_token(keys, claims, common_name)
    with caplog.at_level("INFO"), pytest.raises(AccessDenied, match=reason):
        verifier(keys, service_tokens=allowlist).verify(encoded)
    assert encoded not in caplog.text
    assert "client-a" not in caplog.text


@pytest.mark.parametrize(
    "method,path,status",
    [
        ("GET", "/auth/verify", 200),
        ("GET", "/healthz", 200),
        ("POST", "/auth/verify", 403),
        ("HEAD", "/auth/verify", 403),
        ("GET", "/auth/verify/", 403),
        ("GET", "/", 403),
        ("GET", "/api/environments", 403),
        ("POST", "/api/environments", 403),
    ],
)
def test_service_route_boundary(keys, ctx, caplog, method, path, status):
    app = _app(keys, ctx)
    encoded = service_token(keys)
    with TestClient(app) as client, caplog.at_level("INFO"):
        response = client.request(
            method, path, headers={"Cf-Access-Jwt-Assertion": encoded}
        )
    assert response.status_code == status
    if status == 403:
        assert response.text == ("" if method == "HEAD" else "service_forbidden_route")
        assert "service_forbidden_route" in caplog.text
    assert encoded not in caplog.text


def test_unlisted_service_token_is_unauthorized(keys, ctx):
    headers = {"Cf-Access-Jwt-Assertion": service_token(keys, common_name="other")}
    with TestClient(_app(keys, ctx)) as client:
        assert client.get("/auth/verify", headers=headers).status_code == 401


def _app(keys, ctx):
    class EmptyGitHub:
        def list_branches(self, repo):
            return []

        def list_open_prs(self, repo):
            return []

    return create_app(
        verifier(keys, service_tokens="client-a"),
        dashboard=Dashboard(ctx, EmptyGitHub()),
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"email": " "},
        {"email": "owner@example.com", "service_id": "client-a"},
        {"kind": "service"},
        {"kind": "service", "service_id": "client-a", "email": "owner@example.com"},
    ],
)
def test_identity_rejects_inconsistent_kinds(kwargs):
    with pytest.raises(ValueError, match="invalid"):
        Identity(**kwargs)
