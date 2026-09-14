"""CvDataProvider: the one mutable thing in the data layer.

Holds the current `CvDataSnapshot` and coordinates its background refresh
against a `cv` GitHub Release. Every other component (tools, resources,
`/healthz`) reads `provider.snapshot` / `provider.store` per call; nothing
else may rebind them.

Invariant I2 -- the provider always has data. Enforcement: `initial` is a
non-optional constructor parameter. There is no `Empty`/`Loading` state, so
no caller ever null-checks `.snapshot`.

Invariant I3 -- a refresh is atomic and all-or-nothing. Enforcement:
`refresh_once` parses fetched bytes into a *new* `CvDataSnapshot` first and
only then rebinds `self._snapshot`. A validation failure or an unreachable
release leaves the previous snapshot untouched.

Invariant I4 -- `Pinned` iff `fetcher is None`. Enforcement: the initial
state is derived from the `fetcher` argument in `__init__`, and
`run_refresh_loop` returns immediately when pinned. "Local-dir mode that
nonetheless polls GitHub" is unrepresentable.

Concurrency -- the only mutation is a single attribute rebind of a frozen
value; no lock is used. A reader that captured `self._snapshot` before a
swap keeps a fully valid (if slightly stale) object; a reader after the
swap gets the new one. No half-written state is ever observable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import anyio
from loguru import logger

from cv_forge.data.local import RESUME_FILENAME, SEMANTICS_FILENAME
from cv_forge.data.release import ArtifactUnavailable, ReleaseManifest
from cv_forge.data.snapshot import CvDataSnapshot, ReleaseAssets
from cv_forge.data.store import ResumeStore

DEFAULT_REFRESH_INTERVAL_SECONDS = 900.0


class ReleaseFetcher(Protocol):
    """The network boundary `CvDataProvider` polls -- no I/O in this module.

    Both methods return an `ArtifactUnavailable` *value* for any anticipated
    failure (`http_error`, `timeout`, `no_release`, `checksum_mismatch`,
    `too_large`); they never raise for those cases. This is the seam a fake
    satisfies in tests, and the seam `cv_forge.data.release`'s httpx-based
    implementation satisfies in production.
    """

    def fetch_manifest(self) -> ReleaseManifest | ArtifactUnavailable: ...
    def fetch_asset(self, name: str) -> bytes | ArtifactUnavailable: ...


@dataclass(frozen=True, slots=True)
class Pinned:
    """`CV_DATA_DIR` is set -- refresh never runs."""

    reason: str


@dataclass(frozen=True, slots=True)
class Fresh:
    """The current snapshot matches the latest known release tag."""

    last_success_at: datetime
    tag: str | None


@dataclass(frozen=True, slots=True)
class Stale:
    """A refresh failed; the provider keeps serving the previous snapshot."""

    last_success_at: datetime | None
    last_error: str
    consecutive_failures: int


RefreshState = Pinned | Fresh | Stale


@dataclass(frozen=True, slots=True)
class Unchanged:
    """The release tag has not changed since the last refresh."""

    tag: str | None


@dataclass(frozen=True, slots=True)
class Updated:
    """A new release tag was fetched, parsed and swapped in."""

    tag: str


@dataclass(frozen=True, slots=True)
class Failed:
    """The refresh could not complete; the previous snapshot is untouched."""

    reason: str


RefreshOutcome = Unchanged | Updated | Failed


class CvDataProvider:
    """Owns the current snapshot and its refresh state; see module docstring."""

    def __init__(
        self,
        initial: CvDataSnapshot,
        fetcher: ReleaseFetcher | None,
        interval: float = DEFAULT_REFRESH_INTERVAL_SECONDS,
    ) -> None:
        self._snapshot = initial
        self._store = ResumeStore(initial.resume, initial.semantics)
        self._fetcher = fetcher
        self._interval = interval
        self._current_tag = _tag_of(initial)
        self._state: RefreshState = (
            Pinned(reason="CV_DATA_DIR set")
            if fetcher is None
            else Fresh(last_success_at=datetime.now(UTC), tag=self._current_tag)
        )

    @property
    def snapshot(self) -> CvDataSnapshot:
        return self._snapshot

    @property
    def store(self) -> ResumeStore:
        """Derived from `snapshot`, memoized per snapshot identity."""
        return self._store

    @property
    def state(self) -> RefreshState:
        return self._state

    # --- Derived, flattened accessors for /healthz (INTERFACE_DESIGN.md §3.2) ---

    @property
    def current_tag(self) -> str | None:
        return self._current_tag

    @property
    def last_success_at(self) -> datetime | None:
        if isinstance(self._state, Fresh | Stale):
            return self._state.last_success_at
        return None

    @property
    def last_error(self) -> str | None:
        return self._state.last_error if isinstance(self._state, Stale) else None

    @property
    def consecutive_failures(self) -> int:
        return self._state.consecutive_failures if isinstance(self._state, Stale) else 0

    # --- Refresh ---

    async def refresh_once(self) -> RefreshOutcome:
        """Fetch `release.json`, and the YAML assets only if the tag changed.

        Never raises: any fetcher failure or parse failure is translated
        into a `Failed` outcome and a `Stale` state, degrading freshness
        rather than availability.
        """
        if self._fetcher is None:
            return Unchanged(tag=self._current_tag)

        manifest = self._fetcher.fetch_manifest()
        if isinstance(manifest, ArtifactUnavailable):
            return self._fail(str(manifest.reason))

        if manifest.tag == self._current_tag:
            self._state = Fresh(
                last_success_at=datetime.now(UTC), tag=self._current_tag
            )
            return Unchanged(tag=self._current_tag)

        try:
            snapshot = self._fetch_and_parse(manifest)
        except Exception as exc:  # translated into Failed -- never re-raised
            return self._fail(str(exc))

        self._snapshot = snapshot  # atomic rebind (Invariant I3)
        self._store = ResumeStore(snapshot.resume, snapshot.semantics)
        self._current_tag = manifest.tag
        self._state = Fresh(last_success_at=datetime.now(UTC), tag=manifest.tag)
        return Updated(tag=manifest.tag)

    async def run_refresh_loop(self, stop: anyio.Event) -> None:
        """Refresh once per `interval` until `stop` is set. Inert when pinned."""
        if self._fetcher is None:
            return
        while not stop.is_set():
            outcome = await self.refresh_once()
            if isinstance(outcome, Failed):
                logger.warning(f"CvDataProvider refresh failed: {outcome.reason}")
            with anyio.move_on_after(self._interval):
                await stop.wait()

    def _fetch_and_parse(self, manifest: ReleaseManifest) -> CvDataSnapshot:
        resume_bytes = self._fetcher.fetch_asset(RESUME_FILENAME)
        if isinstance(resume_bytes, ArtifactUnavailable):
            raise ValueError(str(resume_bytes.reason))
        semantics_bytes = self._fetcher.fetch_asset(SEMANTICS_FILENAME)
        if isinstance(semantics_bytes, ArtifactUnavailable):
            raise ValueError(str(semantics_bytes.reason))
        origin = ReleaseAssets(tag=manifest.tag, published_at=manifest.published_at)
        return CvDataSnapshot.parse(resume_bytes, semantics_bytes, origin)

    def _fail(self, reason: str) -> Failed:
        previous_success = (
            self._state.last_success_at
            if isinstance(self._state, Fresh | Stale)
            else None
        )
        previous_failures = (
            self._state.consecutive_failures if isinstance(self._state, Stale) else 0
        )
        self._state = Stale(
            last_success_at=previous_success,
            last_error=reason,
            consecutive_failures=previous_failures + 1,
        )
        return Failed(reason=reason)


def _tag_of(snapshot: CvDataSnapshot) -> str | None:
    return getattr(snapshot.origin, "tag", None)
