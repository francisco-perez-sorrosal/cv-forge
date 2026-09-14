"""Tests for `cv-forge export-schemas`: generation and the drift gate.

Written before `export-schemas`'s command body exists (M1.12 registered it as
a stub that exits 2 "not implemented" and does not yet accept `-o`/`--check`)
-- derived from the schema-export-and-drift-gate behavioral spec and
`INTERFACE_DESIGN.md §1.2-1.3`, not from reading the implementation.

**Invocation contract** (fixed by `tests/cli/test_render.py`, reused here
unchanged): `cv_forge.cli.main.main(argv) -> int`, called in-process.

Contract under test: `export-schemas -o <dir>` writes exactly
`resume.schema.json` and `semantics.schema.json`, generated from
`Resume.model_json_schema()`/`SemanticOverlay.model_json_schema()` via
`model_json_schema()` (§ Cross-Repo Contract item 2), with `$schema` set to
the JSON Schema 2020-12 dialect URI. `--check` compares the on-disk pair
against a fresh generation and writes nothing either way; it exits `0` when
they match and `4` on drift.

Drift is simulated by editing the *written file* after a real generation --
never by touching the Pydantic models themselves, since a genuine model
change is out of this step's scope.
"""

from __future__ import annotations

import json

from cv_forge.cli.main import main
from cv_forge.models.resume import Resume
from cv_forge.models.semantics import SemanticOverlay

JSON_SCHEMA_2020_12 = "https://json-schema.org/draft/2020-12/schema"


class TestExportWritesExactlyTwoFiles:
    def test_writes_only_the_two_named_schema_files(self, tmp_path):
        out_dir = tmp_path / "schemas"
        code = main(["export-schemas", "-o", str(out_dir)])
        assert code == 0
        assert sorted(p.name for p in out_dir.iterdir()) == [
            "resume.schema.json",
            "semantics.schema.json",
        ]


class TestExportedSchemasMatchTheModels:
    def test_resume_schema_is_2020_12_and_matches_the_pydantic_model(self, tmp_path):
        out_dir = tmp_path / "schemas"
        main(["export-schemas", "-o", str(out_dir)])
        written = json.loads((out_dir / "resume.schema.json").read_text())
        assert written.pop("$schema") == JSON_SCHEMA_2020_12
        assert written == Resume.model_json_schema()

    def test_semantics_schema_is_2020_12_and_matches_the_pydantic_model(self, tmp_path):
        out_dir = tmp_path / "schemas"
        main(["export-schemas", "-o", str(out_dir)])
        written = json.loads((out_dir / "semantics.schema.json").read_text())
        assert written.pop("$schema") == JSON_SCHEMA_2020_12
        assert written == SemanticOverlay.model_json_schema()


class TestCheckModeIdempotentRightAfterGeneration:
    def test_check_exits_zero_immediately_after_generation(self, tmp_path):
        out_dir = tmp_path / "schemas"
        generate_code = main(["export-schemas", "-o", str(out_dir)])
        check_code = main(["export-schemas", "-o", str(out_dir), "--check"])
        assert generate_code == 0
        assert check_code == 0


class TestCheckModeDetectsDriftWithoutWriting:
    def test_check_exits_four_on_drift_and_leaves_the_perturbed_file_untouched(
        self, tmp_path
    ):
        out_dir = tmp_path / "schemas"
        main(["export-schemas", "-o", str(out_dir)])
        resume_schema_path = out_dir / "resume.schema.json"

        # Simulate drift by perturbing the committed file directly -- as if
        # a model field were added without re-running export-schemas.
        drifted = json.loads(resume_schema_path.read_text())
        drifted["properties"]["_simulated_new_field"] = {"type": "string"}
        drifted_bytes = json.dumps(drifted).encode()
        resume_schema_path.write_bytes(drifted_bytes)

        check_code = main(["export-schemas", "-o", str(out_dir), "--check"])

        assert check_code == 4
        assert resume_schema_path.read_bytes() == drifted_bytes
