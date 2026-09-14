"""Behavioral tests for the `ArtifactUnavailable` PDF contract and the tool
annotation/statelessness surface, derived from `INTERFACE_DESIGN.md §3.1` (tool
error + JSON-RPC error shapes) and `§3.3` (uniform `ToolAnnotations` on every
tool), plus the requirement that the ASGI factory build stateless streamable HTTP
explicitly (`stateless_http=True`), since the Edge entrypoint never calls `run()`.

Written before `src/cv_forge/mcp/app.py` exists -- confirm RED
(`ModuleNotFoundError`) first. Tests are derived from the interface contract, not
from the implementation; the app-factory and testability contracts this file
relies on are documented in `tests/mcp/test_healthz.py`'s module docstring
(ASGI-lifespan driving, DNS-rebinding-protection assumption) -- not repeated
here.

Today's behavior this replaces: `get_cv(format="pdf")` and `fps-cv://pdf` both
return a silent empty byte string (`tools/data.py:59`, `resources.py:24-28`) when
`CV_PATH` does not resolve. This is replaced by a self-contained, actionable
error naming the asset, the reason (from a closed set), and a direct download URL
-- these tests assert the client-observable shape of that replacement, not which
internal mechanism (`ToolError`, a raw `CallToolResult`, `ResourceError`, ...)
produces it.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

import anyio
import httpx2
import yaml
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

from cv_forge.data.provider import CvDataProvider
from cv_forge.data.release import ArtifactUnavailable, ReleaseManifest
from cv_forge.data.snapshot import BakedSnapshot, CvDataSnapshot, ReleaseAssets
from cv_forge.mcp.app import create_app

RESUME_YAML = yaml.dump(
    {"personal_info": {"name": "PDF Unavailable Test"}, "institutions": [], "work": []}
).encode()

TAG = "2026.09.13"
DOWNLOAD_URL = (
    "https://github.com/francisco-perez-sorrosal/cv/releases/latest/download/"
    "FranciscoPerezSorrosal_CV.pdf"
)


@dataclass
class FakeReleaseFetcher:
    """No-network fake satisfying the async `ReleaseFetcher` contract
    `CvDataProvider` expects. `fetch_asset` always reports the PDF unavailable,
    regardless of the requested name -- these tests assert the client-observable
    error contract, not which literal asset filename the implementation
    requests internally."""

    manifest_responses: list[ReleaseManifest | ArtifactUnavailable]
    unavailable_asset: ArtifactUnavailable

    async def fetch_manifest(self) -> ReleaseManifest | ArtifactUnavailable:
        return self.manifest_responses[0]

    async def fetch_asset(self, name: str) -> bytes | ArtifactUnavailable:
        return self.unavailable_asset


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


def _baked_snapshot_with_no_tag() -> CvDataSnapshot:
    """The boot-state origin `main.py::initial_snapshot_from_env` constructs
    before any successful refresh -- `tag=None`, not yet a real release."""
    origin = BakedSnapshot(staged_at=datetime.now(UTC), tag=None)
    return CvDataSnapshot.parse(RESUME_YAML, None, origin)


def _provider_with_pdf_unavailable(reason: str = "no_release") -> CvDataProvider:
    fetcher = FakeReleaseFetcher(
        manifest_responses=[_manifest(TAG)],
        unavailable_asset=ArtifactUnavailable(
            name="FranciscoPerezSorrosal_CV.pdf",
            tag=TAG,
            download_url=DOWNLOAD_URL,
            reason=reason,
        ),
    )
    return CvDataProvider(initial=_release_snapshot(TAG), fetcher=fetcher)


@asynccontextmanager
async def _run_asgi_lifespan(app):
    """Hand-rolled ASGI lifespan driver -- see `test_healthz.py` for rationale."""
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


@asynccontextmanager
async def _mcp_session(app):
    """Drive one full MCP client session against `app` over an in-process ASGI
    transport, initializing first as every real client must."""
    async with _run_asgi_lifespan(app):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            async with streamable_http_client(
                "http://testserver/mcp", http_client=client
            ) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session


def _combined_text(result) -> str:
    """Every human/model-readable and structured surface of a tool result,
    joined for substring assertions -- robust to whichever mechanism the
    implementer uses to carry the structured payload (embedded in the error
    text, `structured_content`, or both)."""
    text_parts = [
        part.text for part in result.content if getattr(part, "type", None) == "text"
    ]
    if result.structured_content:
        text_parts.append(json.dumps(result.structured_content))
    return "\n".join(text_parts)


class TestGetCvPdfUnavailable:
    def test_pdf_fetch_failure_returns_a_tool_error_naming_reason_and_download_url(
        self,
    ):
        provider = _provider_with_pdf_unavailable(reason="no_release")
        app = create_app(provider)

        async def _call():
            async with _mcp_session(app) as session:
                return await session.call_tool("get_cv", {"format": "pdf"})

        result = asyncio.run(_call())

        assert result.is_error is True
        text = _combined_text(result)
        assert "artifact_unavailable" in text
        assert "no_release" in text
        assert DOWNLOAD_URL in text

    def test_pdf_fetch_failure_names_at_least_one_alternative_tool_call(self):
        provider = _provider_with_pdf_unavailable(reason="no_release")
        app = create_app(provider)

        async def _call():
            async with _mcp_session(app) as session:
                return await session.call_tool("get_cv", {"format": "pdf"})

        result = asyncio.run(_call())

        # §3.1: "naming the alternative tool calls is the load-bearing part" --
        # a model that cannot get bytes still needs a next action.
        text = _combined_text(result)
        assert any(
            alternative in text
            for alternative in ("get_cv_pdf_link", 'format="latex"', "format='latex'")
        )


class TestPdfResourceUnavailable:
    def test_pdf_resource_read_raises_a_json_rpc_error_naming_the_download_url(self):
        provider = _provider_with_pdf_unavailable(reason="no_release")
        app = create_app(provider)

        async def _read() -> MCPError:
            # Catch inside the session: the SDK's ClientSession.__aexit__ hands a
            # propagating exception to an anyio TaskGroup, which re-raises it
            # wrapped in a BaseExceptionGroup that pytest.raises cannot unwrap.
            async with _mcp_session(app) as session:
                try:
                    await session.read_resource("fps-cv://pdf")
                except MCPError as exc:
                    return exc
            raise AssertionError("fps-cv://pdf did not raise an MCPError")

        error = asyncio.run(_read())

        assert DOWNLOAD_URL in error.message


class TestToolAnnotationsAndStatelessness:
    def test_tools_list_over_the_stateless_app_succeeds_and_every_tool_is_annotated(
        self,
    ):
        provider = _provider_with_pdf_unavailable()
        app = create_app(provider, stateless=True)

        async def _list():
            # A brand-new client/session per call, with no prior session state
            # to carry forward -- if the server required a session id to
            # correlate `initialize` with `tools/list`, this would fail here.
            async with _mcp_session(app) as session:
                return await session.list_tools()

        listed = asyncio.run(_list())

        assert len(listed.tools) == 16
        for tool in listed.tools:
            annotations = tool.annotations
            assert annotations is not None, f"{tool.name} has no annotations"
            assert annotations.read_only_hint is True
            assert annotations.idempotent_hint is True
            assert annotations.open_world_hint is False


@dataclass
class CountingAssetFetcher:
    """No-network fake that always serves a fixed PDF payload and counts how
    many times `fetch_asset` actually ran a fetch -- pins the PDF cache's hit
    rate, distinct from `FakeReleaseFetcher` above which always reports the
    asset unavailable and never needs a call counter.

    `fetch_manifest` reports the manifest itself unavailable rather than
    raising: `create_app`'s refresh loop polls `fetch_manifest` in the
    background regardless of what the test is exercising, and
    `refresh_once`'s broad exception guard would otherwise swallow a raised
    `AssertionError` into a misleading "unexpected error" log line on every
    run (`LIGHT_REVIEW_M1.8-rev.md` N5). Reporting `NO_RELEASE` fails the
    poll benignly and keeps the boot-state tag at `None` -- a *real* manifest
    would promote the snapshot mid-test and invalidate the cache-hit-rate
    assertion this fake exists to pin."""

    pdf_bytes: bytes
    fetch_count: int = field(default=0, init=False)

    async def fetch_manifest(self) -> ReleaseManifest | ArtifactUnavailable:
        return ArtifactUnavailable(
            name="release.json",
            tag=None,
            download_url=DOWNLOAD_URL,
            reason="no_release",
        )

    async def fetch_asset(self, name: str) -> bytes | ArtifactUnavailable:
        self.fetch_count += 1
        return self.pdf_bytes


class TestPdfCachingAtTheBootStateTag:
    def test_three_pdf_fetches_at_boot_tag_none_hit_the_network_once(self):
        fetcher = CountingAssetFetcher(pdf_bytes=b"%PDF-1.4 fake pdf content")
        provider = CvDataProvider(
            initial=_baked_snapshot_with_no_tag(), fetcher=fetcher
        )
        app = create_app(provider)

        async def _call_three_times() -> int:
            async with _mcp_session(app) as session:
                for _ in range(3):
                    result = await session.call_tool("get_cv", {"format": "pdf"})
                    assert result.is_error is not True
            return fetcher.fetch_count

        fetch_count = asyncio.run(_call_three_times())

        assert fetch_count == 1


class TestStatelessnessOnTheWire:
    """`test_tools_list_over_the_stateless_app_succeeds...` above drives a
    full `ClientSession`, which stores and replays the `Mcp-Session-Id`
    header `initialize()` returns -- so it succeeds in both stateless and
    stateful modes and can never observe the difference. These tests instead
    send one raw `tools/list` POST with no prior `initialize` and no session
    header at all, the only request shape that actually distinguishes them.
    """

    @staticmethod
    async def _raw_tools_list(app) -> httpx2.Response:
        async with _run_asgi_lifespan(app):
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                return await client.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers={"Accept": "application/json, text/event-stream"},
                )

    def test_stateless_app_serves_tools_list_with_no_session_id(self):
        provider = _provider_with_pdf_unavailable()
        app = create_app(provider, stateless=True)

        response = asyncio.run(self._raw_tools_list(app))

        assert response.status_code == 200

    def test_stateful_app_rejects_tools_list_with_no_session_id(self):
        provider = _provider_with_pdf_unavailable()
        app = create_app(provider, stateless=False)

        response = asyncio.run(self._raw_tools_list(app))

        assert response.status_code != 200
