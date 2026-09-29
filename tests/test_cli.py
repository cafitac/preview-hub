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
