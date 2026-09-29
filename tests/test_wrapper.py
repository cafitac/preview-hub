import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("docker", ["docker", "/custom bin/docker'cli"])
def test_wrapper_quoting_and_disk_guard(tmp_path, docker):
    ssh = tmp_path / "ssh"
    ssh.write_text("""#!/usr/bin/env python3
import json, os, shlex, sys
command = sys.argv[-1]
assert shlex.split(command.split(";", 1)[0]) == [
    "export", "PATH=" + os.environ.get("PHUB_REMOTE_PATH", "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin")
]
if command.endswith(' df -Pk ~'):
    print('Filesystem 1024-blocks Used Available Capacity Mounted')
    print('disk 100000000 1 ' + os.environ.get('FREE_KB', '20000000') + ' 1% /')
else:
    print(json.dumps(shlex.split(command.split(";", 1)[1])))
""")
    ssh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "PHUB_REMOTE_DOCKER": docker,
    }
    args = [
        "up",
        "test-one",
        "--set",
        "backend=space ' quote $d `x`; end\n\n",
        "--ttl",
        "1h",
    ]
    result = subprocess.run(
        ["sh", "scripts/phub", *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        docker,
        "--context",
        "colima-preview-hub",
        "exec",
        "-i",
        "phub-hub",
        "phub",
        *args,
    ]
    result = subprocess.run(
        ["sh", "scripts/phub", *args],
        env={**env, "FREE_KB": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 4
    assert not result.stdout


def test_shell_syntax():
    for path in [*Path("scripts").glob("*"), Path("e2e/run.sh")]:
        subprocess.run(["sh", "-n", str(path)], check=True)


@pytest.mark.parametrize("source_mode", [False, True])
@pytest.mark.parametrize("public_files", ["both", "credentials-only", "neither"])
def test_bootstrap_remote_execution(tmp_path, source_mode, public_files):
    import tarfile

    source = tmp_path / "source with spaces"
    source.mkdir()
    (source / "dirty.txt").write_text("unpushed change")
    for name in (".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"):
        (source / name).mkdir()
        (source / name / "ignored").write_text("ignored")
    ssh = tmp_path / "ssh"
    ssh.write_text("""#!/usr/bin/env python3
import os, subprocess, sys
from pathlib import Path
Path(os.environ['CAPTURE']).write_bytes(sys.stdin.buffer.read())
subprocess.run(sys.argv[-1], shell=True, check=True, stdin=subprocess.DEVNULL)
""")
    colima = tmp_path / "colima"
    colima.write_text("""#!/bin/sh
printf '%s\\n' "$*" >> "$CALLS"
case "$1" in
status) exit 1;;
ssh) case "$*" in
    *"test -f /opt/phub/secrets/tunnel.json") [ "$PUBLIC_FILES" != neither ];;
    *"test -f /opt/phub/public.env") [ "$PUBLIC_FILES" = both ];;
    *mktemp*) echo /tmp/phub-build.test;;
    *"id -u") echo 501;;
    *"id -g") echo 20;;
    esac;;
esac
""")
    docker = tmp_path / "docker 'custom"
    docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\n')
    for executable in (ssh, colima, docker):
        executable.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "PHUB_REMOTE_PATH": f"{tmp_path}:/usr/bin:/bin",
        "PHUB_REMOTE_DOCKER": str(docker),
        "PUBLIC_FILES": public_files,
        "CAPTURE": str(tmp_path / "archive"),
        "CALLS": str(tmp_path / "calls"),
    }
    args = ["--source-dir", str(source)] if source_mode else ["feature/ref", "repo url"]
    subprocess.run(["sh", "scripts/vm-bootstrap.sh", *args], env=env, check=True)
    calls = (tmp_path / "calls").read_text()
    assert ("--profile public up -d" in calls) is (public_files == "both")
    assert "--activate=false" in calls
    assert (
        calls.splitlines()[-1]
        == "ssh --profile preview-hub -- rm -rf /tmp/phub-build.test"
    )
    assert "buildx build --load" in calls
    assert "--context colima-preview-hub" in calls
    assert ("alpine/git" in calls) is not source_mode
    if source_mode:
        with tarfile.open(tmp_path / "archive") as archive:
            assert set(archive.getnames()) == {".", "./dirty.txt"}
            member = archive.extractfile("./dirty.txt")
            assert member is not None
            assert member.read() == b"unpushed change"
    else:
        assert "repo url feature/ref" in calls
        assert "run --rm --user 501:20 -v /tmp/phub-build.test:/work" in calls
