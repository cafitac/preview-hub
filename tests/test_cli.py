import pytest

from preview_hub.cli import create_context, main
from preview_hub.contracts import InvalidInput


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    monkeypatch.setenv("PHUB_CONFIG", str(path))
    monkeypatch.setenv("PHUB_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("PHUB_SOURCE_DIR", str(tmp_path / "source"))
    monkeypatch.setenv("PHUB_RUNNER", "fake")
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(
        "apiVersion: preview-hub/v1\n"
        "public_url_template: 'http://{subdomain}.{env}.localhost:18080'\n"
        "services: {}\n"
        "limits:\n"
        "  max_environments: 2\n"
        "  build_concurrency: 1\n"
        "  default_ttl: 1h\n"
        "  max_ttl: 2h\n"
    )
    monkeypatch.setenv("PHUB_CATALOG", str(catalog))
    return path


@pytest.mark.parametrize("contents", ["", "null\n", "# comment only\n", "{}\n"])
def test_empty_config_uses_defaults(config_file, contents, capsys):
    config_file.write_text(contents)

    assert main(["list", "--format", "json"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "[]"
    assert captured.err == ""


@pytest.mark.parametrize("contents", ["[]\n", "- item\n", "text\n", "42\n", "false\n"])
def test_non_mapping_config_is_invalid_input(config_file, contents, capsys):
    config_file.write_text(contents)

    with pytest.raises(InvalidInput, match="PHUB_CONFIG must contain a mapping"):
        create_context()
    assert main(["list"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "PHUB_CONFIG must contain a mapping"


@pytest.mark.parametrize(
    "env,key,default",
    [
        ("PHUB_STATE_DIR", "state_dir", "/state"),
        ("PHUB_CATALOG", "catalog", "/etc/phub/catalog.yaml"),
        ("PHUB_SOURCE_DIR", "source_dir", "/src"),
        ("PHUB_RUNNER", "runner", "fake"),
    ],
)
@pytest.mark.parametrize("override", [None, "", "override"])
@pytest.mark.parametrize("configured", [{}, {"value": None}, {"value": "configured"}])
def test_config_override_fallbacks(
    monkeypatch, env, key, default, override, configured
):
    from preview_hub.cli import config_override

    monkeypatch.delenv(env, raising=False)
    if override is not None:
        monkeypatch.setenv(env, override)
    config = {key: configured["value"]} if "value" in configured else {}
    expected = override or configured.get("value") or default
    assert config_override(config, env, key, default) == expected


@pytest.mark.parametrize(
    "args", [["list"], ["gc"], ["down", "feat-x"], ["logs", "feat-x", "backend"]]
)
def test_descriptor_rejected_before_context_creation(monkeypatch, args):
    def unexpected_context():
        pytest.fail("Invalid format must not create context or execute commands")

    monkeypatch.setattr("preview_hub.cli.create_context", unexpected_context)
    with pytest.raises(SystemExit) as exc:
        main([*args, "--format", "descriptor"])
    assert exc.value.code == 2


@pytest.mark.parametrize(
    "ttl", ["3651d", "87601h", "5256001m", "315360001s", "9" * 5000 + "d"]
)
def test_oversized_ttl_is_invalid_before_creation(ctx, ttl):
    assert main(["up", "feat-x", "--ttl", ttl], ctx) == 2
    assert ctx.registry.list() == []
    assert ctx.git.resolutions == 0


def test_deadline_overflow_is_invalid_input(ctx, monkeypatch):
    from datetime import UTC, datetime

    class FutureDateTime:
        @staticmethod
        def now(tz):
            return datetime.max.replace(tzinfo=UTC)

    monkeypatch.setattr("preview_hub.lifecycle.datetime", FutureDateTime)
    assert main(["up", "feat-x"], ctx) == 2
    assert ctx.registry.list() == []


def test_pr_up_and_update_reresolve(ctx, tmp_path, monkeypatch):
    from conftest import manifest
    from test_git import FakeGitHub

    from preview_hub.git import GitCliSource

    api = FakeGitHub()
    source = GitCliSource(tmp_path / "sources", github=api)
    monkeypatch.setattr(source, "checkout", lambda *args: tmp_path)
    monkeypatch.setattr(source, "read_manifest", lambda *args: manifest())
    ctx.git = source
    assert main(["up", "pr-demo", "--set", "backend=pr-4"], ctx) == 0
    service = ctx.registry.get("pr-demo")["services"][0]
    assert service["requested_ref"] == "pr-4"
    assert service["commit_sha"] == "a" * 40
    api.pr["head"]["sha"] = "b" * 40
    assert main(["update", "pr-demo", "--set", "backend=pr-4"], ctx) == 0
    service = ctx.registry.get("pr-demo")["services"][0]
    assert service["requested_ref"] == "pr-4"
    assert service["commit_sha"] == "b" * 40
    assert api.calls == [("org/backend", 4), ("org/backend", 4)]


def test_pr_missing_token_exits_two_without_creation(ctx, tmp_path, capsys):
    from preview_hub.git import GitCliSource

    ctx.git = GitCliSource(tmp_path)
    assert main(["up", "pr-demo", "--set", "backend=pr-4"], ctx) == 2
    assert "GitHub token missing" in capsys.readouterr().err
    assert ctx.registry.list() == []


@pytest.mark.parametrize("present", [False, True])
def test_context_github_token_override(config_file, tmp_path, monkeypatch, present):
    config_file.write_text("{}")
    token = tmp_path / "synthetic_token"
    monkeypatch.setenv("PHUB_GITHUB_TOKEN_FILE", str(token))
    if present:
        token.write_text("synthetic")
    ctx = create_context()
    assert (ctx.git.github is not None) == present
    if present:
        assert ctx.git.github.token_path == token


def test_rejected_pr_update_preserves_ready_environment(ctx, tmp_path, monkeypatch):
    from conftest import manifest
    from test_git import FakeGitHub

    from preview_hub.git import GitCliSource

    assert main(["up", "pr-demo"], ctx) == 0
    before = ctx.registry.get("pr-demo")
    api = FakeGitHub()
    api.pr["state"] = "closed"
    source = GitCliSource(tmp_path / "sources", github=api)
    monkeypatch.setattr(source, "checkout", lambda *args: tmp_path)
    monkeypatch.setattr(source, "read_manifest", lambda *args: manifest())
    ctx.git = source
    assert main(["update", "pr-demo", "--set", "backend=pr-4"], ctx) == 2
    assert ctx.registry.get("pr-demo") == before


def test_descriptor_proxy_follows_runtime():
    from preview_hub.cli import descriptor

    env = {
        "name": "demo",
        "state": "READY",
        "created_at": "2026-10-05T00:00:00Z",
        "ttl_expires_at": "2026-10-06T00:00:00Z",
        "updated_at": "2026-10-05T00:00:00Z",
        "services": [],
    }
    template = "http://{subdomain}.{env}.localhost:18080"
    # Compose: the published phub-proxy port from the template
    assert descriptor(env, template)["proxy"] == {
        "hostPort": 18080,
        "inNetworkAddress": "phub-proxy:80",
    }
    # Kubernetes: the cluster router, given by PHUB_PROXY_ADDRESS / PHUB_PROXY_PORT
    traefik = "traefik.kube-system.svc.cluster.local:80"
    assert descriptor(env, template, proxy_address=traefik, proxy_port=80)["proxy"] == {
        "hostPort": 80,
        "inNetworkAddress": traefik,
    }
