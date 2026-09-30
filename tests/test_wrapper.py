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
    for path in [*Path("scripts").glob("*"), *Path("e2e").glob("*.sh")]:
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


def public_helpers():
    source = Path("e2e/public.sh").read_text()
    return (
        source[source.index("delete_branch() {") : source.index("cleanup() {")]
        + source[source.index("public_check() {") : source.index("vm_check() {")]
        + source[source.index("retry_read() (") : source.index("quote() {")]
        + source[
            source.index("links() {") : source.index("printf '%s\\n' 'public E2E: up'")
        ]
        + source[
            source.index("create_branch() (") : source.index(
                "printf '%s\\n' 'public E2E: branches/PRs'"
            )
        ]
    )


def run_public_helpers(tmp_path, body):
    return subprocess.run(
        ["sh", "-eu", "-c", public_helpers() + body],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("failures", [0, 2, 5])
def test_public_read_retry(tmp_path, failures):
    result = run_public_helpers(
        tmp_path,
        f"""
api() {{
    n=$(cat calls 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > calls
    if [ "$n" -le {failures} ]; then echo secret-response >&2; return 1; fi
    echo expected
}}
sleep() {{ echo "$1" >> sleeps; }}
retry_read readme synthetic
""",
    )
    assert int((tmp_path / "calls").read_text()) == min(failures + 1, 5)
    assert result.returncode == (1 if failures == 5 else 0)
    assert result.stdout == ("" if failures == 5 else "expected\n")
    assert result.stderr == ("GitHub read failed: readme\n" if failures == 5 else "")
    if failures:
        assert (tmp_path / "sleeps").read_text().splitlines() == ["2"] * min(
            failures, 4
        )


@pytest.mark.parametrize("timeout", [False, True])
def test_public_wait_pr_head(tmp_path, timeout):
    result = run_public_helpers(
        tmp_path,
        f"""
api() {{
    n=$(cat reads 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > reads
    if [ "$n" -eq 1 ] || [ '{timeout}' = True ]; then echo old; else echo created; fi
}}
date() {{
    n=$(cat clock 2>/dev/null || echo 0); echo $((n + 1)) > clock
    echo $((n * {60 if timeout else 1}))
}}
sleep() {{ echo "$1" >> sleeps; }}
wait_pr_head owner/repo 7 created
""",
    )
    assert result.returncode == (1 if timeout else 0)
    assert result.stdout == ("" if timeout else "created\n")
    assert result.stderr == ("PR head timeout (60 seconds)\n" if timeout else "")
    if not timeout:
        assert (tmp_path / "sleeps").read_text() == "1\n"


@pytest.mark.parametrize("kind", ["branch", "pr"])
@pytest.mark.parametrize("created", [False, True])
def test_public_creation_recovers_before_retry(tmp_path, kind, created):
    result = run_public_helpers(
        tmp_path,
        f"""
branch=e2e/synthetic
api() {{
    case "$*" in
        *git/ref/heads/main*) echo base;;
        *'-X POST'*)
            n=$(cat writes 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > writes
            if [ "$n" -eq 1 ]; then echo secret-response >&2; return 1; fi
            echo 7;;
        *)
            echo checked >> checks
            if [ '{created}' = True ]; then echo 7; fi;;
    esac
}}
sleep() {{ echo "$1" >> sleeps; }}
create_{kind} owner/repo
""",
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == ("7\n" if kind == "pr" else "")
    assert (tmp_path / "writes").read_text().strip() == ("1" if created else "2")
    assert (tmp_path / "checks").read_text() == "checked\n"
    if not created:
        assert (tmp_path / "sleeps").read_text() == "2\n"


@pytest.mark.parametrize("kind", ["branch", "pr"])
@pytest.mark.parametrize("lookup_fails", [False, True])
def test_public_creation_failure_is_bounded(tmp_path, kind, lookup_fails):
    result = run_public_helpers(
        tmp_path,
        f"""
branch=e2e/synthetic
api() {{
    case "$*" in
        *git/ref/heads/main*) echo base;;
        *'-X POST'*) echo write >> writes; return 1;;
        *) echo read >> reads; [ '{lookup_fails}' = False ];;
    esac
}}
sleep() {{ :; }}
create_{kind} owner/repo
""",
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert len((tmp_path / "writes").read_text().splitlines()) == (
        1 if lookup_fails else 5
    )
    assert len((tmp_path / "reads").read_text().splitlines()) == 5
    step = "branch-check" if kind == "branch" else "pr-check"
    assert result.stderr == (
        f"GitHub read failed: {step}\n"
        if lookup_fails
        else f"GitHub write failed: create-{kind}\n"
    )


@pytest.mark.parametrize("failures", [2, 5])
def test_public_main_sha_read_retry(tmp_path, failures):
    result = run_public_helpers(
        tmp_path,
        f"""
branch=e2e/synthetic
api() {{
    case "$*" in
        *git/ref/heads/main*)
            n=$(cat reads 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > reads
            [ "$n" -gt {failures} ] || return 1
            echo base;;
        *'-X POST'*) echo "$*" > write;;
        *) return 1;;
    esac
}}
sleep() {{ :; }}
create_branch owner/repo
""",
    )
    assert (tmp_path / "reads").read_text().strip() == str(min(failures + 1, 5))
    assert result.returncode == (1 if failures == 5 else 0)
    assert result.stdout == ""
    if failures == 5:
        assert result.stderr == "GitHub read failed: main-sha\n"
        assert not (tmp_path / "write").exists()
    else:
        assert result.stderr == ""
        assert "-f sha=base" in (tmp_path / "write").read_text()


@pytest.mark.parametrize("failures", [2, 5])
def test_public_comments_read_retry_to_file(tmp_path, failures):
    result = run_public_helpers(
        tmp_path,
        f"""
work=. env=pub-synthetic backend=owner/backend frontend=owner/frontend
bpr=1 fpr=2 bsha=backend-sha fsha=frontend-sha wait_seconds=40
api() {{
    echo "$*" >> args
    n=$(cat reads 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > reads
    if [ "$n" -le {failures} ]; then echo partial; return 1; fi
    echo '[[{{"id": 7}}]]'
}}
# Stub filtering only; exercise the real read, retry and output redirection.
jq() {{
    case "$1" in
        --arg) cat "$work/pages.json" > filtered; echo '[{{"id": 7}}]';;
        length) echo 1;;
        -e) return 0;;
        -r) echo 7;;
        *) return 1;;
    esac
}}
sleep() {{ :; }}
links READY
""",
    )
    assert result.returncode == (1 if failures == 5 else 0)
    assert result.stdout == ""
    assert all(
        line.startswith("--paginate --slurp repos/")
        and line.endswith("/comments?per_page=100")
        for line in (tmp_path / "args").read_text().splitlines()
    )
    if failures == 5:
        assert result.stderr == "GitHub read failed: comments\n"
        assert (tmp_path / "pages.json").read_text() == ""
        assert not (tmp_path / "filtered").exists()
    else:
        assert result.stderr == ""
        assert (tmp_path / "reads").read_text().strip() == "4"
        assert json.loads((tmp_path / "filtered").read_text()) == [[{"id": 7}]]
        for service in ("backend", "frontend"):
            assert (tmp_path / f"{service}-id").read_text() == "7\n"


def test_public_negative_environment_is_process_specific():
    import re

    source = Path("e2e/public.sh").read_text()
    assignment = next(line for line in source.splitlines() if line.startswith("bad="))
    names = []
    for _ in range(2):
        result = subprocess.run(
            ["sh", "-eu", "-c", assignment + '\nprintf "%s" "$bad"'],
            capture_output=True,
            text=True,
            check=True,
        )
        assert re.fullmatch(r"[a-z][a-z0-9-]{1,30}", result.stdout)
        names.append(result.stdout)
    assert names[0] != names[1]
    assert "all(.[]; .name != $name and .name != $env)" in source
    assert source.index("all(.[]; .name != $name and .name != $env)") < source.index(
        "bad_owned=1"
    )


@pytest.mark.parametrize("status", [204, 404, 422, 403, 500])
def test_public_delete_branch_status(tmp_path, status):
    result = run_public_helpers(
        tmp_path,
        f"""
work=. branch=e2e/synthetic
api() {{ echo 'HTTP/2 {status}'; echo secret-body; [ {status} = 204 ]; }}
delete_branch owner/repo
""",
    )
    assert result.returncode == (0 if status in (204, 404, 422) else 1)
    assert result.stdout == ""
    assert result.stderr == (
        "" if status in (204, 404, 422) else "GitHub write failed: delete-branch\n"
    )


@pytest.mark.parametrize("team", ["cafitac.cloudflareaccess.com", "other.example.com"])
@pytest.mark.parametrize("matches", [False, True])
def test_public_redirect_team(tmp_path, team, matches):
    host = team if matches else "unexpected.example.com"
    result = run_public_helpers(
        tmp_path,
        f"""
work=. access_team_domain={team}
curl() {{
    printf 'Location: https://{host}/login?secret=value\\n' > headers
    printf 302
}}
public_check preview.example.com 302
""",
    )
    assert result.returncode == (0 if matches else 1)
    assert "secret" not in result.stderr + result.stdout
    if not matches:
        assert result.stderr == (
            f"Access redirect expected team domain {team}; got different host\n"
        )


@pytest.mark.parametrize(
    "domain",
    [
        "team.example.com",
        "https://team.example.com",
        "",
        "team:443",
        "-team.example",
        "a" * 64 + ".example",
    ],
)
def test_public_team_hostname_validation(tmp_path, domain):
    source = Path("e2e/public.sh").read_text()
    validation = source[
        source.index("access_team_domain=") : source.index("work=$(mktemp")
    ]
    result = subprocess.run(
        ["sh", "-eu", "-c", validation],
        env={**os.environ, "PHUB_ACCESS_TEAM_DOMAIN": domain},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == (0 if domain == "team.example.com" else 1)


def test_public_branch_ownership_precedes_creation():
    source = Path("e2e/public.sh").read_text()
    for service, flag in (("backend", "bbranch"), ("frontend", "fbranch")):
        assert f'{flag}=1\ncreate_branch "${service}"' in source


@pytest.mark.parametrize(
    "service,flag", [("backend", "bbranch"), ("frontend", "fbranch")]
)
def test_public_failed_creation_still_cleans_owned_branch(tmp_path, service, flag):
    source = Path("e2e/public.sh").read_text()
    cleanup = source[source.index("close_pr() {") : source.index("trap cleanup 0")]
    creation = f'{flag}=1\ncreate_branch "${service}"'
    result = run_public_helpers(
        tmp_path,
        cleanup
        + f"""
work=$(mktemp -d) branch=e2e/synthetic
backend=owner/backend frontend=owner/frontend
bpr= fpr= bbranch=0 fbranch=0 env_owned=0 bad_owned=0
api() {{ echo "$*" >> '{tmp_path}/deletes'; }}
create_branch() {{ return 1; }}
trap cleanup 0
{creation}
""",
    )
    assert result.returncode == 1
    assert (tmp_path / "deletes").read_text() == (
        f"-X DELETE repos/owner/{service}/git/refs/heads/e2e/synthetic --include\n"
    )
