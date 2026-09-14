"""Entry point for the CV MCP server.

Builds a `CvDataProvider` from the environment exactly once, then serves it
through the same `create_app()` factory the Edge entrypoint (repo-root
`main.py`, added in a later step) uses -- local
`pixi run mcps --transport streamable-http` and the deployed Wasmer app
answer identically because both are the same ASGI app, built the same way,
with the same `stateless_http` setting. Tool/resource registration is a
side effect of importing `cv_forge.mcp.server` (see that module's
`_register_modules`), not of importing this one.

Environment parsing and provider construction live in
`cv_forge.data.bootstrap` (shared with the `cv-forge serve` CLI); this
module's own job is rendering that module's raised exceptions as an
actionable startup error and choosing an exit code, not path/network policy.
"""

from __future__ import annotations

import os
import sys
from typing import Literal, NoReturn, cast

from loguru import logger

from cv_forge.data.bootstrap import (
    InvalidCvDataError,
    InvalidRefreshIntervalError,
    StartupError,
    build_provider_from_env,
    describe_startup_error,
)
from cv_forge.data.local import LocalDataDirError
from cv_forge.data.provider import CvDataProvider
from cv_forge.mcp.server import bound_provider, mcp

DEFAULT_PORT = 10000


def _build_provider_or_exit() -> CvDataProvider:
    """`build_provider_from_env()`, rendering its documented failure modes
    as a three-part (what/why/how) startup error on stderr instead of an
    uncaught traceback (`INTERFACE_DESIGN.md §1.6`'s error shape). The
    mapping from exception to message lives in
    `data.bootstrap.describe_startup_error` -- shared with
    `cli/main.py::_cmd_serve` -- not re-derived here."""
    try:
        return build_provider_from_env()
    except (LocalDataDirError, InvalidRefreshIntervalError, InvalidCvDataError) as exc:
        _exit_with_startup_error(describe_startup_error(exc))


def _exit_with_startup_error(error: StartupError) -> NoReturn:
    print(f"cv-forge-mcp: {error.what}.", file=sys.stderr)
    print(f"     {error.why}", file=sys.stderr)
    print(f"     To fix:  {error.how}", file=sys.stderr)
    sys.exit(error.exit_code)


def _transport_config() -> tuple[Literal["stdio", "streamable-http"], str, int, bool]:
    transport = os.environ.get("TRANSPORT", "stdio")
    if transport == "sse":
        raise ValueError("SSE transport is deprecated! Use streamable-http instead.")
    if transport != "streamable-http":
        transport = "stdio"
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("FASTMCP_PORT", DEFAULT_PORT)))
    stateless = transport == "streamable-http"
    return cast(Literal["stdio", "streamable-http"], transport), host, port, stateless


def main() -> None:
    """Initialize and run the server with the specified transport."""
    logger.info(f"Python version: {sys.version}")
    provider = _build_provider_or_exit()
    transport, host, port, stateless = _transport_config()
    logger.info(
        f"Starting CV MCP server with {transport} transport ({host}:{port}) "
        f"and stateless_http={stateless}..."
    )
    if transport == "streamable-http":
        import uvicorn

        from cv_forge.mcp.app import create_app

        app = create_app(provider, stateless=stateless)
        uvicorn.run(app, host=host, port=port, log_level="info")
    else:
        # Only one provider ever exists in the stdio process (unlike
        # streamable-http, which can serve several `create_app()` apps),
        # so binding once for the whole run -- rather than per message --
        # is correct: `mcp.run()`'s internal tasks all start after this and
        # therefore all inherit the binding (see `server.bound_provider`).
        with bound_provider(provider):
            mcp.run(transport=transport)


if __name__ == "__main__":
    main()
