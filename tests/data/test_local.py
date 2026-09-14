"""Tests for load_local_dir() -- local/CI data override.

Derived from the local-data-override requirement ("When CV_DATA_DIR points at a directory
containing resume.yaml ... the system loads from that directory, performs no
network fetch, and reports pinned as its refresh state") and the M1.4 file list
(`data/local.py` -> `load_local_dir(path) -> CvDataSnapshot`). Written before
src/cv_forge/data/local.py exists -- confirm RED (ImportError) first.

The "no network fetch" / "pinned" state assertions belong to CvDataProvider
(M1.6/M1.7, tested in tests/data/test_provider.py) -- this file covers only the
loader's own contract: it either returns a fully-parsed LocalDir-origin snapshot
or raises a clear, actionable error.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from cv_forge.data.local import load_local_dir
from cv_forge.data.snapshot import LocalDir


def _write_resume(directory: Path, data: dict) -> None:
    (directory / "resume.yaml").write_text(yaml.dump(data))


class TestLoadLocalDir:
    def test_raises_a_clear_error_when_resume_yaml_is_absent(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="resume.yaml"):
            load_local_dir(tmp_path)

    def test_loads_a_local_dir_origin_snapshot_when_resume_yaml_is_present(
        self, tmp_path
    ):
        _write_resume(
            tmp_path,
            {
                "personal_info": {"name": "Local Loader"},
                "institutions": [],
                "work": [],
            },
        )
        snapshot = load_local_dir(tmp_path)
        assert isinstance(snapshot.origin, LocalDir)
        assert snapshot.resume.personal_info.name == "Local Loader"

    def test_loads_without_a_semantics_file(self, tmp_path):
        _write_resume(
            tmp_path,
            {
                "personal_info": {"name": "No Semantics"},
                "institutions": [],
                "work": [],
            },
        )
        snapshot = load_local_dir(tmp_path)
        assert snapshot.semantics.annotations == []

    def test_loads_with_a_semantics_file_present(self, tmp_path):
        _write_resume(
            tmp_path,
            {
                "personal_info": {"name": "With Semantics"},
                "institutions": [],
                "work": [],
            },
        )
        (tmp_path / "resume-semantics.yaml").write_text(
            yaml.dump(
                {"version": "1.0.0", "taxonomy": {"topics": []}, "annotations": []}
            )
        )
        snapshot = load_local_dir(tmp_path)
        assert snapshot.semantics.version == "1.0.0"

    def test_propagates_schema_validation_failure_instead_of_silently_loading(
        self, tmp_path
    ):
        # A work entry missing its required `id` must still fail -- load_local_dir
        # must not bypass CvDataSnapshot.parse()'s Invariant I1.
        _write_resume(
            tmp_path,
            {
                "personal_info": {"name": "Invalid Data"},
                "institutions": [],
                "work": [{"institution_id": "inst-x", "position": "Engineer"}],
            },
        )
        with pytest.raises(ValidationError):
            load_local_dir(tmp_path)
