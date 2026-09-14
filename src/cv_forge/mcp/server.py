"""Shared MCP server instance -- imported by tool and resource modules.

`mcp` is process-wide: one `MCPServer` instance whose tool/resource registry
is built once, at import time, via `main._register_modules()`'s side-effect
imports. What is *not* built at import time anymore is the data behind those
tools -- the eager `ResumeStore.load()` this module used to run at import
assumed a `cv-data/` directory reachable by walking up to `pyproject.toml`,
an assumption the repo split breaks (there may be no `cv-data/` at all; data
comes from a `cv` GitHub Release instead).

Tool/resource functions take no `Context` parameter and call `get_store()`/
`get_provider()` with no arguments, so the active `CvDataProvider` cannot be
threaded through a call's own parameters -- it has to be ambient. A single
mutable module global would make that ambient state process-wide, so two
`create_app()` instances built in the same process (tests build several; a
future in-process harness might too) would silently repoint each other's
tools. `bound_provider()` instead binds the provider onto a `ContextVar`:
each `create_app()`'s request-scoping middleware (`cv_forge.mcp.app`) opens
one binding per inbound HTTP request, and `main()`'s stdio path opens one
binding for the whole process (there is only ever one provider there). A
`ContextVar` set inside a coroutine is visible to that coroutine and to any
task spawned under it afterwards, but never to a sibling task or a
differently-bound app -- exactly the per-request/per-process isolation this
needs, with no cross-app leakage.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from cv_forge.data.provider import CvDataProvider
from cv_forge.data.store import ResumeStore

mcp = MCPServer("cv_francisco_perez_sorrosal")

# Every tool here is a pure, read-only query over one person's CV -- one
# shared annotation, applied uniformly rather than repeated per decorator.
READ_ONLY_TOOL = ToolAnnotations(
    read_only_hint=True, idempotent_hint=True, open_world_hint=False
)

_active_provider: ContextVar[CvDataProvider] = ContextVar("cv_forge_active_provider")


@contextmanager
def bound_provider(provider: CvDataProvider) -> Iterator[None]:
    """Bind `provider` as the active one for every `get_provider()` call made
    inside this context (and in any task spawned while inside it).

    See the module docstring for why this replaces a single mutable global.
    """
    token = _active_provider.set(provider)
    try:
        yield
    finally:
        _active_provider.reset(token)


def get_provider() -> CvDataProvider:
    """The provider bound by the innermost enclosing `bound_provider()`.

    Raises if called outside one -- a missing lifespan/middleware wiring,
    not a runtime condition any tool call should observe in a correctly
    started server.
    """
    try:
        return _active_provider.get()
    except LookupError as exc:
        raise RuntimeError(
            "CvDataProvider not bound -- call within bound_provider(...) "
            "(via create_app()'s request middleware or main()'s stdio path) "
            "before serving requests"
        ) from exc


def get_store() -> ResumeStore:
    """Convenience accessor -- most tools only need read access to the
    store, not the provider's refresh/health machinery."""
    return get_provider().store


def _register_modules() -> None:
    """Import every tool/resource module to activate its `@mcp.tool` and
    `@mcp.resource` decorators.

    Triggered here, at the bottom of this module, rather than in `main.py` --
    any entry point that imports `cv_forge.mcp.server` (directly, or via
    `cv_forge.mcp.app.create_app`) gets a fully-registered `mcp`. Each tool
    module imports back `from cv_forge.mcp.server import mcp, ...`; that
    import resolves against this already-executing module (Python caches the
    partially-initialized module in `sys.modules`), which is why this call
    sits after every name a tool module might import, not before.
    """
    import importlib
    import pkgutil

    import cv_forge.mcp.tools

    for _, name, _ in pkgutil.iter_modules(cv_forge.mcp.tools.__path__):
        importlib.import_module(f"cv_forge.mcp.tools.{name}")
    importlib.import_module("cv_forge.mcp.resources")


_register_modules()
