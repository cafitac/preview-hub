import os
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


def test_installer_streams_stdin_not_arguments(tmp_path):
    fake = tmp_path / "ssh"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGS"\ncat > "$INPUT"\n')
    fake.chmod(0o755)
    args, stdin = tmp_path / "args", tmp_path / "stdin"
    env = {
        **os.environ,
        "PATH": str(tmp_path) + ":" + os.environ["PATH"],
        "ARGS": str(args),
        "INPUT": str(stdin),
        "PHUB_SSH_HOST": "test-host",
        "PHUB_REMOTE_PATH": "/a path/it's-bin:/usr/bin:/bin",
        "PHUB_SSH_OPTS": "-o BatchMode=yes",
    }
    result = subprocess.run(
        [str(ROOT / "scripts/bot-token")],
        input="fake-secret",
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0
    assert stdin.read_text() == "fake-secret"
    assert result.stdout == ""
    assert result.stderr.splitlines() == [
        "Paste the token, then press Enter and Ctrl-D (input is hidden).",
        "token installed",
    ]
    assert "fake-secret" not in args.read_text() + result.stdout + result.stderr
    assert "preview-hub" in args.read_text()
    assert "chmod 0400" in args.read_text()
    assert 'chown "$2"' in args.read_text()
    result = subprocess.run(
        [str(ROOT / "scripts/bot-token"), "--check"],
        input="not-consumed",
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0
    assert stdin.read_text() == ""
    assert "Paste the token" not in result.stderr
    assert "token installed" not in result.stderr


def test_installer_rejects_token_argument():
    result = subprocess.run(
        [str(ROOT / "scripts/bot-token"), "fake-secret"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "fake-secret" not in result.stdout + result.stderr


def test_bot_compose_wiring():
    stack = yaml.safe_load((ROOT / "deploy/hub-stack/compose.yaml").read_text())
    bot = stack["services"]["bot"]
    assert bot["image"] == stack["services"]["hub"]["image"]
    assert bot["command"] == ["phub", "bot"]
    assert bot["restart"] == "unless-stopped"
    assert "secrets" not in bot
    assert "/opt/phub/secrets:/run/secrets:ro" in bot["volumes"]
    assert "phub-state:/state" in bot["volumes"]
    assert bot["labels"] == {"dev.phub.managed": "true", "dev.phub.service": "bot"}
    assert "secrets" not in stack
    bootstrap = (ROOT / "scripts/vm-bootstrap.sh").read_text()
    create = "sudo mkdir -p -m 0700 /opt/phub/secrets"
    assert create in bootstrap
    assert bootstrap.index(create) < bootstrap.index("docker compose")


def test_bootstrap_creates_empty_private_secret_directory(tmp_path):
    bootstrap = (ROOT / "scripts/vm-bootstrap.sh").read_text()
    line = next(
        line
        for line in bootstrap.splitlines()
        if "mkdir" in line and "/opt/phub/secrets" in line
    )
    directory = tmp_path / "phub" / "secrets"
    command = line.split("sudo ", 1)[1].replace("/opt/phub/secrets", str(directory))
    subprocess.run(["sh", "-c", command], check=True)
    assert directory.stat().st_mode & 0o777 == 0o700
    assert list(directory.iterdir()) == []
    token = directory / "github_token"
    token.write_text("existing-token")
    token.chmod(0o400)
    subprocess.run(["sh", "-c", command], check=True)
    assert token.read_text() == "existing-token"
    assert token.stat().st_mode & 0o777 == 0o400


@pytest.mark.parametrize("uid_gid", [None, "1000:998"])
@pytest.mark.parametrize("script", ["bot-token", "vm-bootstrap.sh"])
def test_setup_ownership_commands(tmp_path, uid_gid, script):
    capture = tmp_path / "remote"
    fake = tmp_path / "ssh"
    fake.write_text('#!/bin/sh\nfor arg do printf "%s" "$arg" > "$CAPTURE"; done\n')
    fake.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "CAPTURE": str(capture),
    }
    env.pop("PHUB_UID_GID", None)
    if uid_gid is not None:
        env["PHUB_UID_GID"] = uid_gid
    subprocess.run(
        [str(ROOT / "scripts" / script)]
        + (["main"] if script == "vm-bootstrap.sh" else []),
        env=env,
        input="fake-token",
        text=True,
        check=True,
    )
    tokens = shlex.split(capture.read_text())
    index = tokens.index("-c")
    remote_script = tokens[index + 1]
    arguments = tokens[index + 2 :]
    log = tmp_path / "commands"
    env["COMMANDS"] = str(log)
    for command in ("chown", "chmod", "colima", "docker"):
        stub = tmp_path / command
        stub.write_text(
            '#!/bin/sh\nprintf "%s" "${0##*/}" >> "$COMMANDS"\n'
            'printf " <%s>" "$@" >> "$COMMANDS"\nprintf "\\n" >> "$COMMANDS"\n'
        )
        stub.chmod(0o755)
    # Execute generated shell locally; all privileged/remote commands are stubs.
    remote_script = remote_script.replace(
        "/opt/phub/secrets", str(tmp_path / "secrets")
    )
    subprocess.run(
        ["sh", "-c", remote_script, *arguments],
        env=env,
        input="fake-token",
        text=True,
        check=True,
    )
    commands = log.read_text()
    owner = uid_gid or "0:0"
    directory = str(tmp_path / "secrets")
    prefix = "" if script == "bot-token" else "<"
    suffix = "" if script == "bot-token" else ">"
    assert f"{prefix}chown{suffix} <{owner}> <{directory}>" in commands
    assert f"{prefix}chmod{suffix} <0700> <{directory}>" in commands
    if script == "bot-token":
        assert f"chown <{owner}> <{directory}/.github_token." in commands
        assert f"chmod <0400> <{directory}/.github_token." in commands


def test_installer_failure_does_not_report_success(tmp_path):
    fake = tmp_path / "ssh"
    fake.write_text("#!/bin/sh\nexit 1\n")
    fake.chmod(0o755)
    result = subprocess.run(
        [str(ROOT / "scripts/bot-token")],
        input="fake-secret",
        text=True,
        capture_output=True,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        check=False,
    )
    assert result.returncode == 1
    assert "token installed" not in result.stderr
    assert "fake-secret" not in result.stdout + result.stderr
