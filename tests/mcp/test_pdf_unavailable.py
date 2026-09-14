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
from dataclasses import dataclass
from datetime import UTC, datetime

import anyio
import httpx2
import pytest
import yaml
from cv_forge.mcp.app import create_app
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

from cv_forge.data.provider import CvDataProvider
from cv_forge.data.release import ArtifactUnavailable, ReleaseManifest
from cv_forge.data.snapshot import CvDataSnapshot, ReleaseAssets

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

        async def _read():
            async with _mcp_session(app) as session:
                await session.read_resource("fps-cv://pdf")

        with pytest.raises(MCPError) as excinfo:
            asyncio.run(_read())

        assert DOWNLOAD_URL in excinfo.value.message


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
