"""Tests for `cv-forge fetch-snapshot`: asset scope, `--tag` threading, failure policy.

Written before `fetch-snapshot`'s command body exists (M1.12 registered it as a
stub that prints "not implemented" and exits 2) -- derived from the release-
sourcing and local-override behavioral requirements, `INTERFACE_DESIGN.md
§1.1-1.6`, and the `Cross-Repo Contract`'s asset-name table,
not from reading the implementation.

**Fetcher-injection seam fixed here for the M1.16 implementer to satisfy**::

    def make_release_fetcher(repo: str, *, tag: str | None = None) -> ReleaseFetcher

A module-level factory in `cv_forge.cli.main`, called internally by both
`fetch-snapshot` and `serve` (its release-fallback path, out of scope for this
file -- see `tests/cli/test_serve.py`) to construct the real
`GitHubReleaseFetcher`. Tests monkeypatch this attribute to inject a fake,
no-network fetcher and to capture the `(repo, tag)` it was called with -- this
is the only way `--tag <calver>` is observable from outside the CLI, since
`ReleaseFetcher.fetch_manifest`/`fetch_asset` (`cv_forge.data.provider`) take
no tag parameter of their own; a tag-scoped fetcher is constructed once per
invocation instead. `monkeypatch.setattr(..., raising=False)` is used
throughout because the attribute does not exist on the stub yet -- against the
current stub every test here fails on an exit-code/stdout assertion (RED via
exit-code-2), not on the monkeypatch call itself.

**Partial-write policy fixed here**: on any `ArtifactUnavailable` from
`fetch_manifest()` or `fetch_asset()`, `fetch-snapshot` writes nothing --
verified below by asserting none of the three target files exist in the
output directory after a failing run. All fetches must complete before the
first byte reaches disk.

**Asset scope**: exactly `resume.yaml`, `resume-semantics.yaml`, `release.json`
are fetched via `fetch_asset(name)` -- `fetch_manifest()` is called first only
to fail fast and to source the `download_url` for the error message.

Invocation contract reused from `tests/cli/test_render.py`:
`cv_forge.cli.main.main(argv) -> int`, in-process, `capsys`/`tmp_path` for I/O.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from cv_forge.cli import main as cli_main
from cv_forge.data.release import ArtifactUnavailable, ReleaseManifest

TARGET_FILENAMES = ("resume.yaml", "resume-semantics.yaml", "release.json")


@dataclass
class FakeReleaseFetcher:
    """No-network fake satisfying the `ReleaseFetcher` contract (same shape
    `tests/mcp/test_healthz.py` and `tests/data/test_provider.py` use)."""

    manifest: ReleaseManifest | ArtifactUnavailable
    assets: dict[str, bytes | ArtifactUnavailable]

    async def fetch_manifest(self) -> ReleaseManifest | ArtifactUnavailable:
        return self.manifest

    async def fetch_asset(self, name: str) -> bytes | ArtifactUnavailable:
        return self.assets[name]


def _install_fake_fetcher(
    monkeypatch, fetcher: FakeReleaseFetcher
) -> list[tuple[str, str | None]]:
    """Monkeypatch the documented `make_release_fetcher` seam; returns the
    list of `(repo, tag)` calls the CLI made against it."""
    calls: list[tuple[str, str | None]] = []

    def _factory(repo: str, *, tag: str | None = None):
        calls.append((repo, tag))
        return fetcher

    monkeypatch.setattr(cli_main, "make_release_fetcher", _factory, raising=False)
    return calls


def _manifest(tag: str = "2026.09.13") -> ReleaseManifest:
    return ReleaseManifest.model_validate(
        {
            "schema_version": 1,
            "tag": tag,
            "published_at": "2026-09-13T10:04:11Z",
            "cv_forge_version": "1.0.0",
            "assets": {},
        }
    )


def _unavailable(name: str) -> ArtifactUnavailable:
    return ArtifactUnavailable(
        name=name,
        tag=None,
        download_url=(
            f"https://github.com/francisco-perez-sorrosal/cv/releases/"
            f"latest/download/{name}"
        ),
        reason="http_error",
    )


class TestWritesExactlyTheThreeNamedAssets:
    def test_success_writes_only_the_three_target_files_with_fetched_bytes(
        self, tmp_path, monkeypatch
    ):
        payloads = {
            "resume.yaml": b"personal_info: {name: Snapshot Candidate}\n",
            "resume-semantics.yaml": b"topics: []\n",
            "release.json": b'{"schema_version": 1, "tag": "2026.09.13"}',
        }
        fetcher = FakeReleaseFetcher(manifest=_manifest(), assets=payloads)
        _install_fake_fetcher(monkeypatch, fetcher)

        out_dir = tmp_path / "snapshot"
        code = cli_main.main(["fetch-snapshot", "-o", str(out_dir)])

        assert code == 0
        written = {p.name for p in out_dir.iterdir()}
        assert written == set(TARGET_FILENAMES)
        for name, expected_bytes in payloads.items():
            assert (out_dir / name).read_bytes() == expected_bytes


class TestTagOption:
    def test_tag_flag_is_threaded_to_the_fetcher_factory(self, tmp_path, monkeypatch):
        fetcher = FakeReleaseFetcher(
            manifest=_manifest("2025.01.01"),
            assets={name: b"x" for name in TARGET_FILENAMES},
        )
        calls = _install_fake_fetcher(monkeypatch, fetcher)

        code = cli_main.main(
            ["fetch-snapshot", "--tag", "2025.01.01", "-o", str(tmp_path / "snap")]
        )

        assert code == 0
        assert calls, "make_release_fetcher was never called"
        _repo, tag = calls[-1]
        assert tag == "2025.01.01"


class TestArtifactUnavailable:
    def test_unavailable_resume_exits_1_names_download_url_and_writes_nothing(
        self, tmp_path, monkeypatch, capsys
    ):
        fetcher = FakeReleaseFetcher(
            manifest=_manifest(),
            assets={
                "resume.yaml": _unavailable("resume.yaml"),
                "resume-semantics.yaml": b"topics: []\n",
                "release.json": b"{}",
            },
        )
        _install_fake_fetcher(monkeypatch, fetcher)

        out_dir = tmp_path / "snapshot"
        code = cli_main.main(["fetch-snapshot", "-o", str(out_dir)])

        assert code == 1
        err = capsys.readouterr().err
        assert "releases/latest/download/resume.yaml" in err
        for name in TARGET_FILENAMES:
            assert not (out_dir / name).exists()


class TestJsonEnvelope:
    def test_success_envelope_lists_three_outputs_each_with_a_valid_sha256(
        self, tmp_path, monkeypatch, capsys
    ):
        payloads = {name: f"{name}-body".encode() for name in TARGET_FILENAMES}
        fetcher = FakeReleaseFetcher(manifest=_manifest(), assets=payloads)
        _install_fake_fetcher(monkeypatch, fetcher)

        out_dir = tmp_path / "snapshot"
        code = cli_main.main(["fetch-snapshot", "-o", str(out_dir), "--json"])

        assert code == 0
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["command"] == "fetch-snapshot"
        assert envelope["status"] == "ok"
        outputs = envelope["outputs"]
        assert len(outputs) == 3
        assert {Path(o["path"]).name for o in outputs} == set(TARGET_FILENAMES)
        for output in outputs:
            digest = hashlib.sha256(Path(output["path"]).read_bytes()).hexdigest()
            assert output["sha256"] == digest
