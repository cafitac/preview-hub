from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol, cast

from .commands import Command


class Runner(Protocol):
    def __call__(self, args: list[str]) -> subprocess.CompletedProcess[str]: ...


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, capture_output=True, text=True, timeout=3600, check=False
    )


@dataclass(frozen=True)
class Result:
    code: int
    data: dict[str, Any]


class Executor:
    def __init__(self, runner: Runner = run):
        self.runner = runner

    def execute(
        self, command: Command, environment: str, service: str = "", sha: str = ""
    ) -> Result:
        args = ["docker", "exec", "phub-hub", "phub", command.action, environment]
        if command.action in {"up", "update"}:
            for key, value in sorted({**command.refs, service: sha}.items()):
                args.extend(["--set", f"{key}={value}"])
            if command.ttl:
                args.extend(["--ttl", command.ttl])
        args.extend(["--format", "json"])
        try:
            completed = self.runner(args)
        except (OSError, subprocess.SubprocessError):
            return Result(5, {"stage": "exec", "message": "Hub execution interrupted"})
        if completed.returncode == 3:
            return Result(3, {"stage": "exec", "message": "busy, retry"})
        raw = completed.stdout if completed.returncode == 0 else completed.stderr
        try:
            parsed: object = json.loads(raw)
        except ValueError:
            parsed = {"stage": "exec", "message": raw[-2000:] or "Hub command failed"}
        data = (
            cast(dict[str, Any], parsed)
            if isinstance(parsed, dict)
            else {
                "state": "DELETED"
                if command.action == "down" and completed.returncode == 0
                else "UNKNOWN"
            }
        )
        return Result(completed.returncode, data)


def cell(value: object) -> str:
    return str(value or "—").replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def format_reply(
    environment: str, result: Result | None = None, *, rejection: str | None = None
) -> str:
    if rejection is not None:
        return f"preview {environment}: REJECTED\n\nReason: {cell(rejection)}"
    assert result is not None
    state = result.data.get("state", "DONE") if result.code == 0 else "FAILED"
    lines = [f"preview {environment}: {state}"]
    if result.code:
        lines.extend(
            [
                "",
                f"Stage: {cell(result.data.get('stage', 'exec'))}",
                f"Service: {cell(result.data.get('service'))}",
                cell(result.data.get("message", "Command failed")),
                "",
                cell(str(result.data.get("log_excerpt", ""))[-2000:]),
            ]
        )
    else:
        lines.extend(["", "| service | commit | URL |", "| --- | --- | --- |"])
        for service in result.data.get("services", []):
            lines.append(
                f"| {cell(service['service'])} | {cell(service['commit_sha'][:12])} | {cell(service.get('public_url'))} |"
            )
    return "\n".join(lines)
