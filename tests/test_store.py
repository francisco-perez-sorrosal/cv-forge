"""Tests for ResumeStore."""

from __future__ import annotations

import yaml

from cv_forge.data.store import ResumeStore
from cv_forge.models.resume import EntryId, Institution, Project, WorkEntry
from cv_forge.models.semantics import EntryAnnotations, SemanticOverlay

# --- Construction and properties ---


class TestConstruction:
    def test_resume_property(self, minimal_store, minimal_resume):
        assert minimal_store.resume is minimal_resume

    def test_semantics_property(self, minimal_store, minimal_semantics):
        assert minimal_store.semantics is minimal_semantics

    def test_entry_index_covers_all_types(self, minimal_store):
        assert minimal_store.entry_by_id("inst-acme") is not None
        assert minimal_store.entry_by_id("work-acme-2023") is not None
        assert minimal_store.entry_by_id("proj-widget") is not None
        assert minimal_store.entry_by_id("pub-nlp-2019") is not None
        assert minimal_store.entry_by_id("patent-widget-2022") is not None
        assert minimal_store.entry_by_id("edu-testuni-phd") is not None
        assert minimal_store.entry_by_id("skill-programming") is not None
        assert minimal_store.entry_by_id("lang-en") is not None
        assert minimal_store.entry_by_id("conf-icml-2019") is not None
        assert minimal_store.entry_by_id("member-asf") is not None


# --- entry_by_id ---


class TestEntryById:
    def test_institution(self, minimal_store):
        entry = minimal_store.entry_by_id("inst-acme")
        assert isinstance(entry, Institution)
        assert entry.name == "Acme Corp"

    def test_work_entry(self, minimal_store):
        entry = minimal_store.entry_by_id("work-acme-2023")
        assert isinstance(entry, WorkEntry)
        assert entry.position == "Senior Engineer"

    def test_nested_project(self, minimal_store):
        entry = minimal_store.entry_by_id("proj-widget")
        assert isinstance(entry, Project)
        assert entry.name == "Widget Builder"

    def test_not_found(self, minimal_store):
        assert minimal_store.entry_by_id("nonexistent") is None


# --- entry_label ---


class TestEntryLabel:
    def test_project_uses_name(self, minimal_store):
        assert minimal_store.entry_label("proj-widget") == "Widget Builder"

    def test_patent_uses_title(self, minimal_store):
        assert (
            minimal_store.entry_label("patent-widget-2022")
            == "Widget Generation Method"
        )

    def test_work_uses_position(self, minimal_store):
        assert minimal_store.entry_label("work-acme-2023") == "Senior Engineer"

    def test_fallback_to_id(self, minimal_store):
        assert minimal_store.entry_label("nonexistent") == "nonexistent"


# --- Institution lookup ---


class TestInstitutionLookup:
    def test_institution_by_id(self, minimal_store):
        inst = minimal_store.institution_by_id("inst-acme")
        assert inst is not None
        assert inst.name == "Acme Corp"

    def test_institution_name(self, minimal_store):
        assert minimal_store.institution_name("inst-acme") == "Acme Corp"

    def test_institution_name_fallback(self, minimal_store):
        assert minimal_store.institution_name("nonexistent") == "nonexistent"


# --- work_by_company ---


class TestWorkByCompany:
    def test_exact_name(self, minimal_store):
        results = minimal_store.work_by_company("Acme Corp")
        assert len(results) == 1
        assert results[0].id == "work-acme-2023"

    def test_case_insensitive(self, minimal_store):
        results = minimal_store.work_by_company("acme corp")
        assert len(results) == 1

    def test_alias_match(self, minimal_store):
        results = minimal_store.work_by_company("Acme Inc.")
        assert len(results) == 1

    def test_no_match(self, minimal_store):
        assert minimal_store.work_by_company("Unknown Corp") == []


# --- work_by_date_range ---


class TestWorkByDateRange:
    def test_overlapping(self, minimal_store):
        results = minimal_store.work_by_date_range("2020", "2022")
        ids = {w.id for w in results}
        assert "work-acme-2023" in ids

    def test_no_overlap(self, minimal_store):
        results = minimal_store.work_by_date_range("2025", "2026")
        assert results == []


# --- entries_by_topic ---


class TestEntriesByTopic:
    def test_with_descendants(self, minimal_store):
        results = minimal_store.entries_by_topic("ai")
        ids = {r["id"] for r in results}
        assert "work-acme-2023" in ids
        assert "proj-widget" in ids

    def test_filters_unknown_ids(self, minimal_store):
        for r in minimal_store.entries_by_topic("ai"):
            assert r["entry"] is not None


# --- audience_relevant_entries ---


class TestAudienceRelevantEntries:
    def test_known_audience(self, minimal_store):
        results = minimal_store.audience_relevant_entries("hiring-manager")
        assert len(results) >= 1
        assert results[0]["relevance"] == "primary"

    def test_unknown_audience(self, minimal_store):
        assert minimal_store.audience_relevant_entries("unknown") == []


# --- Cross-reference validation ---


class TestCrossReferenceValidation:
    def test_no_warning_with_valid_data(self, minimal_store):
        warnings: list[str] = []
        from loguru import logger

        handler_id = logger.add(lambda msg: warnings.append(str(msg)), level="WARNING")
        try:
            minimal_store._validate_cross_references()
        finally:
            logger.remove(handler_id)
        assert not any("unknown entry IDs" in w for w in warnings)

    def test_warns_on_dangling_refs(self, minimal_resume):
        semantics = SemanticOverlay(
            annotations=[
                EntryAnnotations(entry_id=EntryId("dangling-id")),
            ],
        )
        store = ResumeStore(minimal_resume, semantics)
        warnings: list[str] = []
        from loguru import logger

        handler_id = logger.add(
            lambda msg: warnings.append(str(msg)),
            level="WARNING",
            format="{message}",
        )
        try:
            store._validate_cross_references()
        finally:
            logger.remove(handler_id)
        assert any("unknown entry IDs" in w for w in warnings)


# --- load() class method ---


class TestLoad:
    def test_load_with_semantics(self, tmp_path):
        resume_data = {
            "personal_info": {"name": "Loader Test"},
            "institutions": [],
            "work": [],
        }
        sem_data = {
            "version": "1.0.0",
            "taxonomy": {"topics": []},
            "annotations": [],
        }
        with open(tmp_path / "resume.yaml", "w") as f:
            yaml.dump(resume_data, f)
        with open(tmp_path / "resume-semantics.yaml", "w") as f:
            yaml.dump(sem_data, f)

        store = ResumeStore.load(tmp_path)
        assert store.resume.personal_info.name == "Loader Test"
        assert store.semantics.version == "1.0.0"

    def test_load_without_semantics(self, tmp_path):
        resume_data = {
            "personal_info": {"name": "No Semantics"},
            "institutions": [],
            "work": [],
        }
        with open(tmp_path / "resume.yaml", "w") as f:
            yaml.dump(resume_data, f)

        store = ResumeStore.load(tmp_path)
        assert store.resume.personal_info.name == "No Semantics"
        assert store.semantics.annotations == []
