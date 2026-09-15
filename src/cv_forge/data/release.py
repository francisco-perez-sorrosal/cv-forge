"""Release wire-format types and fetcher for the `cv` <-> `cv-forge` contract.

Pure data shapes for `release.json` and the compiled artifacts it describes,
plus `GitHubReleaseFetcher` -- the one piece of network code in this module,
satisfying the `ReleaseFetcher` Protocol (`cv_forge.data.provider`) against a
`cv` GitHub Release's stable `releases/latest/download/<name>` URLs.

`ReleaseManifest`, `AssetEntry` and `ArtifactUnavailable` are Pydantic
models -- the same boundary-parsing pattern already used for `Resume` and
`SemanticOverlay`: `extra="ignore"` for additive evolution, validation at
construction, `pydantic.ValidationError` (a `ValueError` subclass) on a
missing or malformed field rather than a bare `KeyError` crashing the
refresh loop.
"""

from __future__ import annotations

import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import lru_cache

import certifi
import httpx2
from pydantic import BaseModel, ConfigDict, field_validator


class UnavailableReason(StrEnum):
    """Closed set of reasons a release artifact could not be fetched."""

    HTTP_ERROR = "http_error"
    TIMEOUT = "timeout"
    NO_RELEASE = "no_release"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    TOO_LARGE = "too_large"


class AssetEntry(BaseModel):
    """One asset's metadata as recorded in `release.json`."""

    model_config = ConfigDict(populate_by_name=True, frozen=True, extra="ignore")

    name: str
    size: int
    sha256: str


class ReleaseManifest(BaseModel):
    """The version token of the `cv` <-> `cv-forge` contract (`release.json`).

    Parsed leniently, served strictly: unknown top-level keys are ignored
    (additive evolution); a missing required key raises `ValidationError`.
    """

    model_config = ConfigDict(populate_by_name=True, frozen=True, extra="ignore")

    schema_version: int
    tag: str
    published_at: datetime
    cv_forge_version: str  # diagnostics only -- never a compatibility gate
    assets: Mapping[str, AssetEntry]

    @field_validator("assets", mode="before")
    @classmethod
    def _inject_asset_names(cls, value: object) -> object:
        """`release.json` keys each asset by filename; `AssetEntry.name` mirrors it."""
        if not isinstance(value, Mapping):
            return value
        return {name: {**entry, "name": name} for name, entry in value.items()}


@dataclass(frozen=True, slots=True)
class CachedArtifact:
    """A fetched release asset, cached in memory against its release tag.

    `tag` mirrors `CvDataProvider.current_tag` (`str | None`) rather than
    coercing `None` to `""` -- the boot-state tag (no successful refresh yet)
    has to compare equal to itself across repeated calls, and only `None ==
    None` does that; `"" == None` never does.
    """

    name: str
    tag: str | None
    body: bytes
    media_type: str


class ArtifactUnavailable(BaseModel):
    """A release asset could not be fetched -- an error value, not an exception.

    Carries a direct download URL so a client that cannot get bytes still
    has an actionable next step. `http_status` is populated only when
    `reason` came from an actual HTTP response (`http_error`/`no_release`);
    a timeout or a missing release never reached one.
    """

    model_config = ConfigDict(populate_by_name=True, frozen=True, extra="ignore")

    name: str
    tag: str | None
    download_url: str
    reason: UnavailableReason
    http_status: int | None = None
    # Free-text diagnostic (exception text or "HTTP <status> from <final url>");
    # surfaces in /healthz and logs, never in the closed `reason` set.
    detail: str | None = None


def format_unavailable(
    unavailable: ArtifactUnavailable, *, alternatives: str = ""
) -> str:
    """Render an `ArtifactUnavailable` as the entire client-visible signal.

    A tool error's text has no separate structured channel a naive client
    reads, so the reason, release tag, HTTP status (when known) and the
    direct download URL all have to survive as plain text -- this is the one
    place that formatting happens, shared by the `get_cv(format="pdf")` tool
    error and the `fps-cv://pdf` resource's JSON-RPC error.
    """
    release = f" for release {unavailable.tag}" if unavailable.tag else ""
    status = (
        f", http_status: {unavailable.http_status}" if unavailable.http_status else ""
    )
    message = (
        f"artifact_unavailable: {unavailable.name}{release} could not be fetched "
        f"(reason: {unavailable.reason}{status}). "
        f"Download directly: {unavailable.download_url}."
    )
    return f"{message} {alternatives}".rstrip() if alternatives else message


RELEASE_MANIFEST_ASSET = "release.json"


@lru_cache(maxsize=1)
def _ca_context() -> ssl.SSLContext:
    """TLS context verifying against certifi's bundle.

    httpx2's default is the OS trust store (via truststore); the WASIX image
    on Wasmer Edge has none, so every HTTPS fetch there failed with
    CERTIFICATE_VERIFY_FAILED. `SSL_CERT_FILE` still wins when set, matching
    Python's own default-context behaviour.
    """
    return ssl.create_default_context(cafile=certifi.where())


PDF_ASSET_NAME = "FranciscoPerezSorrosal_CV.pdf"
DEFAULT_CV_REPO = "francisco-perez-sorrosal/cv"
DEFAULT_RELEASES_URL = f"https://github.com/{DEFAULT_CV_REPO}/releases/latest"
DEFAULT_FETCH_TIMEOUT_SECONDS = 10.0


class GitHubReleaseFetcher:
    """`ReleaseFetcher` backed by a `cv` GitHub Release's stable
    `releases/latest/download/<name>` URLs.

    No GitHub API calls and no auth -- these are CDN-served redirects to the
    latest release's assets, not `api.github.com` requests, so the refresh
    loop's steady-state budget (one manifest fetch per interval) never
    touches GitHub's unauthenticated rate limit.
    """

    def __init__(
        self,
        repo: str,
        *,
        tag: str | None = None,
        timeout: float = DEFAULT_FETCH_TIMEOUT_SECONDS,
    ) -> None:
        self._repo = repo
        self._tag = tag
        self._timeout = timeout

    def download_url(self, name: str) -> str:
        if self._tag is not None:
            return (
                f"https://github.com/{self._repo}/releases/download/{self._tag}/{name}"
            )
        return f"https://github.com/{self._repo}/releases/latest/download/{name}"

    async def fetch_manifest(self) -> ReleaseManifest | ArtifactUnavailable:
        data = await self._fetch_bytes(RELEASE_MANIFEST_ASSET)
        if isinstance(data, ArtifactUnavailable):
            return data
        try:
            return ReleaseManifest.model_validate_json(data)
        except ValueError as exc:
            return ArtifactUnavailable(
                name=RELEASE_MANIFEST_ASSET,
                tag=self._tag,
                download_url=self.download_url(RELEASE_MANIFEST_ASSET),
                reason=UnavailableReason.HTTP_ERROR,
                detail=f"malformed release.json: {str(exc).splitlines()[0][:200]}",
            )

    async def fetch_asset(self, name: str) -> bytes | ArtifactUnavailable:
        return await self._fetch_bytes(name)

    async def _fetch_bytes(self, name: str) -> bytes | ArtifactUnavailable:
        url = self.download_url(name)
        try:
            async with httpx2.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                verify=_ca_context(),
            ) as client:
                response = await client.get(url)
        except httpx2.TimeoutException as exc:
            return ArtifactUnavailable(
                name=name,
                tag=self._tag,
                download_url=url,
                reason=UnavailableReason.TIMEOUT,
                detail=f"{type(exc).__name__}: {exc}",
            )
        except httpx2.HTTPError as exc:
            # Transport-level failures (TLS, DNS, redirect handling) carry no
            # status; the exception text is the only diagnostic available.
            return ArtifactUnavailable(
                name=name,
                tag=self._tag,
                download_url=url,
                reason=UnavailableReason.HTTP_ERROR,
                detail=f"{type(exc).__name__}: {exc}",
            )

        if response.status_code == 404:
            return ArtifactUnavailable(
                name=name,
                tag=self._tag,
                download_url=url,
                reason=UnavailableReason.NO_RELEASE,
                http_status=response.status_code,
                detail=f"HTTP {response.status_code} from {response.url}",
            )
        if response.status_code >= 400:
            return ArtifactUnavailable(
                name=name,
                tag=self._tag,
                download_url=url,
                reason=UnavailableReason.HTTP_ERROR,
                http_status=response.status_code,
                detail=f"HTTP {response.status_code} from {response.url}",
            )
        return response.content
