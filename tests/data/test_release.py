"""Tests for ReleaseManifest / ArtifactUnavailable -- release.json wire-format invariants.

Derived from SYSTEMS_PLAN.md § Cross-Repo Contract item 3 (`release.json` schema v1:
additive evolution, unknown top-level keys ignored, required keys `schema_version`,
`tag`, `published_at`, `assets`) and (`ArtifactUnavailable`'s closed `reason`
enum: `http_error | timeout | no_release | checksum_mismatch | too_large`). Written
before src/cv_forge/data/release.py exists -- confirm RED (ImportError) first.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from cv_forge.data.release import ArtifactUnavailable, ReleaseManifest

# Literal wire shape from SYSTEMS_PLAN.md § Cross-Repo Contract item 3 -- per-asset
# entries are keyed by filename and carry no "name" field of their own.
VALID_MANIFEST = {
    "schema_version": 1,
    "tag": "2026.09.13",
    "published_at": "2026-09-13T10:04:11Z",
    "cv_forge_version": "1.0.0",
    "assets": {
        "resume.yaml": {"size": 62312, "sha256": "a" * 64},
    },
}


class TestReleaseManifestWireFormat:
    def test_parses_the_documented_schema_v1_shape(self):
        manifest = ReleaseManifest.model_validate(VALID_MANIFEST)
        assert manifest.schema_version == 1
        assert manifest.tag == "2026.09.13"
        assert manifest.assets["resume.yaml"].size == 62312
        assert manifest.assets["resume.yaml"].sha256 == "a" * 64

    def test_ignores_unknown_top_level_keys(self):
        # Additive evolution: a field added by a newer cv-forge must not break an
        # older server's parse.
        payload = {**VALID_MANIFEST, "future_field": "reserved for a later schema"}
        manifest = ReleaseManifest.model_validate(payload)
        assert manifest.tag == "2026.09.13"

    @pytest.mark.parametrize(
        "missing_key", ["schema_version", "tag", "published_at", "assets"]
    )
    def test_fails_on_missing_required_key(self, missing_key):
        payload = dict(VALID_MANIFEST)
        del payload[missing_key]
        with pytest.raises(ValidationError):
            ReleaseManifest.model_validate(payload)

    def test_parses_from_raw_json_bytes(self):
        raw = json.dumps(VALID_MANIFEST).encode()
        manifest = ReleaseManifest.model_validate_json(raw)
        assert manifest.schema_version == 1


class TestArtifactUnavailableReason:
    @pytest.mark.parametrize(
        "reason",
        ["http_error", "timeout", "no_release", "checksum_mismatch", "too_large"],
    )
    def test_accepts_each_documented_reason(self, reason):
        artifact = ArtifactUnavailable(
            name="FranciscoPerezSorrosal_CV.pdf",
            tag="2026.09.13",
            download_url=(
                "https://github.com/francisco-perez-sorrosal/cv/releases/"
                "latest/download/FranciscoPerezSorrosal_CV.pdf"
            ),
            reason=reason,
        )
        assert artifact.reason == reason

    def test_rejects_a_reason_outside_the_closed_set(self):
        with pytest.raises((ValueError, TypeError)):
            ArtifactUnavailable(
                name="FranciscoPerezSorrosal_CV.pdf",
                tag="2026.09.13",
                download_url=(
                    "https://github.com/francisco-perez-sorrosal/cv/releases/"
                    "latest/download/FranciscoPerezSorrosal_CV.pdf"
                ),
                reason="server_is_on_fire",
            )
