"""Tests for CvDataSnapshot and the DataOrigin sum type -- parse-boundary invariants.

Derived from SYSTEMS_PLAN.md § Architecture -> Data Structures (Invariant I1: a
snapshot is always fully parsed and validated; `parse()` is the only boundary
constructor) and the `DataOrigin` sum-type shape (`LocalDir | ReleaseAssets |
BakedSnapshot`, mutually exclusive, no nullable-field combos). Written before
src/cv_forge/data/snapshot.py exists -- confirm RED (ImportError) first.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
import yaml
from pydantic import ValidationError

from cv_forge.data.snapshot import (
    BakedSnapshot,
    CvDataSnapshot,
    LocalDir,
    ReleaseAssets,
)

VALID_RESUME_YAML = yaml.dump(
    {
        "personal_info": {"name": "Snapshot Test"},
        "institutions": [],
        "work": [],
    }
).encode()

VALID_SEMANTICS_YAML = yaml.dump(
    {
        "version": "1.0.0",
        "taxonomy": {"topics": []},
        "annotations": [],
    }
).encode()


# --- CvDataSnapshot.parse() -- Invariant I1 ---


class TestParseBoundary:
    def test_parses_valid_resume_and_semantics_into_a_snapshot(self, tmp_path):
        origin = LocalDir(path=tmp_path)
        snapshot = CvDataSnapshot.parse(VALID_RESUME_YAML, VALID_SEMANTICS_YAML, origin)
        assert snapshot.resume.personal_info.name == "Snapshot Test"
        assert snapshot.semantics.version == "1.0.0"
        assert snapshot.origin is origin
        assert isinstance(snapshot.loaded_at, datetime)

    def test_parses_with_no_semantics_bytes(self, tmp_path):
        origin = LocalDir(path=tmp_path)
        snapshot = CvDataSnapshot.parse(VALID_RESUME_YAML, None, origin)
        assert snapshot.semantics.annotations == []

    def test_raises_on_syntactically_malformed_resume_yaml(self, tmp_path):
        origin = LocalDir(path=tmp_path)
        with pytest.raises(yaml.YAMLError):
            CvDataSnapshot.parse(b"{unterminated: [1,2", None, origin)

    def test_raises_before_any_instance_exists_on_schema_invalid_resume(self, tmp_path):
        # A work entry missing its required `id` fails Resume's schema -- this is
        # invalid *content*, not invalid YAML syntax, and must still be rejected.
        bad_resume = yaml.dump(
            {
                "personal_info": {"name": "Snapshot Test"},
                "institutions": [],
                "work": [{"institution_id": "inst-x", "position": "Engineer"}],
            }
        ).encode()
        origin = LocalDir(path=tmp_path)
        with pytest.raises(ValidationError):
            CvDataSnapshot.parse(bad_resume, None, origin)

    def test_raises_on_schema_invalid_semantics(self, tmp_path):
        # An annotation missing its required `entryId` fails SemanticOverlay's schema.
        bad_semantics = yaml.dump(
            {
                "version": "1.0.0",
                "taxonomy": {"topics": []},
                "annotations": [{"topics": []}],
            }
        ).encode()
        origin = LocalDir(path=tmp_path)
        with pytest.raises(ValidationError):
            CvDataSnapshot.parse(VALID_RESUME_YAML, bad_semantics, origin)


# --- DataOrigin sum type -- mutually exclusive variants ---


class TestDataOriginVariants:
    def test_local_dir_and_release_assets_are_distinct_types(self, tmp_path):
        local = LocalDir(path=tmp_path)
        release = ReleaseAssets(tag="2026.09.13", published_at=datetime.now(UTC))
        assert not isinstance(local, type(release))
        assert not isinstance(release, type(local))

    def test_local_dir_rejects_release_only_fields(self, tmp_path):
        # A single class with nullable `path`/`tag`/`published_at` fields would
        # accept this call; the sum type must not.
        with pytest.raises(TypeError):
            LocalDir(path=tmp_path, tag="2026.09.13")

    def test_release_assets_rejects_local_dir_only_fields(self, tmp_path):
        with pytest.raises(TypeError):
            ReleaseAssets(
                tag="2026.09.13", published_at=datetime.now(UTC), path=tmp_path
            )

    def test_baked_snapshot_tag_is_optional(self):
        # Unlike ReleaseAssets.tag (required), BakedSnapshot.tag is `str | None` --
        # a baked fallback may predate any release.
        baked = BakedSnapshot(staged_at=datetime.now(UTC), tag=None)
        assert baked.tag is None

    def test_origin_variants_are_frozen(self, tmp_path):
        origin = LocalDir(path=tmp_path)
        with pytest.raises(FrozenInstanceError):
            origin.path = tmp_path / "elsewhere"
