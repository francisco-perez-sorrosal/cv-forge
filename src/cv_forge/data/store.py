"""ResumeStore: read-only query access to a parsed resume and semantic overlay.

Constructed from already-parsed models -- loading lives at the boundary
(`cv_forge.data.local`, and eventually `cv_forge.cli` for semantics writes),
not here. A store whose data came from a GitHub release has no meaningful
`save()`; removing the persistence path removes that illegal state rather
than documenting it.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from cv_forge.data.local import load_local_dir
from cv_forge.models.resume import Institution, Resume
from cv_forge.models.semantics import Relationship, SemanticOverlay


class ResumeStore:
    """Read-only query access over a resume and its semantic overlay."""

    def __init__(self, resume: Resume, semantics: SemanticOverlay) -> None:
        self._resume = resume
        self._semantics = semantics
        self._entries_by_id: dict[str, object] = self._build_entry_index()
        self._validate_cross_references()

    @classmethod
    def load(cls, data_dir: Path) -> ResumeStore:
        """Construct a store from a local data directory.

        Transitional convenience for callers not yet wired through
        `CvDataProvider` -- delegates entirely to `load_local_dir`; no file
        I/O happens in this class.
        """
        snapshot = load_local_dir(data_dir)
        return cls(snapshot.resume, snapshot.semantics)

    @property
    def resume(self) -> Resume:
        return self._resume

    @property
    def semantics(self) -> SemanticOverlay:
        return self._semantics

    # --- Query methods ---

    def entry_by_id(self, entry_id: str) -> object | None:
        return self._entries_by_id.get(entry_id)

    def entry_label(self, entry_id: str) -> str:
        """Human-readable display name for an entry ID."""
        entry = self._entries_by_id.get(entry_id)
        if entry is None:
            return entry_id
        if hasattr(entry, "name"):
            return entry.name
        if hasattr(entry, "title"):
            return entry.title
        if hasattr(entry, "position"):
            return entry.position
        return entry_id

    def institution_by_id(self, inst_id: str) -> Institution | None:
        return self._resume.institution_by_id(inst_id)

    def institution_name(self, inst_id: str) -> str:
        """Resolve institution ID to display name."""
        inst = self._resume.institution_by_id(inst_id)
        return inst.name if inst else inst_id

    def work_by_company(self, company: str) -> list:
        """Find work entries matching a company name (case-insensitive substring).

        Searches institution name and aliases.
        """
        company_lower = company.lower()
        results = []
        for w in self._resume.work:
            inst = self._resume.institution_by_id(w.institution_id)
            if inst is None:
                continue
            names = [inst.name.lower()] + [a.lower() for a in inst.aliases]
            if any(company_lower in n for n in names):
                results.append(w)
        return results

    def work_by_date_range(self, start: str, end: str) -> list:
        """Find work entries overlapping a date range."""
        return [
            w
            for w in self._resume.work
            if w.start_date <= end and (w.end_date >= start or w.end_date == "")
        ]

    def entries_by_topic(self, topic_id: str) -> list[dict]:
        """Find resume entries annotated with a topic (including descendants)."""
        entry_ids = self._semantics.entries_by_topic(topic_id)
        return [
            {"id": eid, "entry": self._entries_by_id.get(eid)}
            for eid in entry_ids
            if eid in self._entries_by_id
        ]

    def relationships_for(self, entry_id: str) -> list[Relationship]:
        return self._semantics.relationships_for(entry_id)

    def audience_relevant_entries(self, audience: str) -> list[dict]:
        """Find entries most relevant for a given audience, sorted by relevance."""
        relevance_order = {"primary": 0, "secondary": 1, "tertiary": 2}
        results = []
        for ann in self._semantics.annotations:
            for ar in ann.audience_relevance:
                if ar.audience == audience and ar.relevance.value != "exclude":
                    results.append(
                        {
                            "entry_id": ann.entry_id,
                            "relevance": ar.relevance.value,
                            "reason": ar.reason,
                            "entry": self._entries_by_id.get(ann.entry_id),
                        }
                    )
        results.sort(key=lambda r: relevance_order.get(r["relevance"], 99))
        return results

    # --- Internal ---

    def _build_entry_index(self) -> dict[str, object]:
        index: dict[str, object] = {}
        for inst in self._resume.institutions:
            index[inst.id] = inst
        for w in self._resume.work:
            index[w.id] = w
            for p in w.projects:
                index[p.id] = p
        for section in [
            self._resume.education,
            self._resume.publications,
            self._resume.skills,
            self._resume.languages,
            self._resume.certificates,
            self._resume.projects,
            self._resume.patents,
            self._resume.conferences,
            self._resume.memberships,
            self._resume.book_reviews,
        ]:
            for entry in section:
                index[entry.id] = entry
        return index

    def _validate_cross_references(self) -> None:
        """Warn about dangling references in the semantic overlay."""
        valid_ids = self._resume.all_entry_ids()
        dangling = self._semantics.all_referenced_ids() - valid_ids
        if dangling:
            logger.warning(
                f"Semantic overlay references {len(dangling)} unknown entry IDs: "
                f"{sorted(dangling)[:10]}{'...' if len(dangling) > 10 else ''}"
            )
