"""Tests for `cv-forge validate`: schema/xref findings and exit codes.

Written before `validate`'s command body exists (M1.12 registered it as a
stub that exits 2 "not implemented" and does not yet accept `--data-dir`) --
derived from the schema-export-and-drift-gate behavioral spec and
`INTERFACE_DESIGN.md §1.3-1.6`, not from reading the implementation.

**Invocation contract** (fixed by `tests/cli/test_render.py` for `render`,
reused here unchanged): `cv_forge.cli.main.main(argv) -> int`, called
in-process, `capsys`/`tmp_path` for I/O.

Findings shape (§1.4): `{severity, code, pointer, message, hint?}` --
`code` is `schema.*` for JSON-Schema-expressible failures (type/format/pattern),
`xref.*` for cross-reference invariants JSON Schema cannot express. `pointer`
is a JSON Pointer into the document. Exit codes (§1.3): `0` valid, `3` data
invalid (schema and/or cross-reference).

Fixtures use `inst-yahoo`/`inst-yahooo` deliberately -- the exact typo pair
`INTERFACE_DESIGN.md §1.6`'s worked example uses, itself drawn from the real
`cv-data/resume.yaml` institution id, so the "did you mean" hint has a real
precedent to match against.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from cv_forge.cli.main import main

# --- Fixtures: data-dir builders ---


def _write_resume(
    data_dir: Path, *, institutions: list[dict], work: list[dict]
) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "resume.yaml").write_text(
        yaml.dump(
            {
                "personal_info": {"name": "CLI Validate Test Candidate"},
                "institutions": institutions,
                "work": work,
            }
        )
    )


def _valid_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "cv-data"
    _write_resume(
        data_dir,
        institutions=[
            {"id": "inst-yahoo", "name": "Yahoo", "type": "company"},
        ],
        work=[
            {
                "id": "work-yahoo-2021",
                "institution_id": "inst-yahoo",
                "position": "Engineer",
                "start_date": "2021",
            }
        ],
    )
    return data_dir


def _unknown_institution_data_dir(tmp_path: Path) -> Path:
    """A work entry references "inst-yahooo" (typo) instead of the declared
    "inst-yahoo" -- the exact pair from `INTERFACE_DESIGN.md §1.6`'s example."""
    data_dir = tmp_path / "cv-data"
    _write_resume(
        data_dir,
        institutions=[
            {"id": "inst-yahoo", "name": "Yahoo", "type": "company"},
        ],
        work=[
            {
                "id": "work-yahoo-2021",
                "institution_id": "inst-yahooo",
                "position": "Engineer",
                "start_date": "2021",
            }
        ],
    )
    return data_dir


def _malformed_start_date_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "cv-data"
    _write_resume(
        data_dir,
        institutions=[
            {"id": "inst-yahoo", "name": "Yahoo", "type": "company"},
        ],
        work=[
            {
                "id": "work-yahoo-2021",
                "institution_id": "inst-yahoo",
                "position": "Engineer",
                "start_date": "March 2019",
            }
        ],
    )
    return data_dir


# --- Valid data: exit 0 ---


class TestValidDataDirectory:
    def test_exits_zero_on_a_minimal_valid_data_dir(self, tmp_path):
        data_dir = _valid_data_dir(tmp_path)
        code = main(["validate", "--data-dir", str(data_dir)])
        assert code == 0


# --- Unknown cross-reference: exit 3, xref.* finding, did-you-mean hint ---


class TestUnknownInstitutionReference:
    def test_exits_with_data_invalid_code(self, tmp_path):
        data_dir = _unknown_institution_data_dir(tmp_path)
        code = main(["validate", "--data-dir", str(data_dir)])
        assert code == 3

    def test_json_findings_name_the_offending_pointer_with_a_did_you_mean_hint(
        self, tmp_path, capsys
    ):
        data_dir = _unknown_institution_data_dir(tmp_path)
        main(["validate", "--data-dir", str(data_dir), "--json"])
        envelope = json.loads(capsys.readouterr().out)
        findings = envelope["findings"]
        xref_findings = [f for f in findings if f["code"].startswith("xref.")]
        assert len(xref_findings) == 1
        finding = xref_findings[0]
        # The pointer must resolve to the offending institution reference on
        # the first (only) work entry -- not merely "somewhere in the doc".
        assert finding["pointer"].startswith("/work/0/institution")
        assert "inst-yahooo" in finding["message"]
        assert "inst-yahoo" in finding["hint"]


# --- Malformed field value: exit 3, schema.* finding ---


class TestMalformedStartDate:
    def test_exits_with_data_invalid_code(self, tmp_path):
        data_dir = _malformed_start_date_data_dir(tmp_path)
        code = main(["validate", "--data-dir", str(data_dir)])
        assert code == 3

    def test_json_findings_name_the_offending_pointer_as_a_schema_finding(
        self, tmp_path, capsys
    ):
        data_dir = _malformed_start_date_data_dir(tmp_path)
        main(["validate", "--data-dir", str(data_dir), "--json"])
        envelope = json.loads(capsys.readouterr().out)
        findings = envelope["findings"]
        schema_findings = [f for f in findings if f["code"].startswith("schema.")]
        assert len(schema_findings) == 1
        finding = schema_findings[0]
        assert finding["pointer"] == "/work/0/start_date"
        assert "March 2019" in finding["message"]


# --- --json envelope shape (generic, §1.4) ---


class TestJsonEnvelopeShape:
    def test_failure_envelope_has_the_documented_keys_and_failed_status(
        self, tmp_path, capsys
    ):
        data_dir = _unknown_institution_data_dir(tmp_path)
        code = main(["validate", "--data-dir", str(data_dir), "--json"])
        assert code == 3
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["command"] == "validate"
        assert envelope["status"] == "failed"
        assert envelope["cv_forge_version"]
        assert envelope["data_origin"]["kind"]
        assert envelope["outputs"] == []
        assert len(envelope["findings"]) >= 1


# --- stdout/stderr discipline (§1.4) ---


class TestStdoutDisciplineWithoutJson:
    def test_stdout_is_empty_and_findings_go_to_stderr_on_failure(
        self, tmp_path, capsys
    ):
        data_dir = _unknown_institution_data_dir(tmp_path)
        code = main(["validate", "--data-dir", str(data_dir)])
        assert code == 3
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "inst-yahooo" in captured.err
