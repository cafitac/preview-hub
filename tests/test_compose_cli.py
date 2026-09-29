import json

import pytest

from preview_hub.cli import create_context, main


@pytest.mark.parametrize("interval,expected", [(None, 2), ("0.5", 0.5)])
def test_compose_config_wires_disk_provider(tmp_path, monkeypatch, interval, expected):
    from preview_hub.runners import compose
    from preview_hub.runners.fake import FakeRunner

    monkeypatch.delenv("PHUB_HEALTH_POLL_INTERVAL", raising=False)
    if interval is not None:
        monkeypatch.setenv("PHUB_HEALTH_POLL_INTERVAL", interval)
    calls = []

    def factory(state_dir, daemon_name):
        calls.append((state_dir, daemon_name))
        return FakeRunner()

    monkeypatch.setattr(compose, "ComposeRunner", factory)
    monkeypatch.setenv("PHUB_RUNNER", "compose")
    monkeypatch.setenv("PHUB_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("PHUB_CATALOG", "deploy/hub-stack/catalog.yaml")
    monkeypatch.setenv("PHUB_DAEMON_NAME", "expected-daemon")
    ctx = create_context()
    assert calls == [(tmp_path, "expected-daemon")]
    assert ctx.free_space() > 0
    assert ctx.poll_interval == expected


def test_inventory_cli(ctx, capsys):
    assert main(["inventory", "test-one"], ctx) == 0
    assert not any(json.loads(capsys.readouterr().out).values())


def test_serve_runs_gc_before_wait(ctx, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "preview_hub.cli.ExpireEnvironments.execute", lambda self: calls.append("gc")
    )

    def stop(gc, seconds, *, context):
        assert context is ctx
        gc()
        calls.append(seconds)
        raise KeyboardInterrupt

    monkeypatch.setattr("preview_hub.web.server.serve", stop)
    with pytest.raises(KeyboardInterrupt):
        main(["serve", "--interval", "15"], ctx)
    assert calls == ["gc", 15]


def test_cli_up_renders_real_plan(ctx, monkeypatch, capsys):
    import yaml

    from preview_hub.contracts import EnvName
    from preview_hub.runners.compose import render

    apply = ctx.runner.apply
    rendered = []

    def render_and_apply(plan):
        assert type(plan.env) is EnvName
        document = render(plan)
        rendered.append(yaml.safe_load(yaml.safe_dump(document)))
        return apply(plan)

    monkeypatch.setattr(ctx.runner, "apply", render_and_apply)
    assert main(["up", "smoke2", "--format", "json"], ctx) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "READY"
    assert rendered[0]["services"]["backend"]["labels"]["dev.phub.env"] == "smoke2"


@pytest.mark.parametrize(
    "command", [["list"], ["status", "smoke2"], ["down", "smoke2"]]
)
def test_invalid_gc_interval_does_not_affect_other_commands(ctx, monkeypatch, command):
    assert main(["up", "smoke2"], ctx) == 0
    monkeypatch.setenv("PHUB_GC_INTERVAL", "15m")
    assert main(command, ctx) == 0


def test_invalid_gc_interval_is_serve_input_error(monkeypatch, capsys):
    monkeypatch.setenv("PHUB_GC_INTERVAL", "15m")
    assert main(["serve"]) == 2
    assert "15m" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args,env,expected", [([], "15", 15), (["--interval", "20"], "15m", 20)]
)
def test_serve_gc_interval_resolution(ctx, monkeypatch, args, env, expected):
    monkeypatch.setenv("PHUB_GC_INTERVAL", env)

    def stop(gc, seconds, *, context):
        assert context is ctx
        assert seconds == expected
        raise KeyboardInterrupt

    monkeypatch.setattr("preview_hub.web.server.serve", stop)
    with pytest.raises(KeyboardInterrupt):
        main(["serve", *args], ctx)


@pytest.mark.parametrize("interval", ["2s", "0", "-1", "nan", "inf"])
def test_invalid_health_interval_is_compose_input_error(
    tmp_path, monkeypatch, capsys, interval
):
    monkeypatch.setenv("PHUB_RUNNER", "compose")
    monkeypatch.setenv("PHUB_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("PHUB_CATALOG", "deploy/hub-stack/catalog.yaml")
    monkeypatch.setenv("PHUB_HEALTH_POLL_INTERVAL", interval)
    assert main(["list"]) == 2
    assert capsys.readouterr().err


def test_invalid_health_interval_does_not_affect_fake_context(tmp_path, monkeypatch):
    monkeypatch.setenv("PHUB_RUNNER", "fake")
    monkeypatch.setenv("PHUB_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("PHUB_CATALOG", "deploy/hub-stack/catalog.yaml")
    monkeypatch.setenv("PHUB_HEALTH_POLL_INTERVAL", "2s")
    assert create_context().poll_interval == 0.1


@pytest.mark.parametrize("interval", ["nan", "inf", "-inf", "-1", "0"])
@pytest.mark.parametrize("source", ["argument", "environment"])
def test_serve_rejects_nonpositive_or_nonfinite_interval_before_loop(
    ctx, monkeypatch, capsys, interval, source
):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid interval must be rejected before GC or sleep")

    monkeypatch.setattr("preview_hub.cli.ExpireEnvironments.execute", unexpected)
    monkeypatch.setattr("preview_hub.web.server.serve", unexpected)
    monkeypatch.setenv(
        "PHUB_GC_INTERVAL", interval if source == "environment" else "900"
    )
    args = [f"--interval={interval}"] if source == "argument" else []
    assert main(["serve", *args], ctx) == 2
    assert "finite and positive" in capsys.readouterr().err
