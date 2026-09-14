"""Tests for `cv-forge serve`: pinned local-dir state, no network fetcher, `/healthz`.

Written before `serve`'s command body exists (M1.12 registered it as a stub
that exits 2 "not implemented") -- derived from the release-sourcing and
local-override behavioral requirements and `INTERFACE_DESIGN.md §1.1-1.6`,
not from reading the implementation. Do NOT
bind a real port or run an event-loop server here -- these tests exercise
provider/app construction in isolation via the seam below, driving the ASGI
app directly the same way `tests/mcp/test_healthz.py` does.

**App-building seam fixed here for the M1.16 implementer to satisfy**::

    def build_serve_app(args: argparse.Namespace) -> tuple[ASGIApp, CvDataProvider]

Separates "resolve data-dir, build a `CvDataProvider`, call
`cv_forge.mcp.app.create_app`" from "bind a transport and actually serve"
(`_cmd_serve` calls this, then dispatches stdio/http). `args` needs only the
`data_dir: str | None` attribute the `serve` subparser adds -- tests call this
directly instead of `main()`, so no port is ever bound and no event loop keeps
running past the test.

**Fetcher-injection seam reused from `tests/cli/test_fetch_snapshot.py`**::

    def make_release_fetcher(repo: str, *, tag: str | None = None) -> ReleaseFetcher

`serve`'s local-dir path (`--data-dir`/`$CV_DATA_DIR` resolved) must never call
this factory -- a local override must perform no network fetch -- verified
below by making the factory raise if invoked at all.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import httpx2
import yaml

from cv_forge.cli import main as cli_main
from cv_forge.cli.main import build_serve_app
from cv_forge.data.provider import Pinned

RESUME_YAML = yaml.dump(
    {"personal_info": {"name": "Serve Test"}, "institutions": [], "work": []}
).encode()


def _local_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "cv-data"
    data_dir.mkdir()
    (data_dir / "resume.yaml").write_bytes(RESUME_YAML)
    return data_dir


def _raise_if_fetcher_factory_called(monkeypatch) -> None:
    def _factory(repo: str, *, tag: str | None = None):
        raise AssertionError(
            "make_release_fetcher must not be called when a local data "
            "directory is resolved (local override: no network fetch)"
        )

    monkeypatch.setattr(cli_main, "make_release_fetcher", _factory, raising=False)


@asynccontextmanager
async def _run_asgi_lifespan(app):
    """Minimal hand-rolled ASGI lifespan driver, adapted from
    `tests/mcp/test_healthz.py::_run_asgi_lifespan` (no `asgi_lifespan`
    dependency in this project)."""
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


class TestDataDirBuildsPinnedProvider:
    def test_data_dir_flag_yields_a_pinned_provider(self, tmp_path, monkeypatch):
        data_dir = _local_data_dir(tmp_path)
        _raise_if_fetcher_factory_called(monkeypatch)

        _app, provider = build_serve_app(argparse.Namespace(data_dir=str(data_dir)))

        assert isinstance(provider.state, Pinned)

    def test_cv_data_dir_env_var_yields_a_pinned_provider(self, tmp_path, monkeypatch):
        data_dir = _local_data_dir(tmp_path)
        monkeypatch.setenv("CV_DATA_DIR", str(data_dir))
        _raise_if_fetcher_factory_called(monkeypatch)

        _app, provider = build_serve_app(argparse.Namespace(data_dir=None))

        assert isinstance(provider.state, Pinned)


class TestNeverConstructsTheNetworkFetcher:
    def test_local_dir_resolution_never_invokes_the_fetcher_factory(
        self, tmp_path, monkeypatch
    ):
        data_dir = _local_data_dir(tmp_path)
        _raise_if_fetcher_factory_called(monkeypatch)

        # No AssertionError propagating out of build_serve_app *is* the
        # behavior under test: the factory patched above raises the moment
        # it is invoked at all, regardless of what it's asked to build.
        build_serve_app(argparse.Namespace(data_dir=str(data_dir)))


class TestHealthzReportsPinned:
    def test_healthz_reports_pinned_refresh_state_for_a_local_data_dir(
        self, tmp_path, monkeypatch
    ):
        data_dir = _local_data_dir(tmp_path)
        _raise_if_fetcher_factory_called(monkeypatch)

        app, _provider = build_serve_app(argparse.Namespace(data_dir=str(data_dir)))

        response = asyncio.run(_get_healthz(app))

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["refresh_state"] == "pinned"
