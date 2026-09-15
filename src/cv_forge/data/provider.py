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

Concurrency -- `self._snapshot` is rebound first with no `await` before it;
`self._store` and `self._state` are rebound immediately after with no
`await` between any of the three lines. On a single-threaded event loop
that makes the three-way rebind observably atomic: a reader can never see
one rebound and the others stale. That guarantee is a property of *no
intervening await*, not of "one assignment" -- see the comment at the swap
site in `refresh_once` before adding one.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import anyio
from loguru import logger

from cv_forge.data.local import RESUME_FILENAME, SEMANTICS_FILENAME
from cv_forge.data.release import (
    DEFAULT_RELEASES_URL,
    PDF_ASSET_NAME,
    ArtifactUnavailable,
    AssetEntry,
    CachedArtifact,
    ReleaseManifest,
    UnavailableReason,
)
from cv_forge.data.snapshot import (
    BakedSnapshot,
    CvDataSnapshot,
    LocalDir,
    ReleaseAssets,
)
from cv_forge.data.store import ResumeStore

DEFAULT_REFRESH_INTERVAL_SECONDS = 900.0
DEFAULT_MAX_ASSET_BYTES = 8 * 1024 * 1024  # 8 MiB guard against a corrupted/huge asset


class ReleaseFetcher(Protocol):
    """The network boundary `CvDataProvider` polls -- no I/O in this module.

    Both methods return an `ArtifactUnavailable` *value* for any anticipated
    failure (`http_error`, `timeout`, `no_release`); they never raise for
    those cases. This is the seam a fake satisfies in tests, and the seam
    `cv_forge.data.release`'s httpx-based implementation satisfies in
    production. Both methods are coroutines -- the provider awaits them from
    an ASGI lifespan task, and a synchronous network call here would block
    every concurrent request for the duration of the fetch.

    `fetch_asset` returns raw bytes only; verifying them against the
    manifest's declared `size`/`sha256` is the provider's job (`_fetch_verified`),
    because only the provider holds the manifest.
    """

    async def fetch_manifest(self) -> ReleaseManifest | ArtifactUnavailable: ...
    async def fetch_asset(self, name: str) -> bytes | ArtifactUnavailable: ...


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
    """A refresh failed, or none has run yet; the provider keeps serving
    the previous snapshot."""

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
    """A new snapshot was fetched, parsed and swapped in.

    Covers both a genuine tag change and the one-time promotion of a
    baked/local snapshot to `ReleaseAssets` on the first successful poll --
    both are "a real reparse happened", just with different causes.
    """

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
        max_asset_bytes: int = DEFAULT_MAX_ASSET_BYTES,
    ) -> None:
        self._snapshot = initial
        self._store = ResumeStore(initial.resume, initial.semantics)
        self._fetcher = fetcher
        self._interval = interval
        self._max_asset_bytes = max_asset_bytes
        self._state: RefreshState = self._initial_state(initial, fetcher)
        self._pdf_cache: CachedArtifact | None = None

    @staticmethod
    def _initial_state(
        initial: CvDataSnapshot, fetcher: ReleaseFetcher | None
    ) -> RefreshState:
        """`Pinned` when there is no fetcher.

        `Fresh` only when `initial` already came from a release (a resumed
        process resuming against the same tag); otherwise a pre-first-refresh
        `Stale`. A baked or local snapshot has never actually been checked
        against the release, so claiming `Fresh` for it would report a
        staleness alarm that can never fire -- `stale` carrying an explicit
        sentinel `last_error` is honest about "not yet checked", where a
        fabricated `Fresh` would not be.
        """
        if fetcher is None:
            return Pinned(reason="CV_DATA_DIR set")
        if isinstance(initial.origin, ReleaseAssets):
            return Fresh(last_success_at=datetime.now(UTC), tag=initial.origin.tag)
        return Stale(
            last_success_at=None,
            last_error="no refresh attempted yet",
            consecutive_failures=0,
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

    # --- Derived, flattened accessors for /healthz ---

    @property
    def current_tag(self) -> str | None:
        """A pure projection of `snapshot.origin` -- never settable on its
        own."""
        return _tag_of(self._snapshot)

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
        """Fetch `release.json`, then reparse the YAML assets if warranted.

        A full reparse+swap happens when the tag changed, or when the
        current snapshot did not yet originate from a release -- this
        promotes a baked or local snapshot to `ReleaseAssets` on the first
        successful poll, so a post-deploy `/healthz` check reflects the live
        release rather than the bake, even when the bake's tag was current.

        Never raises (`asyncio.CancelledError` is a `BaseException`, not an
        `Exception`, so it is never caught by the guard below and remains a
        cancellation checkpoint): any fetcher failure, verification failure,
        or parse failure is translated into a `Failed` outcome and a `Stale`
        state, degrading freshness rather than availability.
        """
        if self._fetcher is None:
            return Unchanged(tag=self.current_tag)

        try:
            manifest = await self._fetcher.fetch_manifest()
            if isinstance(manifest, ArtifactUnavailable):
                return self._fail(
                    f"release.json: {manifest.reason}"
                    + (f" ({manifest.detail})" if manifest.detail else "")
                )

            already_released = isinstance(self._snapshot.origin, ReleaseAssets)
            if already_released and manifest.tag == self.current_tag:
                self._transition(
                    Fresh(last_success_at=datetime.now(UTC), tag=manifest.tag)
                )
                return Unchanged(tag=manifest.tag)

            snapshot = await self._fetch_and_parse(manifest)
        except Exception as exc:
            logger.exception("CvDataProvider refresh failed with an unexpected error")
            return self._fail(str(exc))

        # The atomic swap (Invariant I3) -- see the Concurrency note in the
        # module docstring: no `await` follows until `_state` is rebound too.
        self._snapshot = snapshot
        self._store = ResumeStore(snapshot.resume, snapshot.semantics)
        self._transition(Fresh(last_success_at=datetime.now(UTC), tag=manifest.tag))
        return Updated(tag=manifest.tag)

    async def run_refresh_loop(self, stop: anyio.Event) -> None:
        """Refresh once per `interval` until `stop` is set. Inert when pinned.

        `refresh_once` never raises for expected failures, so one bad cycle
        cannot end this loop; `_transition` logs the cause once, on the
        state-kind change, not once per cycle.
        """
        if self._fetcher is None:
            return
        while not stop.is_set():
            await self.refresh_once()
            with anyio.move_on_after(self._interval):
                await stop.wait()

    async def fetch_pdf(self) -> bytes | ArtifactUnavailable:
        """Lazily fetch and cache the compiled PDF against the current release
        tag.

        The PDF is never part of the parsed snapshot -- Invariant I1 only
        governs the resume/semantics YAML that `refresh_once` swaps
        atomically. A pinned provider (no fetcher) has no release to fetch
        from at all.
        """
        if self._fetcher is None:
            return ArtifactUnavailable(
                name=PDF_ASSET_NAME,
                tag=self.current_tag,
                download_url=DEFAULT_RELEASES_URL,
                reason=UnavailableReason.NO_RELEASE,
            )

        tag = self.current_tag
        if self._pdf_cache is not None and self._pdf_cache.tag == tag:
            return self._pdf_cache.body

        result = await self._fetcher.fetch_asset(PDF_ASSET_NAME)
        if isinstance(result, ArtifactUnavailable):
            # The fetcher has no notion of a release tag (it only knows the
            # asset name); the provider does, so it fills the field in
            # rather than leaving the client-visible error silent about
            # which release the failure applies to.
            return result.model_copy(update={"tag": tag})
        if len(result) > self._max_asset_bytes:
            return ArtifactUnavailable(
                name=PDF_ASSET_NAME,
                tag=tag,
                download_url=DEFAULT_RELEASES_URL,
                reason=UnavailableReason.TOO_LARGE,
            )

        # Keyed on `tag` directly (including `None`, the boot-state tag
        # before any successful refresh) rather than the coerced `tag or ""`
        # this replaced -- that coercion made `CachedArtifact.tag` a `str`
        # that could never equal the `str | None` `current_tag` it was
        # compared against, so the cache was written on every call and never
        # read back in the boot state (repeated network fetches until the
        # first successful refresh promotes a real tag).
        self._pdf_cache = CachedArtifact(
            name=PDF_ASSET_NAME,
            tag=tag,
            body=result,
            media_type="application/pdf",
        )
        return result

    async def _fetch_and_parse(self, manifest: ReleaseManifest) -> CvDataSnapshot:
        resume_entry = manifest.assets.get(RESUME_FILENAME)
        if resume_entry is None:
            raise ValueError(f"{RESUME_FILENAME}: missing from release.json assets")
        resume_bytes = await self._fetch_verified(resume_entry)

        semantics_entry = manifest.assets.get(SEMANTICS_FILENAME)
        semantics_bytes = (
            await self._fetch_verified(semantics_entry)
            if semantics_entry is not None
            else None  # optional asset, simply absent from the manifest
        )

        origin = ReleaseAssets(tag=manifest.tag, published_at=manifest.published_at)
        return CvDataSnapshot.parse(resume_bytes, semantics_bytes, origin)

    async def _fetch_verified(self, entry: AssetEntry) -> bytes:
        """Fetch one asset and verify it against its manifest entry.

        Raises `ValueError` -- caught by `refresh_once`'s guard -- naming the
        asset and the reason: the fetcher's own `ArtifactUnavailable`, a body
        exceeding the manifest's declared size (or the `max_asset_bytes`
        guard, whichever is tighter), or a `sha256` mismatch.
        """
        data = await self._fetcher.fetch_asset(entry.name)
        if isinstance(data, ArtifactUnavailable):
            raise ValueError(f"{entry.name}: {data.reason}")

        size_limit = min(entry.size, self._max_asset_bytes)
        if len(data) > size_limit:
            raise ValueError(
                f"{entry.name}: {UnavailableReason.TOO_LARGE.value} "
                f"({len(data)} bytes > {size_limit})"
            )

        digest = hashlib.sha256(data).hexdigest()
        if digest != entry.sha256:
            raise ValueError(
                f"{entry.name}: {UnavailableReason.CHECKSUM_MISMATCH.value}"
            )

        return data

    def _transition(self, new_state: RefreshState) -> None:
        """Rebind `_state`, logging only when the state's *kind* changes.

        The cause is logged once per transition, not once per cycle -- a
        multi-day outage emits one `Fresh -> Stale` line, not one `WARNING`
        every `interval`.
        """
        if type(new_state) is not type(self._state):
            log = logger.warning if isinstance(new_state, Stale) else logger.info
            log(f"CvDataProvider refresh state: {self._state} -> {new_state}")
        self._state = new_state

    def _fail(self, reason: str) -> Failed:
        previous_success = (
            self._state.last_success_at
            if isinstance(self._state, Fresh | Stale)
            else None
        )
        previous_failures = (
            self._state.consecutive_failures if isinstance(self._state, Stale) else 0
        )
        if previous_failures == 0:
            # The boot state is already Stale, so the kind-change log below
            # stays silent for the first failure; say it once here.
            logger.warning(f"CvDataProvider refresh failed: {reason}")
        self._transition(
            Stale(
                last_success_at=previous_success,
                last_error=reason,
                consecutive_failures=previous_failures + 1,
            )
        )
        return Failed(reason=reason)


def _tag_of(snapshot: CvDataSnapshot) -> str | None:
    """Exhaustive match over `DataOrigin` -- a future variant with a `tag`
    attribute must be handled explicitly here, not silently absorbed."""
    match snapshot.origin:
        case ReleaseAssets(tag=tag) | BakedSnapshot(tag=tag):
            return tag
        case LocalDir():
            return None
