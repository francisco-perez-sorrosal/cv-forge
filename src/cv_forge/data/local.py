"""Local-directory loading of a `CvDataSnapshot` (`CV_DATA_DIR`, tests, CI).

When a local data directory is configured, the server or CLI loads from it,
performs no network fetch, and the resulting snapshot's `LocalDir` origin is
what later lets `CvDataProvider` report a `pinned` refresh state.
"""

from __future__ import annotations

from pathlib import Path

from cv_forge.data.snapshot import CvDataSnapshot, LocalDir

RESUME_FILENAME = "resume.yaml"
SEMANTICS_FILENAME = "resume-semantics.yaml"


class LocalDataDirError(FileNotFoundError):
    """Raised when a local data directory is missing its required resume file."""


def load_local_dir(path: Path) -> CvDataSnapshot:
    """Load and validate a `CvDataSnapshot` from a local directory.

    `resume.yaml` is required; `resume-semantics.yaml` is optional and
    yields an empty semantic overlay when absent.
    """
    resume_path = path / RESUME_FILENAME
    if not resume_path.is_file():
        raise LocalDataDirError(
            f"{RESUME_FILENAME} not found in {path} "
            "(expected a directory containing resume.yaml)"
        )
    semantics_path = path / SEMANTICS_FILENAME
    semantics_bytes = semantics_path.read_bytes() if semantics_path.is_file() else None
    return CvDataSnapshot.parse(
        resume_bytes=resume_path.read_bytes(),
        semantics_bytes=semantics_bytes,
        origin=LocalDir(path=path),
    )
