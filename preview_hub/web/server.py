from __future__ import annotations

import logging
import os
import threading
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp

from ..access import AccessDenied, AccessVerifier, Identity
from ..lifecycle import Context
from ..metrics import Metrics, start_server
from .dashboard import Dashboard


class AccessMiddleware(BaseHTTPMiddleware):
    """U12 routes receive the verified identity as request.state.identity."""

    def __init__(self, app: ASGIApp, verifier: AccessVerifier):
        super().__init__(app)
        self.verifier = verifier

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method == "GET" and request.url.path == "/healthz":
            return await call_next(request)
        # urllib/JWKS I/O must not block the ASGI event loop.
        from starlette.concurrency import run_in_threadpool

        try:
            request.state.identity = await run_in_threadpool(
                self.verifier.verify, request.headers.get("cf-access-jwt-assertion")
            )
        except AccessDenied:
            return PlainTextResponse("unauthorized", status_code=401)
        return await call_next(request)


def identity(request: Request) -> Identity:
    return request.state.identity


def ok(request: Request) -> Response:
    return PlainTextResponse("ok")


def create_app(
    verifier: AccessVerifier | None = None,
    *,
    gc: Callable[[], object] | None = None,
    interval: float = 900,
    dashboard: Dashboard | None = None,
    metrics: Metrics | None = None,
    metrics_port: int = 0,
) -> Starlette:
    active_dashboard = dashboard or Dashboard()

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None]:
        collector = metrics
        if collector is None and metrics_port:
            collector = Metrics(active_dashboard.context.registry.path)
        stop = threading.Event()
        listener = (
            start_server(collector, metrics_port)
            if collector and metrics_port
            else None
        )

        def collect() -> None:
            while not stop.is_set():
                if gc:
                    try:
                        if collector:
                            collector.collect(gc)
                        else:
                            gc()
                    except Exception as exc:  # noqa: BLE001 - keep periodic GC alive
                        # Exception text may contain credentials or command output.
                        logging.getLogger(__name__).error(
                            "gc failed: %s; retrying next interval", type(exc).__name__
                        )
                if stop.wait(interval):
                    break

        thread = threading.Thread(target=collect, name="phub-gc") if gc else None
        if thread:
            thread.start()
        try:
            yield
        finally:
            stop.set()
            if listener:
                from starlette.concurrency import run_in_threadpool

                await run_in_threadpool(listener.shutdown)
                listener.server_close()
            if thread:
                from starlette.concurrency import run_in_threadpool

                await run_in_threadpool(thread.join)

    return Starlette(
        routes=[
            Route("/healthz", ok),
            Route("/auth/verify", ok),
            *active_dashboard.routes(),
        ],
        middleware=[
            Middleware(AccessMiddleware, verifier=verifier or AccessVerifier())
        ],
        lifespan=lifespan,
    )


def serve(
    gc: Callable[[], object], interval: float, *, context: Context | None = None
) -> None:
    dashboard = Dashboard(context)
    port = int(os.environ.get("PHUB_METRICS_PORT", "9100") or 0)
    uvicorn.run(
        create_app(
            gc=gc,
            interval=interval,
            dashboard=dashboard,
            metrics_port=port,
        ),
        host="0.0.0.0",
        port=int(os.environ.get("PHUB_HTTP_PORT", "8080")),
    )
