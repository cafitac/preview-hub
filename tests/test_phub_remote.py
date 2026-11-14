import importlib.machinery
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

loader = importlib.machinery.SourceFileLoader(
    "phub_remote", str(Path(__file__).parents[1] / "scripts/phub-remote")
)
spec = importlib.util.spec_from_loader(loader.name, loader)
remote = importlib.util.module_from_spec(spec)
loader.exec_module(remote)


def runner(responses, calls):
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        status, body = next(responses)
        return subprocess.CompletedProcess(
            argv, 0, json.dumps(body) + f"\n{status}", ""
        )

    return run


def test_up(monkeypatch, capsys):
    monkeypatch.setenv("PHUB_URL", "https://hub.example.com")
    monkeypatch.setenv("PHUB_CLOUDFLARED", "custom-cloudflared")
    calls = []
    assert (
        remote.main(
            [
                "up",
                "feat-a",
                "--set",
                "backend=feature=x",
                "--set",
                "frontend=main",
                "--ttl",
                "2h",
            ],
            run=runner(iter([(202, {"name": "feat-a"})]), calls),
        )
        == 0
    )
    argv, kwargs = calls[0]
    assert argv[:4] == [
        "custom-cloudflared",
        "access",
        "curl",
        "https://hub.example.com/api/environments",
    ]
    assert argv[4:] == [
        "-sS",
        "--fail-with-body",
        "-w",
        "\n%{http_code}",
        "-X",
        "POST",
        "-H",
        "Origin: https://hub.example.com",
        "-H",
        "Content-Type: application/json",
        "--data-binary",
        "@-",
    ]
    assert json.loads(kwargs.pop("input")) == {
        "name": "feat-a",
        "services": {"backend": "feature=x", "frontend": "main"},
        "ttl": "2h",
    }
    assert kwargs == {"capture_output": True, "text": True, "timeout": 60}
    assert json.loads(capsys.readouterr().out) == {"name": "feat-a"}


@pytest.mark.parametrize(
    "status,code", [(400, 2), (409, 3), (429, 4), (500, 5), (502, 5)]
)
def test_http_error(status, code, capsys):
    assert (
        remote.main(["list"], run=runner(iter([(status, {"error": "busy"})]), []))
        == code
    )
    captured = capsys.readouterr()
    assert "busy" in captured.err
    assert json.loads(captured.out) == {"error": "busy"}


def test_inventory_expect_empty():
    calls = []
    assert (
        remote.main(
            ["inventory", "feat-a", "--expect-empty"],
            run=runner(iter([(200, {"empty": False})]), calls),
        )
        == 1
    )
    assert calls[0][0][3].endswith("/feat-a/inventory")


@pytest.mark.parametrize("terminal,code", [("READY", 0), ("FAILED", 5), ("DELETED", 5)])
def test_wait_ready(terminal, code, capsys):
    calls, sleeps = [], []
    pending = [(200, {"state": "STARTING"})] if terminal == "READY" else []
    responses = iter(
        [*pending, (200, {"state": terminal, "readiness": {"allHealthy": True}})]
    )
    assert (
        remote.main(
            ["wait-ready", "feat-a"],
            run=runner(responses, calls),
            sleep=sleeps.append,
            clock=lambda: 0,
        )
        == code
    )
    assert sleeps == ([5] if terminal == "READY" else [])
    assert calls[0][0][3].endswith("?format=descriptor")
    assert len(capsys.readouterr().err.splitlines()) == len(pending) + 1


def test_wait_timeout():
    ticks = iter([0, 1])
    assert (
        remote.main(
            ["wait-ready", "feat-a", "--timeout", "1"],
            run=runner(
                iter([(200, {"state": "READY", "readiness": {"allHealthy": False}})]),
                [],
            ),
            clock=lambda: next(ticks),
        )
        == 6
    )


def test_missing_binary(capsys):
    def missing(*args, **kwargs):
        raise FileNotFoundError

    assert remote.main(["list"], run=missing) == 2
    assert "binary not found" in capsys.readouterr().err
