from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATES = (
    "REQUESTED",
    "RESOLVING",
    "BUILDING",
    "STARTING",
    "UPDATING",
    "READY",
    "FAILED",
    "DELETING",
)


class Metrics:
    def __init__(self, path: Path, clock: Callable[[], float] = time.time):
        self.path = path
        self.clock = clock
        self.lock = threading.Lock()
        self.last_success = 0.0
        self.failures = 0

    def collect(self, gc: Callable[[], object]) -> None:
        try:
            gc()
        except Exception:
            with self.lock:
                self.failures += 1
            raise
        with self.lock:
            self.last_success = self.clock()

    def render(self) -> str:
        db = sqlite3.connect(
            f"{self.path.resolve().as_uri()}?mode=ro", uri=True, timeout=1
        )
        try:
            counts = dict(
                db.execute("SELECT state,COUNT(*) FROM environments GROUP BY state")
            )
            starts = db.execute(
                "SELECT started_at FROM operations WHERE status='RUNNING'"
            ).fetchall()
        finally:
            db.close()
        age = max(
            (
                self.clock() - datetime.fromisoformat(row[0]).timestamp()
                for row in starts
            ),
            default=0,
        )
        with self.lock:
            success, failures = self.last_success, self.failures
        lines = ["# TYPE phub_environments gauge"]
        lines.extend(
            f'phub_environments{{state="{state}"}} {counts.get(state, 0)}'
            for state in STATES
        )
        for name, kind, value in (
            ("phub_operation_running_oldest_seconds", "gauge", max(0, age)),
            ("phub_gc_last_success_timestamp_seconds", "gauge", success),
            ("phub_gc_failures_total", "counter", failures),
            ("phub_up", "gauge", 1),
        ):
            lines.extend((f"# TYPE {name} {kind}", f"{name} {value}"))
        return "\n".join(lines) + "\n"


def start_server(metrics: Metrics, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.command != "GET" or self.path != "/metrics":
                self.send_error(404)
                return
            try:
                body = metrics.render().encode()
            except Exception:  # noqa: BLE001 - scrapes must never disclose details
                self.send_response(500)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_error(
            self, code: int, message: str | None = None, explain: str | None = None
        ) -> None:
            super().send_error(404 if code == 501 else code)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(
        target=server.serve_forever, name="phub-metrics", daemon=True
    ).start()
    return server
