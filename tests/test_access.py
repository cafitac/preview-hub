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
