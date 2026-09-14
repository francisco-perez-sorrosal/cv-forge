"""Entry point for the CV MCP server.

Builds a `CvDataProvider` from the environment exactly once, then serves it
through the same `create_app()` factory the Edge entrypoint (repo-root
`main.py`, added in a later step) uses -- local
`pixi run mcps --transport streamable-http` and the deployed Wasmer app
answer identically because both are the same ASGI app, built the same way,
with the same `stateless_http` setting. Tool/resource registration is a
side effect of importing `cv_forge.mcp.server` (see that module's
`_register_modules`), not of importing this one.
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Literal, cast

from loguru import logger

from cv_forge.data.local import load_local_dir
from cv_forge.data.provider import CvDataProvider
from cv_forge.data.release import DEFAULT_CV_REPO, GitHubReleaseFetcher
from cv_forge.data.snapshot import BakedSnapshot, CvDataSnapshot
from cv_forge.mcp.server import mcp, set_provider

DEFAULT_REFRESH_INTERVAL_SECONDS = 900.0
DEFAULT_PORT = 10000


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _baked_snapshot_dir() -> Path:
    """The deploy-time-staged data directory, or a local fallback.

    `scripts/deploy.sh` materializes `baked/` into the Edge image; a local
    checkout that never ran that script has no `baked/`, so this worktree's
    own `cv-data/` stands in -- local runs work without the deploy step.
    """
    baked = Path(os.environ.get("CV_BAKED_DIR", str(_repo_root() / "baked")))
    return baked if baked.is_dir() else _repo_root() / "cv-data"


def _initial_snapshot() -> CvDataSnapshot:
    """`CV_DATA_DIR` wins when set (pinned/offline mode); otherwise
    load the baked snapshot as the origin the refresh loop promotes to a real
    release on its first successful poll (`CvDataProvider._initial_state`)."""
    data_dir_env = os.environ.get("CV_DATA_DIR")
    if data_dir_env:
        return load_local_dir(Path(data_dir_env))
    snapshot = load_local_dir(_baked_snapshot_dir())
    return replace(
        snapshot, origin=BakedSnapshot(staged_at=snapshot.loaded_at, tag=None)
    )


def _build_provider() -> CvDataProvider:
    fetcher = None
    if not os.environ.get("CV_DATA_DIR"):
        repo = os.environ.get("CV_RELEASE_REPO", DEFAULT_CV_REPO)
        fetcher = GitHubReleaseFetcher(repo=repo)
    interval = float(
        os.environ.get("CV_REFRESH_INTERVAL", DEFAULT_REFRESH_INTERVAL_SECONDS)
    )
    return CvDataProvider(
        initial=_initial_snapshot(), fetcher=fetcher, interval=interval
    )


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
    provider = _build_provider()
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
        set_provider(provider)
        mcp.run(transport=transport)


if __name__ == "__main__":
    main()
