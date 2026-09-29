import os
import subprocess
from pathlib import Path

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
    assert "fake-secret" not in args.read_text() + result.stdout + result.stderr
    assert "preview-hub" in args.read_text()
    assert "chmod 0400" in args.read_text()
    assert "chown 0:0" in args.read_text()
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
