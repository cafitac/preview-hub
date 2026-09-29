import io
import json
import traceback
from email.message import Message
from urllib.error import HTTPError, URLError

import pytest

from preview_hub.bot.github import GitHubError, TokenMissing, UrllibGitHubApi

TOKEN = "test-secret-do-not-print"


@pytest.fixture
def token_path(tmp_path):
    path = tmp_path / "github_token"
    path.write_text(TOKEN)
    return path


@pytest.mark.parametrize("error", ["http", "transport", "invalid_json"])
def test_token_not_in_repr_logs_or_exception(token_path, caplog, error):
    seen = []

    def transport(request, *, timeout):
        seen.append(request)
        assert timeout == 20
        assert request.get_header("Authorization") == "Bearer " + TOKEN
        assert TOKEN not in request.full_url
        assert TOKEN not in repr(request.data)
        if error == "http":
            raise HTTPError(
                request.full_url, 401, TOKEN, Message(), io.BytesIO(TOKEN.encode())
            )
        if error == "transport":
            raise URLError(TOKEN)
        return io.BytesIO(TOKEN.encode())

    api = UrllibGitHubApi(token_path, transport=transport)
    with pytest.raises(GitHubError) as caught:
        api.get_pr("owner/backend", 1)
    assert len(seen) == 1
    assert TOKEN not in repr(api)
    assert TOKEN not in str(caught.value)
    assert TOKEN not in repr(caught.value)
    assert TOKEN not in "".join(traceback.format_exception(caught.value))
    assert TOKEN not in caplog.text


@pytest.mark.parametrize(
    "status,headers",
    [(500, {}), (429, {"Retry-After": "3"}), (403, {"Retry-After": "3"})],
)
def test_bounded_retries_and_retry_after(token_path, status, headers):
    calls, sleeps = [], []

    def transport(request, *, timeout):
        calls.append(request)
        message = Message()
        for key, value in headers.items():
            message[key] = value
        raise HTTPError(request.full_url, status, TOKEN, message, io.BytesIO())

    api = UrllibGitHubApi(token_path, transport=transport, sleep=sleeps.append)
    with pytest.raises(GitHubError):
        api.get_pr("owner/backend", 1)
    assert len(calls) == 3
    assert sleeps == ([3, 3] if headers else [1, 2])


def test_post_has_no_hidden_transport_retries(token_path):
    calls = []

    def transport(request, *, timeout):
        calls.append(request)
        raise HTTPError(request.full_url, 500, TOKEN, Message(), io.BytesIO())

    api = UrllibGitHubApi(token_path, transport=transport)
    with pytest.raises(GitHubError):
        api.post_comment("owner/backend", 1, "reply")
    assert len(calls) == 1


def test_api_pagination_and_payloads(token_path):
    paths = []

    def transport(request, *, timeout):
        paths.append(request.full_url)
        if request.method == "POST":
            assert json.loads(request.data) == {"body": "reply"}
            data = {"id": 999}
        elif "/pulls/42" in request.full_url:
            data = {"number": 42}
        elif "/pulls?" in request.full_url:
            data = [
                {"number": 42, "updated_at": "2026-09-29T00:00:00Z"},
                {"number": 41, "updated_at": "2020-01-01T00:00:00Z"},
            ]
        else:
            data = [{"id": 1}] * (100 if request.full_url.endswith("&page=1") else 1)
        return io.BytesIO(json.dumps(data).encode())

    api = UrllibGitHubApi(token_path, transport=transport)
    assert len(api.list_issue_comments("owner/backend", "2026-09-29T00:00:00Z")) == 101
    assert "page=2" in paths[1]
    assert api.get_pr("owner/backend", 42) == {"number": 42}
    assert api.list_closed_prs("owner/backend", "2026-09-01T00:00:00Z") == [
        {"number": 42, "updated_at": "2026-09-29T00:00:00Z"}
    ]
    assert api.post_comment("owner/backend", 42, "reply") == 999


def test_missing_token(tmp_path):
    api = UrllibGitHubApi(tmp_path / "absent")
    assert not api.token_present()
    with pytest.raises(TokenMissing, match="token missing"):
        api.get_pr("owner/backend", 42)


def test_long_retry_after_defers_without_hammering(token_path, monkeypatch):
    from preview_hub.bot import github

    monkeypatch.setattr(github.time, "time", lambda: 1000)
    calls, sleeps = [], []

    def transport(request, *, timeout):
        calls.append(request)
        headers = Message()
        headers["Retry-After"] = "120"
        raise HTTPError(request.full_url, 429, TOKEN, headers, io.BytesIO())

    api = UrllibGitHubApi(token_path, transport=transport, sleep=sleeps.append)
    with pytest.raises(GitHubError) as first:
        api.post_comment("owner/backend", 1, "reply")
    assert first.value.retry_at == 1120
    assert first.value.attempted
    with pytest.raises(GitHubError) as second:
        api.get_pr("owner/backend", 1)
    assert not second.value.attempted
    assert len(calls) == 1 and not sleeps


def test_redirects_cannot_forward_authorization():
    from urllib.request import Request

    from preview_hub.bot.github import NoRedirect

    with pytest.raises(GitHubError, match="redirects"):
        NoRedirect().redirect_request(
            Request(
                "https://api.github.com/", headers={"Authorization": "Bearer " + TOKEN}
            ),
            None,
            302,
            "redirect",
            {},
            "https://untrusted.example",
        )


@pytest.mark.parametrize("later_status", [200, 403, 404])
def test_expired_cooldown_is_cleared(token_path, monkeypatch, later_status):
    from preview_hub.bot import github

    now = [1000.0]
    monkeypatch.setattr(github.time, "time", lambda: now[0])
    statuses = iter([503, 503, 503, later_status])

    def transport(request, *, timeout):
        status = next(statuses)
        if status != 200:
            raise HTTPError(
                request.full_url, status, "failure", Message(), io.BytesIO()
            )
        return io.BytesIO(b'{"number": 42}')

    api = UrllibGitHubApi(token_path, transport=transport, sleep=lambda _: None)
    with pytest.raises(GitHubError) as first:
        api.get_pr("owner/backend", 42)
    assert first.value.retryable
    assert api.retry_at == first.value.retry_at == 1004
    now[0] = api.retry_at
    if later_status == 200:
        assert api.get_pr("owner/backend", 42) == {"number": 42}
    else:
        with pytest.raises(GitHubError) as later:
            api.get_pr("owner/backend", 42)
        assert not later.value.retryable
        assert later.value.retry_at == 0
    assert api.retry_at == 0
