"""Fail-closed Cloudflare Access verification; credentials never enter logs."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPException
from typing import Any, Literal, cast
from urllib.request import HTTPRedirectHandler, Request, build_opener

import jwt

from .contracts import is_hostname

SERVICE_IDENTITY_CLAIM = "common_name"


@dataclass(frozen=True)
class Identity:
    email: str | None = None
    kind: Literal["human", "service"] = "human"
    service_id: str | None = None


class AccessDenied(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def fetch_jwks(url: str) -> object:
    with build_opener(_NoRedirect()).open(url, timeout=5) as response:
        return json.load(response)


class AccessVerifier:
    def __init__(
        self,
        team_domain: str | None = None,
        audience: str | None = None,
        *,
        fetcher: Callable[[str], object] = fetch_jwks,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.team_domain = (
            os.environ.get("PHUB_ACCESS_TEAM_DOMAIN", "")
            if team_domain is None
            else team_domain
        )
        self.audience = (
            os.environ.get("PHUB_ACCESS_AUD", "") if audience is None else audience
        )
        self.service_tokens = frozenset(
            value.strip()
            for value in os.environ.get("PHUB_ACCESS_SERVICE_TOKENS", "").split(",")
            if value.strip()
        )
        self.fetcher, self.clock = fetcher, clock
        self._keys: dict[str, jwt.PyJWK] = {}
        self._expires = 0.0
        self._last_fetch = float("-inf")
        self._lock = threading.Lock()

    def _refresh(self, now: float) -> None:
        self._last_fetch = now
        try:
            raw = self.fetcher(f"https://{self.team_domain}/cdn-cgi/access/certs")
            if not isinstance(raw, dict):
                raise TypeError("invalid JWKS")
            items = cast(dict[str, object], raw).get("keys")
            if not isinstance(items, list):
                raise TypeError("invalid JWKS")
            keys: dict[str, jwt.PyJWK] = {}
            for value in cast(list[object], items):
                if not isinstance(value, dict):
                    raise TypeError("invalid JWK")
                item = cast(dict[str, Any], value)
                if item.get("kty") != "RSA" or item.get("use", "sig") != "sig":
                    continue
                key = jwt.PyJWK.from_dict(item, algorithm="RS256")
                if key.key_id:
                    keys[key.key_id] = key
            if not keys:
                raise ValueError("empty JWKS")
            self._keys = keys
            self._expires = now + 3600
        except (OSError, HTTPException, ValueError, TypeError, jwt.PyJWTError):
            raise AccessDenied("jwks_unavailable") from None

    def verify(self, token: str | None) -> Identity:
        try:
            return self._verify(token)
        except AccessDenied as exc:
            logging.getLogger(__name__).info("%s", exc.reason)
            raise

    def _verify(self, token: str | None) -> Identity:
        if not self.audience or not is_hostname(self.team_domain):
            raise AccessDenied("config_missing")
        if not token:
            raise AccessDenied("missing")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                raise AccessDenied("malformed")
            kid = header["kid"]
            with self._lock:
                now = self.clock()
                if now >= self._expires:
                    if now - self._last_fetch < 60:
                        raise AccessDenied("jwks_unavailable")
                    self._refresh(now)
                elif kid not in self._keys and now - self._last_fetch >= 60:
                    self._refresh(now)
                key = self._keys.get(kid)
                if key is None:
                    raise AccessDenied("unknown_kid")
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=f"https://{self.team_domain}",
                leeway=60,
                options={"require": ["exp", "iat", "aud", "iss"]},
            )
            email = claims.get("email")
            if "email" in claims:
                if not isinstance(email, str) or not email.strip():
                    raise AccessDenied("malformed")
                return Identity(email=email)
            service_id = claims.get(SERVICE_IDENTITY_CLAIM)
            if not isinstance(service_id, str) or service_id not in self.service_tokens:
                raise AccessDenied("service_not_allowed")
            return Identity(kind="service", service_id=service_id)
        except jwt.InvalidAudienceError:
            raise AccessDenied("bad_audience") from None
        except jwt.InvalidIssuerError:
            raise AccessDenied("bad_issuer") from None
        except jwt.ExpiredSignatureError:
            raise AccessDenied("expired") from None
        except jwt.InvalidSignatureError:
            raise AccessDenied("bad_signature") from None
        except (jwt.PyJWTError, ValueError, TypeError) as exc:
            if isinstance(exc, AccessDenied):
                raise
            raise AccessDenied("malformed") from None
