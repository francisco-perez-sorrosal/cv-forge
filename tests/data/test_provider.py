"""Tests for CvDataProvider -- refresh-loop invariants and degradation behavior.

Derived from SYSTEMS_PLAN.md § Architecture -> Data Structures (`CvDataProvider`,
`RefreshState = Pinned | Fresh | Stale`, Invariants I2-I4, the "no lock, single
attribute rebind" concurrency note) and the behaviors the server needs from the
provider: sourcing data from the latest release, refreshing in the background
without re-fetching unchanged data, and degrading to a stale-but-serving state
rather than failing outright. Revised after a pair-review of the initial GREEN
pass tightened the fetcher contract, asset verification, and the pre-first-refresh
state -- see the module docstring and `_fetch_verified` in `provider.py`.

Fake fetcher contract the implementer's `ReleaseFetcher` must satisfy
(`CvDataProvider.__init__(initial, fetcher, interval=900, max_asset_bytes=...)`
takes an instance of this shape, or `None`):

    class ReleaseFetcher(Protocol):
        async def fetch_manifest(self) -> ReleaseManifest | ArtifactUnavailable: ...
        async def fetch_asset(self, name: str) -> bytes | ArtifactUnavailable: ...

Both methods are coroutines and return an `ArtifactUnavailable` value for any
*anticipated* failure (http_error, timeout, no_release) -- consistent with
`release.py`'s "error value, not exception" design, reused here at the provider
boundary. `fetch_asset` returns raw bytes only; the provider verifies them
against the manifest's declared `size`/`sha256` itself (`_fetch_verified`),
since only the provider holds the manifest. `CvDataProvider.refresh_once()` is
responsible for translating an `ArtifactUnavailable` return, a verification
failure, an exception raised by `CvDataSnapshot.parse()` on malformed fetched
bytes, or any other unexpected exception a fetcher raises, into a `Failed`
outcome and a `Stale` state -- no exception escapes `refresh_once()` except
`asyncio.CancelledError` (a `BaseException`, deliberately left to propagate).
`refresh_once()` returns one of the three `RefreshOutcome` variants named in
the type comment in SYSTEMS_PLAN.md: `Unchanged | Updated | Failed`, importable
from `cv_forge.data.provider` alongside `Pinned | Fresh | Stale`.

Async note: `refresh_once`/`run_refresh_loop` are coroutines per the architecture's
type signatures. `pytest-asyncio`/`anyio`'s pytest plugin are not configured in this
project's dev environment (no `[tool.pytest.ini_options]` asyncio/anyio settings, no
`pytest-asyncio` dependency) -- rather than add one for this single step, these tests
drive the coroutines directly via `asyncio.run()` from plain synchronous test
functions. `anyio` itself (already a transitive dependency) is used only for the
`stop: anyio.Event` parameter `run_refresh_loop` declares.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

import anyio
import yaml

from cv_forge.data.provider import (
    CvDataProvider,
    Failed,
    Fresh,
    Pinned,
    Stale,
    Unchanged,
    Updated,
)
from cv_forge.data.release import ArtifactUnavailable, ReleaseManifest
from cv_forge.data.snapshot import BakedSnapshot, CvDataSnapshot, ReleaseAssets

RESUME_YAML = yaml.dump(
    {
        "personal_info": {"name": "Provider Test"},
        "institutions": [],
        "work": [],
    }
).encode()

SEMANTICS_YAML = yaml.dump(
    {
        "version": "1.0.0",
        "taxonomy": {"topics": []},
        "annotations": [],
    }
).encode()

INITIAL_TAG = "2026.09.01"
NEW_TAG = "2026.09.13"


def _asset_entry(data: bytes) -> dict:
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _manifest(
    tag: str,
    *,
    resume: bytes = RESUME_YAML,
    semantics: bytes | None = SEMANTICS_YAML,
) -> ReleaseManifest:
    """Build a manifest whose asset entries checksum-match the bytes a test
    intends to serve. `semantics=None` omits the asset from `assets` entirely
    rather than describing an asset that is never fetched.
    """
    assets = {"resume.yaml": _asset_entry(resume)}
    if semantics is not None:
        assets["resume-semantics.yaml"] = _asset_entry(semantics)
    return ReleaseManifest.model_validate(
        {
            "schema_version": 1,
            "tag": tag,
            "published_at": "2026-09-13T10:04:11Z",
            "cv_forge_version": "1.0.0",
            "assets": assets,
        }
    )


def _initial_snapshot(
    origin: ReleaseAssets | BakedSnapshot | None = None,
) -> CvDataSnapshot:
    origin = origin or ReleaseAssets(tag=INITIAL_TAG, published_at=datetime.now(UTC))
    return CvDataSnapshot.parse(RESUME_YAML, SEMANTICS_YAML, origin)


@dataclass
class FakeReleaseFetcher:
    """No-network fake satisfying the `ReleaseFetcher` contract documented above."""

    manifest_responses: list[ReleaseManifest | ArtifactUnavailable]
    asset_responses: dict[str, bytes | ArtifactUnavailable]
    manifest_call_count: int = field(default=0, init=False)
    asset_fetch_log: list[str] = field(default_factory=list, init=False)

    async def fetch_manifest(self) -> ReleaseManifest | ArtifactUnavailable:
        index = min(self.manifest_call_count, len(self.manifest_responses) - 1)
        response = self.manifest_responses[index]
        self.manifest_call_count += 1
        return response

    async def fetch_asset(self, name: str) -> bytes | ArtifactUnavailable:
        self.asset_fetch_log.append(name)
        return self.asset_responses[name]


@dataclass
class RaisingReleaseFetcher:
    """Simulates an unwrapped bug in a concrete fetcher -- e.g. an
    `httpx` exception path the implementation forgot to translate into
    `ArtifactUnavailable`. Must not escape `refresh_once`."""

    async def fetch_manifest(self) -> ReleaseManifest | ArtifactUnavailable:
        raise RuntimeError("unwrapped connection error")

    async def fetch_asset(self, name: str) -> bytes | ArtifactUnavailable:
        raise AssertionError("must not be reached -- manifest fetch fails first")


def _unavailable(reason: str = "http_error") -> ArtifactUnavailable:
    return ArtifactUnavailable(
        name="release.json",
        tag=None,
        download_url="https://github.com/francisco-perez-sorrosal/cv/releases/latest",
        reason=reason,
    )


# --- Invariant I4: Pinned iff fetcher is None ---


class TestPinnedInvariant:
    def test_state_is_pinned_iff_fetcher_is_none(self):
        pinned = CvDataProvider(initial=_initial_snapshot(), fetcher=None)
        assert isinstance(pinned.state, Pinned)

        fetcher = FakeReleaseFetcher(
            manifest_responses=[_manifest(INITIAL_TAG)], asset_responses={}
        )
        not_pinned = CvDataProvider(initial=_initial_snapshot(), fetcher=fetcher)
        assert not isinstance(not_pinned.state, Pinned)

    def test_run_refresh_loop_returns_immediately_when_pinned(self):
        # fetcher=None means there is no network path to call -- if the loop
        # incorrectly tried to use it anyway, this would raise AttributeError
        # rather than time out, and either way the test fails for a legible reason.
        provider = CvDataProvider(initial=_initial_snapshot(), fetcher=None)
        stop = anyio.Event()

        async def _run():
            await asyncio.wait_for(provider.run_refresh_loop(stop), timeout=0.5)

        asyncio.run(_run())  # raises asyncio.TimeoutError if it never returns


# --- Honest pre-first-refresh state ---


class TestInitialState:
    def test_fetcher_backed_provider_starting_from_a_release_is_fresh(self):
        fetcher = FakeReleaseFetcher(
            manifest_responses=[_manifest(INITIAL_TAG)], asset_responses={}
        )
        provider = CvDataProvider(initial=_initial_snapshot(), fetcher=fetcher)
        assert isinstance(provider.state, Fresh)

    def test_fetcher_backed_provider_starting_from_a_baked_snapshot_is_stale(self):
        baked = BakedSnapshot(staged_at=datetime.now(UTC), tag=INITIAL_TAG)
        fetcher = FakeReleaseFetcher(
            manifest_responses=[_manifest(INITIAL_TAG)], asset_responses={}
        )
        provider = CvDataProvider(initial=_initial_snapshot(baked), fetcher=fetcher)

        # Must not fabricate a success: no refresh has run yet.
        assert isinstance(provider.state, Stale)
        assert provider.state.last_error
        assert provider.state.consecutive_failures == 0
        assert provider.state.last_success_at is None


# --- Degradation, never failure: a bad or unreachable release must not crash the loop ---


class TestRefreshDegradation:
    def test_malformed_yaml_leaves_snapshot_identity_unchanged_and_marks_stale(self):
        initial = _initial_snapshot()
        malformed = b"{unterminated: [1,2"
        fetcher = FakeReleaseFetcher(
            manifest_responses=[_manifest(NEW_TAG, resume=malformed)],
            asset_responses={
                "resume.yaml": malformed,
                "resume-semantics.yaml": SEMANTICS_YAML,
            },
        )
        provider = CvDataProvider(initial=initial, fetcher=fetcher)

        outcome = asyncio.run(provider.refresh_once())

        assert isinstance(outcome, Failed)
        assert provider.snapshot is initial
        assert isinstance(provider.state, Stale)
        assert provider.state.last_error
        assert provider.state.consecutive_failures == 1

    def test_malformed_yaml_after_tag_change_keeps_old_tag_and_origin(self):
        """A bug advancing current_tag before parse would pass the
        test above but fail this one: the release that failed to parse must
        not become the reported tag, or the good release is never retried."""
        initial = _initial_snapshot()
        malformed = b"{unterminated: [1,2"
        fetcher = FakeReleaseFetcher(
            manifest_responses=[_manifest(NEW_TAG, resume=malformed)],
            asset_responses={
                "resume.yaml": malformed,
                "resume-semantics.yaml": SEMANTICS_YAML,
            },
        )
        provider = CvDataProvider(initial=initial, fetcher=fetcher)

        asyncio.run(provider.refresh_once())

        assert provider.current_tag == INITIAL_TAG
        assert isinstance(provider.snapshot.origin, ReleaseAssets)
        assert provider.snapshot.origin.tag == INITIAL_TAG

    def test_consecutive_failures_increments_across_repeated_failures(self):
        malformed = b"{unterminated: [1,2"
        fetcher = FakeReleaseFetcher(
            manifest_responses=[_manifest(NEW_TAG, resume=malformed)],
            asset_responses={
                "resume.yaml": malformed,
                "resume-semantics.yaml": SEMANTICS_YAML,
            },
        )
        provider = CvDataProvider(initial=_initial_snapshot(), fetcher=fetcher)

        asyncio.run(provider.refresh_once())
        asyncio.run(provider.refresh_once())

        assert isinstance(provider.state, Stale)
        assert provider.state.consecutive_failures == 2

    def test_manifest_fetch_failure_is_a_failed_outcome_not_an_exception(self):
        initial = _initial_snapshot()
        fetcher = FakeReleaseFetcher(
            manifest_responses=[_unavailable(reason="timeout")],
            asset_responses={},
        )
        provider = CvDataProvider(initial=initial, fetcher=fetcher)

        outcome = asyncio.run(provider.refresh_once())  # must not raise

        assert isinstance(outcome, Failed)
        assert provider.snapshot is initial
        assert isinstance(provider.state, Stale)
        assert fetcher.asset_fetch_log == []  # never got past the failed manifest

    def test_unexpected_fetcher_exception_becomes_failed_not_a_crash(self):
        """A bug in a concrete fetcher (not an anticipated
        ArtifactUnavailable) must still degrade to Stale, never escape."""
        initial = _initial_snapshot()
        provider = CvDataProvider(initial=initial, fetcher=RaisingReleaseFetcher())

        outcome = asyncio.run(provider.refresh_once())  # must not raise

        assert isinstance(outcome, Failed)
        assert provider.snapshot is initial
        assert isinstance(provider.state, Stale)
        assert provider.state.last_error


# --- Fetched assets are verified against the manifest, not trusted blindly ---


class TestAssetVerification:
    def test_oversized_asset_fails_with_too_large(self):
        oversized = RESUME_YAML + b"x" * 100
        manifest = _manifest(NEW_TAG)  # entry.size reflects the *intended* body
        fetcher = FakeReleaseFetcher(
            manifest_responses=[manifest],
            asset_responses={
                "resume.yaml": oversized,  # served body exceeds the entry's size
                "resume-semantics.yaml": SEMANTICS_YAML,
            },
        )
        provider = CvDataProvider(initial=_initial_snapshot(), fetcher=fetcher)

        outcome = asyncio.run(provider.refresh_once())

        assert isinstance(outcome, Failed)
        assert "too_large" in outcome.reason

    def test_checksum_mismatch_fails_with_checksum_mismatch(self):
        manifest = _manifest(NEW_TAG)  # checksums recorded for RESUME_YAML
        corrupted = RESUME_YAML.replace(
            b"Provider", b"Provided"
        )  # same length (8 bytes)
        fetcher = FakeReleaseFetcher(
            manifest_responses=[manifest],
            asset_responses={
                "resume.yaml": corrupted,  # same length, different bytes
                "resume-semantics.yaml": SEMANTICS_YAML,
            },
        )
        provider = CvDataProvider(initial=_initial_snapshot(), fetcher=fetcher)

        outcome = asyncio.run(provider.refresh_once())

        assert isinstance(outcome, Failed)
        assert "checksum_mismatch" in outcome.reason


# --- The semantics asset is optional, matching CvDataSnapshot.parse ---


class TestOptionalSemanticsAsset:
    def test_semantics_absent_from_manifest_parses_with_no_overlay(self):
        fetcher = FakeReleaseFetcher(
            manifest_responses=[_manifest(NEW_TAG, semantics=None)],
            asset_responses={"resume.yaml": RESUME_YAML},
        )
        provider = CvDataProvider(initial=_initial_snapshot(), fetcher=fetcher)

        outcome = asyncio.run(provider.refresh_once())

        assert isinstance(outcome, Updated)
        assert fetcher.asset_fetch_log == ["resume.yaml"]  # never asked for semantics

    def test_semantics_present_but_unavailable_fails(self):
        fetcher = FakeReleaseFetcher(
            manifest_responses=[_manifest(NEW_TAG)],
            asset_responses={
                "resume.yaml": RESUME_YAML,
                "resume-semantics.yaml": _unavailable(reason="http_error"),
            },
        )
        provider = CvDataProvider(initial=_initial_snapshot(), fetcher=fetcher)

        outcome = asyncio.run(provider.refresh_once())

        assert isinstance(outcome, Failed)


# --- Bounded background refresh: tag comparison gates the YAML asset fetch ---


class TestTagComparisonGatesAssetFetch:
    def test_unchanged_tag_performs_no_asset_fetch(self):
        fetcher = FakeReleaseFetcher(
            manifest_responses=[_manifest(INITIAL_TAG), _manifest(INITIAL_TAG)],
            asset_responses={
                "resume.yaml": RESUME_YAML,
                "resume-semantics.yaml": SEMANTICS_YAML,
            },
        )
        provider = CvDataProvider(initial=_initial_snapshot(), fetcher=fetcher)

        first = asyncio.run(provider.refresh_once())
        second = asyncio.run(provider.refresh_once())

        assert isinstance(first, Unchanged)
        assert isinstance(second, Unchanged)
        assert fetcher.asset_fetch_log == []
        assert fetcher.manifest_call_count == 2
        assert isinstance(provider.state, Fresh)
        assert provider.state.tag == INITIAL_TAG

    def test_changed_tag_triggers_full_reparse_and_atomic_swap(self):
        initial = _initial_snapshot()
        original_store = CvDataProvider(initial=initial, fetcher=None).store
        fetcher = FakeReleaseFetcher(
            manifest_responses=[_manifest(NEW_TAG)],
            asset_responses={
                "resume.yaml": RESUME_YAML,
                "resume-semantics.yaml": SEMANTICS_YAML,
            },
        )
        provider = CvDataProvider(initial=initial, fetcher=fetcher)

        outcome = asyncio.run(provider.refresh_once())

        assert isinstance(outcome, Updated)
        assert provider.snapshot is not initial
        assert isinstance(provider.snapshot.origin, ReleaseAssets)
        assert provider.snapshot.origin.tag == NEW_TAG
        assert sorted(fetcher.asset_fetch_log) == [
            "resume-semantics.yaml",
            "resume.yaml",
        ]
        assert isinstance(provider.state, Fresh)
        assert provider.state.tag == NEW_TAG
        # store must be rebound alongside snapshot, or every
        # tool/resource call site keeps serving the boot data forever.
        assert provider.store is not original_store
        assert provider.store.resume is provider.snapshot.resume


# --- A baked/local snapshot is promoted to `release` on the first success ---


class TestBakedSnapshotPromotion:
    def test_unchanged_tag_from_a_baked_origin_still_swaps_and_promotes(self):
        """The deploy skill bakes the *current latest* release. On the first
        poll the tag already matches, but origin must still become
        ReleaseAssets so a post-deploy health check reflects the live
        release rather than the bake."""
        baked = BakedSnapshot(staged_at=datetime.now(UTC), tag=INITIAL_TAG)
        initial = _initial_snapshot(baked)
        fetcher = FakeReleaseFetcher(
            manifest_responses=[_manifest(INITIAL_TAG)],  # same tag as the bake
            asset_responses={
                "resume.yaml": RESUME_YAML,
                "resume-semantics.yaml": SEMANTICS_YAML,
            },
        )
        provider = CvDataProvider(initial=initial, fetcher=fetcher)

        outcome = asyncio.run(provider.refresh_once())

        assert isinstance(outcome, Updated)
        assert isinstance(provider.snapshot.origin, ReleaseAssets)
        assert provider.snapshot.origin.tag == INITIAL_TAG
        assert fetcher.asset_fetch_log  # the promotion actually fetched assets

    def test_once_released_the_tag_gate_applies_again(self):
        baked = BakedSnapshot(staged_at=datetime.now(UTC), tag=INITIAL_TAG)
        initial = _initial_snapshot(baked)
        fetcher = FakeReleaseFetcher(
            manifest_responses=[_manifest(INITIAL_TAG), _manifest(INITIAL_TAG)],
            asset_responses={
                "resume.yaml": RESUME_YAML,
                "resume-semantics.yaml": SEMANTICS_YAML,
            },
        )
        provider = CvDataProvider(initial=initial, fetcher=fetcher)

        first = asyncio.run(provider.refresh_once())  # promotes
        second = asyncio.run(provider.refresh_once())  # now gated normally

        assert isinstance(first, Updated)
        assert isinstance(second, Unchanged)
        assert fetcher.asset_fetch_log == ["resume.yaml", "resume-semantics.yaml"]
