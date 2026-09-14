"""Shared MCP server instance -- imported by tool and resource modules.

`mcp` is process-wide: one `MCPServer` instance whose tool/resource registry
is built once, at import time, via `main._register_modules()`'s side-effect
imports. What is *not* built at import time anymore is the data behind those
tools -- the eager `ResumeStore.load()` this module used to run at import
assumed a `cv-data/` directory reachable by walking up to `pyproject.toml`,
an assumption the repo split breaks (there may be no `cv-data/` at all; data
comes from a `cv` GitHub Release instead).

`create_app()` (`cv_forge.mcp.app`) binds the live `CvDataProvider` via
`set_provider()` before the returned ASGI app serves its first request;
`main()` does the same before `mcp.run()` for the stdio transport. Every
tool and resource reads `get_store()` per call instead of importing a
module-level `store` -- Invariant I2 (a `CvDataProvider` always has data)
means there is no "not loaded yet" state for a call site to handle.
"""

from __future__ import annotations

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

_provider: CvDataProvider | None = None


def set_provider(provider: CvDataProvider) -> None:
    """Bind the active `CvDataProvider`.

    Called once, by `create_app()` or by `main()`'s stdio path, before the
    server can serve a single request.
    """
    global _provider
    _provider = provider


def get_provider() -> CvDataProvider:
    """The bound provider.

    Raises if called before `set_provider()` -- a missing lifespan wiring,
    not a runtime condition any tool call should observe in a correctly
    started server.
    """
    if _provider is None:
        raise RuntimeError(
            "CvDataProvider not bound -- call set_provider() "
            "(via create_app() or main()) before serving requests"
        )
    return _provider


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
