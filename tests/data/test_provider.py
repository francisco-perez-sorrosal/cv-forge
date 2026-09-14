"""Tests for CvDataProvider -- refresh-loop invariants and degradation behavior.

Derived from SYSTEMS_PLAN.md § Architecture -> Data Structures (`CvDataProvider`,
`RefreshState = Pinned | Fresh | Stale`, Invariants I2-I4, the "no lock, single
attribute rebind" concurrency note) and the behaviors the server needs from the
provider: sourcing data from the latest release, refreshing in the background
without re-fetching unchanged data, and degrading to a stale-but-serving state
rather than failing outright. Written before src/cv_forge/data/provider.py
exists -- confirm RED (ImportError) first.

Fake fetcher contract the implementer's `ReleaseFetcher` must satisfy
(`CvDataProvider.__init__(initial, fetcher, interval=900)` takes an instance of
this shape, or `None`):

    class ReleaseFetcher(Protocol):
        def fetch_manifest(self) -> ReleaseManifest | ArtifactUnavailable: ...
        def fetch_asset(self, name: str) -> bytes | ArtifactUnavailable: ...

Both methods return an `ArtifactUnavailable` value for any *anticipated* failure
(http_error, timeout, no_release, checksum_mismatch, too_large) -- consistent with
`release.py`'s "error value, not exception" design, reused here at the provider
boundary. `CvDataProvider.refresh_once()` is responsible for translating either an
`ArtifactUnavailable` return from the fetcher, or an exception raised by
`CvDataSnapshot.parse()` on malformed fetched bytes (bad YAML syntax or a schema
validation failure), into a `Failed` outcome and a `Stale` state -- no exception
escapes `refresh_once()`. `refresh_once()` returns one of the three
`RefreshOutcome` variants named in the type comment in SYSTEMS_PLAN.md:
`Unchanged | Updated | Failed`, importable from `cv_forge.data.provider` alongside
`Pinned | Fresh | Stale`.

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
from cv_forge.data.snapshot import CvDataSnapshot, ReleaseAssets

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


def _manifest(tag: str) -> ReleaseManifest:
    return ReleaseManifest.model_validate(
        {
            "schema_version": 1,
            "tag": tag,
            "published_at": "2026-09-13T10:04:11Z",
            "cv_forge_version": "1.0.0",
            "assets": {
                "resume.yaml": {"size": len(RESUME_YAML), "sha256": "a" * 64},
                "resume-semantics.yaml": {
                    "size": len(SEMANTICS_YAML),
                    "sha256": "b" * 64,
                },
            },
        }
    )


def _initial_snapshot() -> CvDataSnapshot:
    origin = ReleaseAssets(tag=INITIAL_TAG, published_at=datetime.now(UTC))
    return CvDataSnapshot.parse(RESUME_YAML, SEMANTICS_YAML, origin)


@dataclass
class FakeReleaseFetcher:
    """No-network fake satisfying the `ReleaseFetcher` contract documented above."""

    manifest_responses: list[ReleaseManifest | ArtifactUnavailable]
    asset_responses: dict[str, bytes | ArtifactUnavailable]
    manifest_call_count: int = field(default=0, init=False)
    asset_fetch_log: list[str] = field(default_factory=list, init=False)

    def fetch_manifest(self) -> ReleaseManifest | ArtifactUnavailable:
        index = min(self.manifest_call_count, len(self.manifest_responses) - 1)
        response = self.manifest_responses[index]
        self.manifest_call_count += 1
        return response

    def fetch_asset(self, name: str) -> bytes | ArtifactUnavailable:
        self.asset_fetch_log.append(name)
        return self.asset_responses[name]


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


# --- Degradation, never failure: a bad or unreachable release must not crash the loop ---


class TestRefreshDegradation:
    def test_malformed_yaml_leaves_snapshot_identity_unchanged_and_marks_stale(self):
        initial = _initial_snapshot()
        fetcher = FakeReleaseFetcher(
            manifest_responses=[_manifest(NEW_TAG)],
            asset_responses={
                "resume.yaml": b"{unterminated: [1,2",
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

    def test_consecutive_failures_increments_across_repeated_failures(self):
        fetcher = FakeReleaseFetcher(
            manifest_responses=[_manifest(NEW_TAG)],
            asset_responses={
                "resume.yaml": b"{unterminated: [1,2",
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
