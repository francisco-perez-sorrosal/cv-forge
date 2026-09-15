"""Validation findings over a parsed `Resume`: cross-references and date shape.

Operates on already-parsed models, not raw YAML -- `CvDataSnapshot.parse()`
(`cv_forge.data.snapshot`) is the boundary that turns bytes into typed
values; this module adds the invariants Pydantic's schema validation cannot
express on its own:

- **Cross-references** (`xref.*`): `institution_id` fields that name no
  declared `Institution`. JSON Schema has no "foreign key" concept, so this
  can only be checked once the whole document is parsed.
- **Date shape** (`schema.*`): `start_date` on `work`/`education`/
  `certificates` carries no Pydantic `pattern` constraint (see
  `LEARNINGS.md` for why one isn't added at the model level -- `Conference`
  reuses the same field name for a different date grammar, so a single
  shared pattern would either under- or over-constrain one of the two
  families). This check restores the constraint at the layer that knows
  which family it's looking at.

Findings share one shape across `validate` and the CLI's JSON envelope: `severity`, `code`
(`schema.*`/`xref.*`), a JSON Pointer `pointer`, a `message`, and an
optional did-you-mean `hint`.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Literal

from cv_forge.models.resume import Resume

Severity = Literal["error", "warning"]

# work[]/education[]/certificates[].start_date: "2019" or "2019-03" -- the
# only two shapes present in cv-data/resume.yaml for these three sections.
# Conference.start_date uses full YYYY-MM-DD and is deliberately excluded.
_YEAR_OR_YEAR_MONTH = re.compile(r"^\d{4}(-\d{2})?$")


@dataclass(frozen=True, slots=True)
class Finding:
    """One validation finding."""

    severity: Severity
    code: str
    pointer: str
    message: str
    hint: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "severity": self.severity,
            "code": self.code,
            "pointer": self.pointer,
            "message": self.message,
        }
        if self.hint is not None:
            payload["hint"] = self.hint
        return payload


def validate_resume(resume: Resume) -> list[Finding]:
    """Cross-reference and date-shape findings across the whole resume."""
    findings: list[Finding] = []
    institution_ids = {inst.id for inst in resume.institutions}
    for section, entries in _sections_with_institution_refs(resume):
        for index, entry in enumerate(entries):
            findings.extend(
                _check_institution_reference(section, index, entry, institution_ids)
            )
            findings.extend(_check_start_date_shape(section, index, entry))
    return findings


def _sections_with_institution_refs(resume: Resume) -> list[tuple[str, list]]:
    """Sections whose entries carry `institution_id` and a `YYYY[-MM]` date."""
    return [
        ("work", resume.work),
        ("education", resume.education),
        ("certificates", resume.certificates),
    ]


def _check_institution_reference(
    section: str, index: int, entry: object, institution_ids: set[str]
) -> list[Finding]:
    inst_id = entry.institution_id
    if inst_id in institution_ids:
        return []
    return [
        Finding(
            severity="error",
            code="xref.unknown_institution",
            pointer=f"/{section}/{index}/institution_id",
            message=f'"{inst_id}" is not a declared institution id',
            hint=_did_you_mean(inst_id, institution_ids),
        )
    ]


def _check_start_date_shape(section: str, index: int, entry: object) -> list[Finding]:
    start_date = getattr(entry, "start_date", "")
    if not start_date or _YEAR_OR_YEAR_MONTH.match(start_date):
        return []
    return [
        Finding(
            severity="error",
            code="schema.invalid_date_format",
            pointer=f"/{section}/{index}/start_date",
            message=f'expected YYYY-MM or YYYY, got "{start_date}"',
        )
    ]


def _did_you_mean(value: str, candidates: set[str]) -> str | None:
    matches = difflib.get_close_matches(value, candidates, n=1)
    return f'did you mean "{matches[0]}"?' if matches else None
