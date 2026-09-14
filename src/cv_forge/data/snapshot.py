"""CvDataSnapshot: the immutable unit of served CV data.

`origin` is a sum type -- `LocalDir | ReleaseAssets | BakedSnapshot` -- not
three correlated nullable fields, so a state like "a release with a local
path" is unrepresentable. `CvDataSnapshot.parse()` is the only constructor
that accepts raw bytes: it validates through the Pydantic models and raises
before any instance exists, so no partially-parsed snapshot can exist
either.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from cv_forge.models.resume import Resume
from cv_forge.models.semantics import SemanticOverlay


@dataclass(frozen=True, slots=True)
class LocalDir:
    """Data loaded from a directory on disk (CV_DATA_DIR, tests, CI)."""

    path: Path


@dataclass(frozen=True, slots=True)
class ReleaseAssets:
    """Data fetched live from a `cv` GitHub Release."""

    tag: str
    published_at: datetime


@dataclass(frozen=True, slots=True)
class BakedSnapshot:
    """Data staged into the deploy image at build time."""

    staged_at: datetime
    tag: str | None


DataOrigin = LocalDir | ReleaseAssets | BakedSnapshot


@dataclass(frozen=True, slots=True)
class CvDataSnapshot:
    """A fully parsed, validated resume + semantic overlay, frozen in time.

    Invariant: a snapshot is always fully parsed and validated. `parse()` is
    the only function that accepts raw bytes; it runs `Resume.model_validate`
    / `SemanticOverlay.model_validate` and raises before any instance exists.
    Pure value: frozen, comparable, freely shareable across concurrent
    requests. Snapshots are never mutated -- they are replaced.
    """

    resume: Resume
    semantics: SemanticOverlay
    origin: DataOrigin
    loaded_at: datetime

    @classmethod
    def parse(
        cls,
        resume_bytes: bytes,
        semantics_bytes: bytes | None,
        origin: DataOrigin,
    ) -> CvDataSnapshot:
        """Validate raw YAML bytes into a snapshot. Raises before construction.

        `semantics_bytes=None` yields an empty `SemanticOverlay`, matching
        "no semantic overlay found" for the optional file.
        """
        resume = Resume.model_validate(yaml.safe_load(resume_bytes))
        semantics = _parse_semantics(semantics_bytes)
        return cls(
            resume=resume,
            semantics=semantics,
            origin=origin,
            loaded_at=datetime.now(UTC),
        )


def _parse_semantics(semantics_bytes: bytes | None) -> SemanticOverlay:
    if semantics_bytes is None:
        return SemanticOverlay()
    raw = yaml.safe_load(semantics_bytes)
    return SemanticOverlay.model_validate(raw) if raw else SemanticOverlay()
