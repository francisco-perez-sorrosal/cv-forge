"""Release wire-format types for the `cv` <-> `cv-forge` contract.

Pure data shapes for `release.json` and the compiled artifacts it describes.
No network code lives here -- fetching is `ReleaseFetcher`'s job (a later
step); this module only defines what a fetch produces or fails with.

`ReleaseManifest`, `AssetEntry` and `ArtifactUnavailable` are Pydantic
models -- the same boundary-parsing pattern already used for `Resume` and
`SemanticOverlay`: `extra="ignore"` for additive evolution, validation at
construction, `pydantic.ValidationError` (a `ValueError` subclass) on a
missing or malformed field rather than a bare `KeyError` crashing the
refresh loop.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

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
    """A fetched release asset, cached in memory against its release tag."""

    name: str
    tag: str
    body: bytes
    media_type: str


class ArtifactUnavailable(BaseModel):
    """A release asset could not be fetched -- an error value, not an exception.

    Carries a direct download URL so a client that cannot get bytes still
    has an actionable next step.
    """

    model_config = ConfigDict(populate_by_name=True, frozen=True, extra="ignore")

    name: str
    tag: str | None
    download_url: str
    reason: UnavailableReason
