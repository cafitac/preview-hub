"""Exercise the live shell driver offline, including its failure cleanup."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
FAKE = r"""#!/usr/bin/env python3
import base64
import json
import os
import pathlib
import sys

path = pathlib.Path(os.environ["FAKE_STATE"])
s = json.loads(path.read_text())
args = sys.argv[1:]
name = pathlib.Path(sys.argv[0]).name
result = None
if name == "gh":
    if args == ["auth", "token", "--user", "cafitac"]:
        print("fake-owner-secret")
        sys.exit(0)
    assert os.environ["GH_TOKEN"] == "fake-owner-secret"
    assert not os.environ.get("GH_DEBUG")
    endpoint = next(a for a in args if a.startswith("repos/"))
    method = args[args.index("-X") + 1] if "-X" in args else "GET"
    s["requests"].append([method, endpoint])
    fields = dict(a.split("=", 1) for a in args if "=" in a and not a.startswith("repos/"))
    if endpoint.endswith("git/ref/heads/main"):
        result = "a" * 40
    elif endpoint.endswith("git/refs"):
        assert fields["ref"].startswith("refs/heads/e2e/bot-")
        s["branch"] = True
    elif "git/refs/heads/e2e/bot-" in endpoint:
        assert method == "DELETE"
        s["branch"] = False
    elif "/contents/README.md" in endpoint:
        if method == "GET":
            result = {"sha": "c" * 40, "content": base64.b64encode(b"README\n").decode()}
        else:
            payload = json.loads(pathlib.Path(args[args.index("--input") + 1]).read_text())
            assert payload["branch"].startswith("e2e/bot-")
            assert base64.b64decode(payload["content"]).startswith(b"README\n")
            result = "b" * 40
    elif endpoint.endswith("/pulls"):
        assert fields["base"] == "main"
        s["pr"] = "open"
        result = 42
    elif "/comments" in endpoint:
        if method == "POST":
            cid = len(s["comments"]) + 1
            body = fields["body"]
            s["comments"].append({"id": cid, "body": body})
            s["state"] = "DELETED" if body == "/preview down" else "READY"
            reply = "preview pr-backend-42: " + s["state"] + "\n| backend | bbbbbbbbbbbb | http://api |"
            s["comments"].append({"id": cid + 1, "body": reply})
            if os.environ.get("DUPLICATE"):
                s["comments"].append({"id": cid + 2, "body": reply})
            result = cid
        else:
            result = [s["comments"]]
    elif endpoint.endswith("/pulls/42"):
        if method == "PATCH":
            s["pr"] = "closed"
            s["state"] = "DELETED"
        else:
            result = s["pr"]
    else:
        raise AssertionError(endpoint)
elif name == "phub":
    s["hub"].append(args)
    if args[0] == "inventory":
        result = {"containers": [], "networks": [], "volumes": []}
    elif args[0] == "down":
        s["state"] = "DELETED"
        result = {"state": "DELETED"}
    elif args[0] == "list":
        result = [{"id": 1, "name": "pr-backend-42"}]
    elif args[0] == "status":
        result = {"id": 1, "version": 1, "state": s["state"],
                  "services": [{"service": "backend", "commit_sha": "b" * 40}]}
    else:
        raise AssertionError(args)
else:
    assert name == "sleep"
path.write_text(json.dumps(s))
if result is not None:
    print(result if isinstance(result, str) else json.dumps(result))
"""


@pytest.mark.parametrize("duplicate", [False, True])
def test_live_driver_offline(tmp_path, duplicate):
    (tmp_path / "e2e").mkdir()
    (tmp_path / "scripts").mkdir()
    script = tmp_path / "e2e/bot.sh"
    shutil.copy(ROOT / "e2e/bot.sh", script)
    for name in ("gh", "sleep", "scripts/phub"):
        fake = tmp_path / name
        fake.write_text(FAKE)
        fake.chmod(0o755)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"comments": [], "requests": [], "hub": []}))
    result = subprocess.run(
        ["sh", "-x", str(script)],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "FAKE_STATE": str(state),
            "DUPLICATE": "1" if duplicate else "",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == (1 if duplicate else 0), result.stderr
    assert "fake-owner-secret" not in result.stdout + result.stderr
    saved = json.loads(state.read_text())
    assert saved["pr"] == "closed"
    assert saved["branch"] is False
    assert saved["state"] == "DELETED"
    assert saved["hub"][-2:] == [
        ["down", "pr-backend-42", "--format", "json"],
        ["inventory", "pr-backend-42"],
    ]
    if duplicate:
        assert "Duplicate reply" in result.stderr
    else:
        assert "A9(a)-(e) passed" in result.stdout
        assert "exactly-once" in result.stdout
