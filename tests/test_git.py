import subprocess
from pathlib import Path

import pytest

from preview_hub.contracts import InvalidInput
from preview_hub.git import GitCliSource


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "remote"
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.email", "synthetic@example.invalid")
    git(path, "config", "user.name", "Synthetic Test")
    (path / "preview.yaml").write_text(
        (Path(__file__).parent / "fixtures/backend.yaml").read_text()
    )
    git(path, "add", ".")
    git(path, "commit", "-m", "synthetic fixture")
    return path


def test_exact_checkout_and_refs(repo, tmp_path):
    sha = git(repo, "rev-parse", "HEAD")
    source = GitCliSource(tmp_path / "cache", {str(repo): "backend"})
    assert source.resolve(str(repo), "main") == sha
    assert source.resolve(str(repo), sha[:7]) == sha
    assert source.resolve(str(repo), sha) == sha
    checkout = source.checkout(str(repo), sha)
    assert checkout == tmp_path / "cache" / "backend" / sha
    assert git(checkout, "rev-parse", "HEAD") == sha
    assert source.read_manifest(str(repo), sha).service == "backend"
    git(repo, "tag", "-a", "v1", "-m", "synthetic tag")
    assert source.resolve(str(repo), "v1") == sha
    (repo / "new").write_text("branch moves")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "next synthetic commit")
    assert source.resolve(str(repo), "main") != sha
    assert git(checkout, "rev-parse", "HEAD") == sha
    assert source.resolve(str(repo), sha) == sha
    with pytest.raises(InvalidInput):
        source.resolve(str(repo), "f" * 40)
    with pytest.raises(InvalidInput):
        source.resolve(str(repo), "--upload-pack=bad")
    with pytest.raises(InvalidInput):
        source.checkout(str(repo), "../invalid")


@pytest.mark.parametrize(
    "repository",
    [
        "--upload-pack=touch /tmp/pwned;http://x",
        "https://github.com/org/repo",
        "-org/repo",
        "_org/repo",
        ".org/repo",
        "örg/repo",
        "org/répo",
        "org/repo/extra",
        "org/",
        "org/repo\n",
    ],
)
@pytest.mark.parametrize("method", ["resolve", "checkout", "read_manifest"])
def test_invalid_repository_rejected_before_git(
    tmp_path, monkeypatch, repository, method
):
    source = GitCliSource(tmp_path / "cache", {repository: "backend"})
    # A pre-existing checkout must not bypass repository validation either.
    (tmp_path / "cache" / "backend" / ("a" * 40)).mkdir(parents=True)

    def unexpected_git(*args):
        pytest.fail(f"Invalid repository reached git: {args}")

    monkeypatch.setattr(source, "_git", unexpected_git)
    with pytest.raises(InvalidInput, match="Invalid repository"):
        getattr(source, method)(repository, "a" * 40)


@pytest.mark.parametrize("repository", ["org/repo", "A0._-/repo_.-", "0/repo"])
def test_repository_arguments_are_separated_from_options(
    tmp_path, monkeypatch, repository
):
    source = GitCliSource(tmp_path / "cache")
    calls = []
    sha = "a" * 40

    def fake_git(*args):
        calls.append(args)
        if args[0] == "ls-remote":
            return f"{sha}\trefs/heads/main"
        if "rev-parse" in args:
            return sha
        return ""

    monkeypatch.setattr(source, "_git", fake_git)
    assert source.resolve(repository, "main") == sha
    url = f"https://github.com/{repository}.git"
    assert calls[0] == ("ls-remote", "--", url)
    fetch = next(args for args in calls if "fetch" in args)
    assert fetch[3:] == ("--depth=1", "--", url, sha)


@pytest.mark.parametrize("kind", ["branch", "tag", "annotated_tag"])
@pytest.mark.parametrize("ref", ["20240101", "cafe123", "a" * 40])
def test_hex_named_refs_take_precedence_over_commit_prefixes(
    tmp_path, monkeypatch, kind, ref
):
    source = GitCliSource(tmp_path / "cache")
    named_sha = "b" * 40
    other_sha = ref.ljust(40, "0")
    key = f"refs/heads/{ref}" if kind == "branch" else f"refs/tags/{ref}"
    advertised = [f"{other_sha}\trefs/heads/main"]
    if kind == "annotated_tag":
        advertised.extend([f"{'c' * 40}\t{key}", f"{named_sha}\t{key}^{{}}"])
    else:
        advertised.append(f"{named_sha}\t{key}")
    monkeypatch.setattr(source, "_git", lambda *args: "\n".join(advertised))
    checked_out = []
    monkeypatch.setattr(source, "checkout", lambda *args: checked_out.append(args))

    assert source.resolve("org/repo", ref) == named_sha
    assert checked_out == [("org/repo", named_sha)]


class FakeGitHub:
    def get_authenticated_user(self):
        return "bot"

    def list_pr_comments(self, repo, number):
        return []

    def __init__(self):
        self.pr = {
            "state": "open",
            "base": {"repo": {"full_name": "org/backend"}},
            "head": {"repo": {"full_name": "org/backend"}, "sha": "A" * 40},
        }
        self.error = None
        self.calls = []

    def get_pr(self, repo, number):
        self.calls.append((repo, number))
        if self.error:
            raise self.error
        return self.pr


@pytest.mark.parametrize(
    "ref,number",
    [
        ("pr-1", 1),
        ("pr-9999999", 9999999),
        ("pr-0", None),
        ("pr-01", None),
        ("pr-10000000", None),
        ("pr-x", None),
        ("pr-4\n", None),
        ("main", None),
    ],
)
def test_pr_ref_syntax(ref, number):
    from preview_hub.git import PrRef

    parsed = PrRef.parse(ref)
    assert (parsed.number if parsed else None) == number


def test_pr_ref_rejects_local_repository_before_github_call(tmp_path):
    api = FakeGitHub()
    source = GitCliSource(tmp_path / "cache", github=api)
    repository = str(tmp_path / "remote")

    with pytest.raises(InvalidInput) as exc:
        source.resolve(repository, "pr-4")

    assert str(exc.value) == f"{repository} PR #4: pr refs need a GitHub repository"
    assert api.calls == []


def test_pr_head_uses_existing_exact_sha_fetch(tmp_path, monkeypatch):
    api = FakeGitHub()
    source = GitCliSource(tmp_path, github=api)
    calls = []

    def fake_git(*args):
        calls.append(args)
        assert args[0] != "ls-remote"
        return "a" * 40 if "rev-parse" in args else ""

    monkeypatch.setattr(source, "_git", fake_git)
    assert source.resolve("org/backend", "pr-4") == "a" * 40
    assert api.calls == [("org/backend", 4)]
    fetch = next(args for args in calls if "fetch" in args)
    assert fetch[3:] == (
        "--depth=1",
        "--",
        "https://github.com/org/backend.git",
        "a" * 40,
    )


@pytest.mark.parametrize(
    "case,message",
    [
        ("closed", "closed or merged"),
        ("merged", "closed or merged"),
        ("fork", "fork"),
        ("base", "base repository"),
        ("deleted_head", "fork"),
        ("sha", "invalid head SHA"),
        ("404", "not found"),
        ("401", "unauthorized"),
        ("403", "unauthorized"),
        ("missing", "token missing"),
        ("no_client", "token missing"),
    ],
)
def test_pr_rejections_before_checkout(tmp_path, monkeypatch, case, message):
    from preview_hub.github import GitHubError, TokenMissing

    api = FakeGitHub()
    if case == "closed":
        api.pr["state"] = "closed"
    elif case == "merged":
        api.pr["merged"] = True
    elif case in {"fork", "base"}:
        api.pr["head" if case == "fork" else "base"]["repo"]["full_name"] = (
            "other/backend"
        )
    elif case == "deleted_head":
        api.pr["head"]["repo"] = None
    elif case == "sha":
        api.pr["head"]["sha"] = "invalid"
    elif case.isdigit():
        api.error = GitHubError("request failed", status=int(case))
    elif case == "missing":
        api.error = TokenMissing("token missing")
    source = GitCliSource(tmp_path, github=None if case == "no_client" else api)
    monkeypatch.setattr(
        source, "checkout", lambda *args: pytest.fail("unexpected checkout")
    )
    with pytest.raises(InvalidInput, match=message):
        source.resolve("org/backend", "pr-4")
