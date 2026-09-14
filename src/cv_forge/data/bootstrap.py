"""Environment-driven `CvDataProvider` construction, shared by every driver.

`mcp/main.py` (stdio and streamable-http) and the `cv-forge serve` CLI
subcommand both need to answer the same question -- "which snapshot, which
fetcher, what refresh interval" -- from the same handful of environment
variables. Lifting that precedence rule here once, as public API, keeps it
from drifting into two silently-different copies behind private functions in
`mcp/main.py`: `data/` owns paths and the network, `mcp/` and `cli/` are the
two drivers that consume this module rather than re-implementing it.

Raises `LocalDataDirError` or `ValueError` on a misconfigured environment;
this module never prints or exits -- that is each driver's own concern (a
CLI's exit code table is not this module's to pick).
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from cv_forge.data.local import load_local_dir
from cv_forge.data.provider import CvDataProvider
from cv_forge.data.release import DEFAULT_CV_REPO, GitHubReleaseFetcher
from cv_forge.data.snapshot import BakedSnapshot, CvDataSnapshot

DEFAULT_REFRESH_INTERVAL_SECONDS = 900.0


def repo_root() -> Path:
    """The `cv-forge` checkout root -- three levels above this file.

    Correct for a source checkout; an installed wheel resolves into
    `site-packages/..` instead, at which point `CV_DATA_DIR`/`CV_BAKED_DIR`
    become mandatory rather than merely convenient.
    """
    return Path(__file__).resolve().parents[3]


def baked_snapshot_dir() -> Path:
    """The deploy-time-staged data directory, or a local fallback.

    `scripts/deploy.sh` materializes `baked/` into the Edge image; a local
    checkout that never ran that script has no `baked/`, so this worktree's
    own `cv-data/` stands in -- local runs work without the deploy step.
    """
    baked = Path(os.environ.get("CV_BAKED_DIR", str(repo_root() / "baked")))
    return baked if baked.is_dir() else repo_root() / "cv-data"


def initial_snapshot_from_env() -> CvDataSnapshot:
    """`CV_DATA_DIR` wins when set (pinned/offline mode); otherwise load the
    baked snapshot as the origin the refresh loop promotes to a real release
    on its first successful poll (`CvDataProvider._initial_state`)."""
    data_dir_env = os.environ.get("CV_DATA_DIR")
    if data_dir_env:
        return load_local_dir(Path(data_dir_env))
    snapshot = load_local_dir(baked_snapshot_dir())
    return replace(
        snapshot, origin=BakedSnapshot(staged_at=snapshot.loaded_at, tag=None)
    )


def build_provider_from_env() -> CvDataProvider:
    """Construct the one `CvDataProvider` a process needs, entirely from
    environment variables.

    Raises `LocalDataDirError` (`cv_forge.data.local`) when no data
    directory resolves, or `ValueError` when `CV_REFRESH_INTERVAL` is not a
    number -- both left for the caller to render as an actionable startup
    error (see `mcp/main.py::_build_provider_or_exit`).
    """
    fetcher = None
    if not os.environ.get("CV_DATA_DIR"):
        repo = os.environ.get("CV_RELEASE_REPO", DEFAULT_CV_REPO)
        fetcher = GitHubReleaseFetcher(repo=repo)
    interval = float(
        os.environ.get("CV_REFRESH_INTERVAL", DEFAULT_REFRESH_INTERVAL_SECONDS)
    )
    return CvDataProvider(
        initial=initial_snapshot_from_env(), fetcher=fetcher, interval=interval
    )
