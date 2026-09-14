"""ASGI app factory for the CV MCP server.

`create_app(provider)` binds an already-loaded `CvDataProvider` (Invariant
I2 -- a `CvDataProvider` always has data, so there is no providerless app to
build) and returns a single ASGI app serving the MCP protocol at `POST /mcp`
and a liveness probe at `GET /healthz`.

Stateless streamable HTTP is built explicitly here (`stateless=True` by
default) because the Edge entrypoint (`main:app`, a plain ASGI callable) never
calls `MCPServer.run()` -- if statelessness lived only on `run()`'s keyword
arguments, Edge and a local `cv-forge serve` invocation would silently
diverge on session semantics. `cv_forge.mcp.main.main()` threads the same
`stateless` value through both the ASGI-app path and the stdio path for the
same reason.

The returned app's lifespan enters the MCP session manager's own lifespan
(`session_manager.run()`) and starts the background refresh loop (a no-op
when `provider` has no fetcher -- Invariant I4) inside it, so on shutdown the
refresh task is cancelled *before* the session manager tears down, the
reverse of acquisition order. `_BindProviderMiddleware` binds `provider` onto
`cv_forge.mcp.server`'s request-scoped `ContextVar` for the duration of every
inbound HTTP request, so tools and resources -- which take no `Context`
parameter and call `get_store()`/`get_provider()` with no arguments -- reach
*this app's* provider even when a second `create_app()` runs in the same
process.

A 503 `no_validated_snapshot` response (`INTERFACE_DESIGN.md` §3.2) has no
code path here: `provider` is a required, already-validated
`CvDataProvider` (Invariant I2), so there is no in-process call shape that
reaches "loaded, but no data yet" -- that state is only observable from
outside the process, in the window before this ASGI app's lifespan has
completed a first pass (or if a baked snapshot fails to parse before
`create_app` is ever called). A live probe, not a unit test, is what proves
that window is short.
"""

from __future__ import annotations

import importlib.metadata
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from cv_forge.data.provider import CvDataProvider, Fresh, Pinned, RefreshState, Stale
from cv_forge.data.snapshot import BakedSnapshot, DataOrigin, LocalDir, ReleaseAssets
from cv_forge.mcp.server import bound_provider, mcp

# `main.py`'s stdio and local `streamable-http` paths have no front door
# validating the `Host`/`Origin` headers for them, so the default here stays
# *protected*, mirroring the SDK's own localhost defaults
# (`mcp.server.lowlevel.server.streamable_http_app`) verbatim plus the
# in-process test transport's synthetic hostname. `CV_ALLOWED_ORIGINS`
# (comma-separated) extends `allowed_origins` for a non-default local port
# (e.g. a dev frontend on :3000) without disabling the check entirely. Only
# `CV_TRUST_HOST=1` -- set by `scripts/deploy.sh` for the Edge image, where
# Wasmer Edge already terminates and validates the public hostname in front
# of this app -- turns the whole check off; the SDK's own default
# (`enable_dns_rebinding_protection=True` with empty `allowed_hosts`/
# `allowed_origins`) would otherwise reject every request there too.
_LOCAL_ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*", "testserver"]
_LOCAL_ALLOWED_ORIGINS = [
    "http://127.0.0.1:*",
    "http://localhost:*",
    "http://[::1]:*",
]


def _resolve_cv_forge_version() -> str:
    """Resolved once at import, not per `/healthz` request -- both because a
    filesystem/dist-info scan on every liveness probe is wasted work, and
    because an MCPB or Wasmer bundle can ship importable code with no
    dist-info at all, which would otherwise turn a healthy server into a 500
    on the very probe meant to prove it is alive."""
    try:
        return importlib.metadata.version("cv-forge")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


_CV_FORGE_VERSION = _resolve_cv_forge_version()


def _local_allowed_origins() -> list[str]:
    origins = list(_LOCAL_ALLOWED_ORIGINS)
    extra = os.environ.get("CV_ALLOWED_ORIGINS", "")
    origins.extend(origin.strip() for origin in extra.split(",") if origin.strip())
    return origins


def _transport_security() -> TransportSecuritySettings:
    if os.environ.get("CV_TRUST_HOST") == "1":
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_LOCAL_ALLOWED_HOSTS,
        allowed_origins=_local_allowed_origins(),
    )


class _BindProviderMiddleware:
    """Binds `provider` into `cv_forge.mcp.server`'s request-scoped
    `ContextVar` for the duration of one HTTP request -- see `app.py`'s
    module docstring for why tool/resource call sites need this rather than
    a plain module global."""

    def __init__(self, app: ASGIApp, *, provider: CvDataProvider) -> None:
        self._app = app
        self._provider = provider

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        with bound_provider(self._provider):
            await self._app(scope, receive, send)


def create_app(provider: CvDataProvider, *, stateless: bool = True) -> Starlette:
    """Build the ASGI app backing both the Edge entrypoint and `cv-forge serve`."""
    inner_app = mcp.streamable_http_app(
        stateless_http=stateless, transport_security=_transport_security()
    )
    # The specific manager `streamable_http_app()` just created -- captured
    # locally rather than re-read from `mcp.session_manager` later, so a
    # second `create_app()` call in the same process (tests build several)
    # can never make this lifespan enter someone else's manager. Note for
    # test authors: `session_manager.run()` can only be entered once per
    # instance ("StreamableHTTPSessionManager .run() can only be called
    # once per instance") -- a real server enters this app's lifespan
    # exactly once, but a test that drives the ASGI lifespan protocol by
    # hand twice against the *same* `create_app()` result will hit this;
    # do everything one test needs inside a single lifespan entry instead.
    session_manager = mcp.session_manager

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        stop = anyio.Event()
        async with session_manager.run():
            async with anyio.create_task_group() as tg:
                tg.start_soon(provider.run_refresh_loop, stop)
                try:
                    yield
                finally:
                    stop.set()

    healthz_route = Route("/healthz", _healthz_handler(provider), methods=["GET"])
    app = Starlette(
        routes=[healthz_route, *inner_app.routes],
        middleware=[Middleware(_BindProviderMiddleware, provider=provider)],
        lifespan=lifespan,
    )
    app.state.provider = provider
    return app


def _healthz_handler(provider: CvDataProvider):
    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse(_healthz_body(provider))

    return healthz


def _healthz_body(provider: CvDataProvider) -> dict[str, object]:
    """`INTERFACE_DESIGN.md` §3.2's `200` body.

    `refresh_state` is the discriminator for the optional fields:
    `consecutive_failures`/`last_success_at` appear on `Fresh`/`Stale` only,
    `last_error` on `Stale` only, and `pinned` carries neither.
    """
    state = provider.state
    body: dict[str, object] = {
        "status": "ok",
        "origin": _origin_body(provider.snapshot.origin),
        "release_tag": provider.current_tag,
        "loaded_at": provider.snapshot.loaded_at.isoformat(),
        "refresh_state": _state_kind(state),
        "cv_forge_version": _CV_FORGE_VERSION,
    }
    if isinstance(state, Fresh | Stale):
        body["consecutive_failures"] = provider.consecutive_failures
        if provider.last_success_at is not None:
            body["last_success_at"] = provider.last_success_at.isoformat()
    if isinstance(state, Stale):
        body["last_error"] = state.last_error
    return body


def _state_kind(state: RefreshState) -> str:
    """Exhaustive match over `RefreshState` -- a future variant must be
    handled explicitly here, not silently absorbed into a default branch."""
    match state:
        case Pinned():
            return "pinned"
        case Fresh():
            return "fresh"
        case Stale():
            return "stale"


def _origin_body(origin: DataOrigin) -> dict[str, object]:
    """Exhaustive match over `DataOrigin` -- see `_state_kind`."""
    match origin:
        case LocalDir(path=path):
            return {"kind": "local_dir", "path": str(path)}
        case ReleaseAssets(tag=tag, published_at=published_at):
            return {
                "kind": "release",
                "tag": tag,
                "published_at": published_at.isoformat(),
            }
        case BakedSnapshot(staged_at=staged_at, tag=tag):
            return {"kind": "baked", "staged_at": staged_at.isoformat(), "tag": tag}
