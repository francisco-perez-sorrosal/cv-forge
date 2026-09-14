"""Behavioral tests for `GET /healthz` -- the discriminated honest-health-surface
contract, derived from `INTERFACE_DESIGN.md §3.2` (fresh/stale/pinned bodies) and
the "honest health surface" requirement in `SYSTEMS_PLAN.md`'s behavioral spec.

Written before `src/cv_forge/mcp/app.py` exists -- confirm RED
(`ModuleNotFoundError`) first, per the BDD/TDD execution contract for this
parallel group. Do NOT read `src/cv_forge/mcp/app.py` before it exists; tests are
derived from the interface contract, not from the implementation.

App factory contract fixed here for the ASGI-lifespan implementation to satisfy:

    def create_app(
        provider: CvDataProvider, *, stateless: bool = True
    ) -> <Starlette ASGI app>

`create_app` takes an already-constructed `CvDataProvider` -- it must NOT build
its own -- so tests can drive `refresh_state` transitions with a fake, no-network
fetcher satisfying the `ReleaseFetcher` Protocol (now async, per the light-review
amendment to that contract): `async def fetch_manifest() -> ReleaseManifest |
ArtifactUnavailable` / `async def fetch_asset(name) -> bytes | ArtifactUnavailable`.
This also means `provider`
is a required parameter -- calling the factory with no provider at all must fail
before any snapshot could ever be missing, which is the basis for the
503-unreachability test below (Invariant I2: a `CvDataProvider` can never exist
without a validated snapshot).

The app must serve `GET /healthz` and the MCP endpoint at `POST /mcp`, matching
the path `IMPLEMENTATION_PLAN.md`'s M3.3 live-poke curl already assumes.

Two testability contracts fixed by scratch-verifying the installed `mcp==2.2.0` +
`httpx2==2.12.0` + `starlette==0.48.0` stack in this environment (`httpx` itself is
not installed -- `starlette.testclient.TestClient` cannot be used here):

1. **ASGI lifespan must actually run.** `MCPServer.streamable_http_app()`'s
   session-manager task group only initializes inside the ASGI app's own
   `lifespan` context manager (`RuntimeError: Task group is not initialized.
   Make sure to use run()` otherwise) -- exactly the lifespan `create_app`'s
   `Implementation` note describes ("startup load, refresh task, /healthz
   route"). No `asgi_lifespan` dependency exists in this project; tests drive
   the ASGI lifespan protocol by hand via `_run_asgi_lifespan` below.
2. **DNS-rebinding host-header protection must not reject the in-process test
   host.** The SDK's `TransportSecuritySettings` defaults to
   `enable_dns_rebinding_protection=True` with an empty `allowed_hosts`, which
   rejects `httpx2.ASGITransport`'s synthetic `Host: testserver` header with a
   generic `-32603` error that has nothing to do with the behavior under test.
   `create_app` is expected to disable this (Wasmer Edge terminates/validates
   the public hostname in front of the app; the internal ASGI hop does not need
   a second check) -- if that assumption is wrong, this file's tests will need
   `allowed_hosts=["testserver"]` added at the factory boundary instead.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

import anyio
import httpx2
import pytest
import yaml
from cv_forge.mcp.app import create_app

from cv_forge.data.local import load_local_dir
from cv_forge.data.provider import CvDataProvider
from cv_forge.data.release import ArtifactUnavailable, ReleaseManifest
from cv_forge.data.snapshot import CvDataSnapshot, ReleaseAssets

RESUME_YAML = yaml.dump(
    {"personal_info": {"name": "Healthz Test"}, "institutions": [], "work": []}
).encode()

TAG = "2026.09.13"


@dataclass
class FakeReleaseFetcher:
    """No-network fake satisfying the `ReleaseFetcher` contract `CvDataProvider`
    expects (same shape `tests/data/test_provider.py` fixes)."""

    manifest_responses: list[ReleaseManifest | ArtifactUnavailable]
    asset_responses: dict[str, bytes | ArtifactUnavailable] = field(
        default_factory=dict
    )
    manifest_call_count: int = field(default=0, init=False)

    async def fetch_manifest(self) -> ReleaseManifest | ArtifactUnavailable:
        index = min(self.manifest_call_count, len(self.manifest_responses) - 1)
        response = self.manifest_responses[index]
        self.manifest_call_count += 1
        return response

    async def fetch_asset(self, name: str) -> bytes | ArtifactUnavailable:
        return self.asset_responses[name]


def _manifest(tag: str) -> ReleaseManifest:
    return ReleaseManifest.model_validate(
        {
            "schema_version": 1,
            "tag": tag,
            "published_at": "2026-09-13T10:04:11Z",
            "cv_forge_version": "1.0.0",
            "assets": {},
        }
    )


def _release_snapshot(tag: str = TAG) -> CvDataSnapshot:
    origin = ReleaseAssets(tag=tag, published_at=datetime.now(UTC))
    return CvDataSnapshot.parse(RESUME_YAML, None, origin)


def _unavailable(reason: str = "http_error") -> ArtifactUnavailable:
    return ArtifactUnavailable(
        name="release.json",
        tag=None,
        download_url="https://github.com/francisco-perez-sorrosal/cv/releases/latest",
        reason=reason,
    )


@asynccontextmanager
async def _run_asgi_lifespan(app):
    """Hand-rolled ASGI lifespan driver (no `asgi_lifespan` dependency available).

    Sends `lifespan.startup`, waits for `lifespan.startup.complete`, yields, then
    signals `lifespan.shutdown` on exit -- the minimum a real ASGI server
    (uvicorn, Wasmer Edge) does before routing any request to the app.
    """
    startup_seen = anyio.Event()
    shutdown_requested = anyio.Event()
    started = anyio.Event()
    failures: list[Exception] = []

    async def receive():
        if not startup_seen.is_set():
            startup_seen.set()
            return {"type": "lifespan.startup"}
        await shutdown_requested.wait()
        return {"type": "lifespan.shutdown"}

    async def send(message):
        if message["type"] == "lifespan.startup.complete":
            started.set()
        elif message["type"] == "lifespan.startup.failed":
            failures.append(RuntimeError(message.get("message", "startup failed")))
            started.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(app, {"type": "lifespan"}, receive, send)
        await started.wait()
        if failures:
            raise failures[0]
        try:
            yield
        finally:
            shutdown_requested.set()


async def _get_healthz(app) -> httpx2.Response:
    async with _run_asgi_lifespan(app):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get("/healthz")


class TestFreshAndStaleRefreshStates:
    def test_fresh_snapshot_reports_200_with_zero_failures_and_no_last_error(self):
        fetcher = FakeReleaseFetcher(manifest_responses=[_manifest(TAG)])
        provider = CvDataProvider(initial=_release_snapshot(TAG), fetcher=fetcher)
        asyncio.run(provider.refresh_once())  # unchanged tag -> Fresh

        app = create_app(provider)
        response = asyncio.run(_get_healthz(app))

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["refresh_state"] == "fresh"
        assert body["consecutive_failures"] == 0
        assert "last_error" not in body
        assert body["release_tag"] == TAG

    def test_degraded_refresh_reports_200_stale_with_last_error_and_failure_count(
        self,
    ):
        fetcher = FakeReleaseFetcher(manifest_responses=[_unavailable("timeout")])
        provider = CvDataProvider(initial=_release_snapshot(TAG), fetcher=fetcher)
        asyncio.run(provider.refresh_once())  # manifest fetch fails -> Stale

        app = create_app(provider)
        response = asyncio.run(_get_healthz(app))

        # A degraded refresh loop keeps serving the last-good snapshot -- 200, never 5xx.
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["refresh_state"] == "stale"
        assert body["consecutive_failures"] > 0
        assert body["last_error"]


class TestPinnedRefreshState:
    def test_local_dir_snapshot_with_no_fetcher_reports_200_pinned_without_failure_fields(
        self, tmp_path
    ):
        (tmp_path / "resume.yaml").write_bytes(RESUME_YAML)
        provider = CvDataProvider(initial=load_local_dir(tmp_path), fetcher=None)

        app = create_app(provider)
        response = asyncio.run(_get_healthz(app))

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["refresh_state"] == "pinned"
        assert body["origin"]["kind"] == "local_dir"
        # §3.2: "pinned" permits neither last_error nor consecutive_failures > 0 --
        # asserted here as key-absence, the strictest reading of "permits neither".
        assert "last_error" not in body
        assert "consecutive_failures" not in body


class TestNoValidatedSnapshotIsUnreachableInProcess:
    def test_app_factory_requires_a_provider_because_a_provider_always_has_data(self):
        """503 `no_validated_snapshot` is documented as reachable only before the
        real ASGI lifespan completes, or if a baked snapshot fails to parse
        (`INTERFACE_DESIGN.md §3.2`). Neither is constructible through
        `create_app(provider, ...)`: Invariant I2 (`SYSTEMS_PLAN.md`) makes a
        `CvDataProvider` without a validated snapshot unrepresentable, and the
        factory's `provider` parameter is required, not optional -- so there is
        no synchronous call shape that reaches this branch. This test pins that
        boundary rather than inventing a state the type system already forbids;
        the 503 path is exercised only by a live probe (M3.3) against the real
        pre-lifespan window, which no in-process unit test can reach.
        """
        with pytest.raises(TypeError):
            create_app()
