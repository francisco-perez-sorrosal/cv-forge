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

The lifespan below binds the provider into the shared tool registry
(`cv_forge.mcp.server.set_provider`), starts the background refresh loop (a
no-op when `provider` has no fetcher -- Invariant I4), and only then enters
the MCP session manager's own lifespan (`session_manager.run()`) -- so on
shutdown the refresh task is cancelled *before* the session manager tears
down, the reverse of acquisition order.

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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from cv_forge.data.provider import CvDataProvider, Fresh, Pinned, RefreshState, Stale
from cv_forge.data.snapshot import BakedSnapshot, DataOrigin, LocalDir, ReleaseAssets
from cv_forge.mcp.server import mcp, set_provider

# Wasmer Edge terminates and validates the public hostname in front of this
# app; the internal ASGI hop does not need a second DNS-rebinding check, and
# the SDK's default (`enable_dns_rebinding_protection=True` with an empty
# `allowed_hosts`) would reject every request whose `Host` header isn't on
# that empty allowlist.
_TRANSPORT_SECURITY = TransportSecuritySettings(enable_dns_rebinding_protection=False)


def create_app(provider: CvDataProvider, *, stateless: bool = True) -> Starlette:
    """Build the ASGI app backing both the Edge entrypoint and `cv-forge serve`."""
    set_provider(provider)

    inner_app = mcp.streamable_http_app(
        stateless_http=stateless, transport_security=_TRANSPORT_SECURITY
    )
    # The specific manager `streamable_http_app()` just created -- captured
    # locally rather than re-read from `mcp.session_manager` later, so a
    # second `create_app()` call in the same process (tests build several)
    # can never make this lifespan enter someone else's manager.
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
    return Starlette(routes=[healthz_route, *inner_app.routes], lifespan=lifespan)


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
        "cv_forge_version": _cv_forge_version(),
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


def _cv_forge_version() -> str:
    return importlib.metadata.version("cv-forge")
