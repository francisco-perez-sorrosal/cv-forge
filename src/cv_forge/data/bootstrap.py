"""Environment-driven `CvDataProvider` construction, shared by every driver.

The repo-root Edge entrypoint (`main.py`) and the `cv-forge serve` CLI
subcommand (`cli/main.py::_cmd_serve`, stdio and streamable-http both) need
to answer the same question -- "which snapshot, which fetcher, what refresh
interval" -- from the same handful of environment variables. Lifting that
precedence rule here once, as public API, keeps it from drifting into two
silently-different copies behind private functions in each driver: `data/`
owns paths and the network, `mcp/` (the ASGI app itself) and `cli/` are the
drivers that consume this module rather than re-implementing it.

Raises `LocalDataDirError`, `InvalidRefreshIntervalError` or
`InvalidCvDataError` on a misconfigured environment; this module never
prints or exits -- that is each driver's own concern (a CLI's exit code
table is not this module's to pick). `describe_startup_error()` maps any of
the three onto the ready-to-render `INTERFACE_DESIGN.md §1.6` message once,
here, so every driver renders identical text for identical failures instead
of each re-deriving it from the raw exception -- in particular,
`pydantic.ValidationError` is a `ValueError` subclass, so a caller that
still did `except ValueError` around this module's return value would
misreport a malformed `resume.yaml` as a bad `CV_REFRESH_INTERVAL`; the two
are now distinct exception types.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

import yaml
from pydantic import ValidationError

from cv_forge.data.local import LocalDataDirError, load_local_dir
from cv_forge.data.provider import CvDataProvider
from cv_forge.data.release import DEFAULT_CV_REPO, GitHubReleaseFetcher
from cv_forge.data.snapshot import BakedSnapshot, CvDataSnapshot

DEFAULT_REFRESH_INTERVAL_SECONDS = 900.0

# Fallback bind port for the `streamable-http`/`http` transport when neither
# `PORT` nor `FASTMCP_PORT` is set -- shared by `cli/main.py::_cmd_serve` and
# the repo-root Edge entrypoint's `__main__` guard so both agree on the same
# default without importing from each other.
DEFAULT_PORT = 10000


class InvalidRefreshIntervalError(ValueError):
    """`CV_REFRESH_INTERVAL` is set but not parseable as a number of seconds."""


class InvalidCvDataError(Exception):
    """The resolved data directory's `resume.yaml`/`resume-semantics.yaml`
    failed to parse (`yaml.YAMLError`) or validate (`pydantic.ValidationError`).

    `why` is pre-formatted (file path + first error location) so callers
    render it verbatim rather than re-inspecting `__cause__`.
    """

    def __init__(self, path: Path, why: str) -> None:
        super().__init__(why)
        self.path = path
        self.why = why


@dataclass(frozen=True, slots=True)
class StartupError:
    """A ready-to-print `INTERFACE_DESIGN.md §1.6` three-part message plus
    its `§1.3` exit code."""

    what: str
    why: str
    how: str
    exit_code: int


def describe_startup_error(exc: Exception) -> StartupError:
    """Map a `build_provider_from_env()` failure onto its startup message.

    An exception type this function does not recognize is a bug at the call
    site (catching something `build_provider_from_env()` cannot raise), not
    a case to silently default -- it re-raises rather than guessing.
    """
    if isinstance(exc, LocalDataDirError):
        return StartupError(
            what="no CV data directory found",
            why=str(exc),
            how=(
                "export CV_DATA_DIR=/path/to/cv-data\n"
                "       or:    export CV_BAKED_DIR=/path/to/baked\n"
                f"       or:    place resume.yaml in {repo_root() / 'cv-data'}"
            ),
            exit_code=1,
        )
    if isinstance(exc, InvalidRefreshIntervalError):
        return StartupError(
            what="invalid CV_REFRESH_INTERVAL",
            why=str(exc),
            how=(
                "set CV_REFRESH_INTERVAL to a number of seconds, e.g. "
                f"CV_REFRESH_INTERVAL={DEFAULT_REFRESH_INTERVAL_SECONDS:.0f}"
            ),
            exit_code=1,
        )
    if isinstance(exc, InvalidCvDataError):
        return StartupError(
            what=f"{exc.path} is not valid",
            why=exc.why,
            how=f"edit the fields above, then  cv-forge validate --data-dir {exc.path}",
            exit_code=3,
        )
    raise TypeError(f"no startup-error mapping for {type(exc).__name__}") from exc


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


def load_snapshot_or_raise(path: Path) -> CvDataSnapshot:
    """`load_local_dir`, wrapping its two parse-time failure modes into
    `InvalidCvDataError` so a malformed `resume.yaml`/`resume-semantics.yaml`
    is distinguishable from `LocalDataDirError` (missing file) and from
    `InvalidRefreshIntervalError` (unrelated env var) at the call site.
    Public: `cli/main.py::build_serve_app`'s `--data-dir` branch loads a
    directory directly (no env var involved) and needs the same wrapping."""
    try:
        return load_local_dir(path)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(part) for part in first["loc"]) or "<root>"
        why = f"{path}: {loc} -- {first['msg']} ({exc.error_count()} error(s) total)"
        raise InvalidCvDataError(path, why) from exc
    except yaml.YAMLError as exc:
        raise InvalidCvDataError(path, f"{path}: {exc}") from exc


def initial_snapshot_from_env() -> CvDataSnapshot:
    """`CV_DATA_DIR` wins when set (pinned/offline mode); otherwise load the
    baked snapshot as the origin the refresh loop promotes to a real release
    on its first successful poll (`CvDataProvider._initial_state`)."""
    data_dir_env = os.environ.get("CV_DATA_DIR")
    if data_dir_env:
        return load_snapshot_or_raise(Path(data_dir_env))
    snapshot = load_snapshot_or_raise(baked_snapshot_dir())
    return replace(
        snapshot, origin=BakedSnapshot(staged_at=snapshot.loaded_at, tag=None)
    )


def build_provider_from_env() -> CvDataProvider:
    """Construct the one `CvDataProvider` a process needs, entirely from
    environment variables.

    Raises `LocalDataDirError` when no data directory resolves,
    `InvalidRefreshIntervalError` when `CV_REFRESH_INTERVAL` is not a
    number, or `InvalidCvDataError` when the resolved data fails to parse
    or validate -- all three left for the caller to render via
    `describe_startup_error()`.
    """
    fetcher = None
    if not os.environ.get("CV_DATA_DIR"):
        repo = os.environ.get("CV_RELEASE_REPO", DEFAULT_CV_REPO)
        fetcher = GitHubReleaseFetcher(repo=repo)
    interval_raw = os.environ.get(
        "CV_REFRESH_INTERVAL", DEFAULT_REFRESH_INTERVAL_SECONDS
    )
    try:
        interval = float(interval_raw)
    except ValueError as exc:
        raise InvalidRefreshIntervalError(str(exc)) from exc
    return CvDataProvider(
        initial=initial_snapshot_from_env(), fetcher=fetcher, interval=interval
    )
