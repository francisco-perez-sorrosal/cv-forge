"""Tests for `cv-forge render`: exit codes, `--json` envelope, R1 determinism.

Written before `src/cv_forge/cli/main.py` exists (the package currently has only
an empty `__init__.py`) -- derived from `INTERFACE_DESIGN.md §1.1-1.6` and the
one-renderer-two-callers behavior, not from reading the implementation.

**Invocation contract fixed here for the M1.12 implementer to satisfy**:

    def main(argv: list[str] | None = None) -> int

`cv_forge.cli.main.main` is called in-process (no subprocess) with `argv`
excluding the program name, matching the console-script entry `cv-forge =
"cv_forge.cli.main:main"`. Tests capture stdout/stderr via `capsys` and write
to `tmp_path`. A single cheap `pixi run cv-forge --help` subprocess smoke was
considered and skipped: the console script only registers on package
reinstall, which this in-process test suite must not depend on.

Asset filenames are pinned to the release-asset contract (`FranciscoPerezSorrosal_CV.<ext>`,
no `_English` suffix) rather than the legacy `scripts/render_cv.py` naming --
`render`'s whole reason to exist is producing the same bytes, at the same
names, that the publish workflow uploads.

No default for `render`'s `-o/--out` is documented in `INTERFACE_DESIGN.md §1.2`
(unlike `export-schemas`/`fetch-snapshot`, which do state one) -- every test
below passes `-o` explicitly rather than assuming a default output directory.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from cv_forge.cli.main import main

# --- Fixtures ---


@pytest.fixture
def cv_data_dir(tmp_path: Path) -> Path:
    """A minimal, valid local data directory (resume.yaml only, no semantics)."""
    data_dir = tmp_path / "cv-data"
    data_dir.mkdir()
    (data_dir / "resume.yaml").write_text(
        yaml.dump(
            {
                "personal_info": {"name": "CLI Test Candidate"},
                "institutions": [],
                "work": [],
            }
        )
    )
    return data_dir


# --- Data-directory resolution failure (exit 2, error shape ①) ---


class TestNoDataDirectoryResolved:
    def test_exits_with_usage_error_code(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("CV_DATA_DIR", raising=False)
        code = main(["render", "-f", "md", "-o", str(tmp_path)])
        assert code == 2

    def test_stderr_names_both_resolution_paths(self, tmp_path, monkeypatch, capsys):
        # The three-part shape (what/why/how) must at minimum tell the user
        # the two ways to point at data -- --data-dir and $CV_DATA_DIR --
        # since those are the only two inputs the resolution ladder reads.
        monkeypatch.delenv("CV_DATA_DIR", raising=False)
        main(["render", "-f", "md", "-o", str(tmp_path)])
        err = capsys.readouterr().err
        assert "--data-dir" in err
        assert "CV_DATA_DIR" in err

    def test_writes_nothing_to_stdout(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("CV_DATA_DIR", raising=False)
        main(["render", "-f", "md", "-o", str(tmp_path)])
        assert capsys.readouterr().out == ""


# --- Successful render: named file per format ---


class TestRenderWritesNamedFile:
    @pytest.mark.parametrize(
        "fmt,filename",
        [
            ("md", "FranciscoPerezSorrosal_CV.md"),
            ("html", "FranciscoPerezSorrosal_CV.html"),
            ("tex", "FranciscoPerezSorrosal_CV.tex"),
            ("typst", "FranciscoPerezSorrosal_CV.typ"),
        ],
    )
    def test_writes_the_release_asset_named_file(
        self, cv_data_dir, tmp_path, fmt, filename
    ):
        out_dir = tmp_path / "out"
        code = main(
            ["render", "-f", fmt, "--data-dir", str(cv_data_dir), "-o", str(out_dir)]
        )
        assert code == 0
        produced = out_dir / filename
        assert produced.is_file()
        assert produced.stat().st_size > 0


class TestUnknownFormat:
    def test_exits_with_usage_error_code(self, cv_data_dir, tmp_path):
        code = main(
            [
                "render",
                "-f",
                "bogus",
                "--data-dir",
                str(cv_data_dir),
                "-o",
                str(tmp_path),
            ]
        )
        assert code == 2


# --- PDF: compiler-missing vs compiler-present ---


class TestPdfRequiresLatexmk:
    def test_missing_latexmk_exits_with_toolchain_missing_code(
        self, cv_data_dir, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(shutil, "which", lambda _name: None)
        code = main(
            ["render", "-f", "pdf", "--data-dir", str(cv_data_dir), "-o", str(tmp_path)]
        )
        assert code == 5

    def test_missing_latexmk_error_names_the_compiler(
        self, cv_data_dir, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setattr(shutil, "which", lambda _name: None)
        main(
            ["render", "-f", "pdf", "--data-dir", str(cv_data_dir), "-o", str(tmp_path)]
        )
        assert "latexmk" in capsys.readouterr().err


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("latexmk") is None, reason="latexmk not on PATH")
def test_pdf_renders_and_compiles_when_latexmk_is_present(cv_data_dir, tmp_path):
    code = main(
        ["render", "-f", "pdf", "--data-dir", str(cv_data_dir), "-o", str(tmp_path)]
    )
    assert code == 0
    assert (tmp_path / "FranciscoPerezSorrosal_CV.pdf").is_file()


# --- --json envelope ---


class TestJsonEnvelope:
    def test_success_envelope_has_documented_keys_and_sha256_per_output(
        self, cv_data_dir, tmp_path, capsys
    ):
        code = main(
            [
                "render",
                "-f",
                "md",
                "--data-dir",
                str(cv_data_dir),
                "-o",
                str(tmp_path),
                "--json",
            ]
        )
        assert code == 0
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["command"] == "render"
        assert envelope["status"] == "ok"
        assert envelope["cv_forge_version"]
        assert envelope["data_origin"]["kind"]
        assert envelope["findings"] == []
        outputs = envelope["outputs"]
        assert len(outputs) == 1
        output = outputs[0]
        assert output["format"] == "md"
        assert Path(output["path"]).is_file()
        assert output["bytes"] == Path(output["path"]).stat().st_size
        assert len(output["sha256"]) == 64
        digest = hashlib.sha256(Path(output["path"]).read_bytes()).hexdigest()
        assert output["sha256"] == digest


# --- R1: determinism ---


class TestR1Determinism:
    def test_two_renders_of_the_same_data_are_byte_identical_and_hash_identical(
        self, cv_data_dir, tmp_path
    ):
        out_a = tmp_path / "run-a"
        out_b = tmp_path / "run-b"
        code_a = main(
            [
                "render",
                "-f",
                "md,html",
                "--data-dir",
                str(cv_data_dir),
                "-o",
                str(out_a),
            ]
        )
        code_b = main(
            [
                "render",
                "-f",
                "md,html",
                "--data-dir",
                str(cv_data_dir),
                "-o",
                str(out_b),
            ]
        )
        assert code_a == 0
        assert code_b == 0
        assert (out_a / "FranciscoPerezSorrosal_CV.md").read_bytes() == (
            out_b / "FranciscoPerezSorrosal_CV.md"
        ).read_bytes()
        assert (out_a / "FranciscoPerezSorrosal_CV.html").read_bytes() == (
            out_b / "FranciscoPerezSorrosal_CV.html"
        ).read_bytes()

    def test_two_renders_with_the_same_release_tag_are_still_byte_identical(
        self, cv_data_dir, tmp_path
    ):
        out_a = tmp_path / "run-a"
        out_b = tmp_path / "run-b"
        for out_dir in (out_a, out_b):
            code = main(
                [
                    "render",
                    "-f",
                    "html",
                    "--data-dir",
                    str(cv_data_dir),
                    "--release-tag",
                    "2026.09.14",
                    "-o",
                    str(out_dir),
                ]
            )
            assert code == 0
        assert (out_a / "FranciscoPerezSorrosal_CV.html").read_bytes() == (
            out_b / "FranciscoPerezSorrosal_CV.html"
        ).read_bytes()


# --- --release-tag: HTML embeds it, other formats ignore it ---


class TestReleaseTag:
    def test_html_embeds_the_release_tag_meta_and_footer_line_when_given(
        self, cv_data_dir, tmp_path
    ):
        out_dir = tmp_path / "out"
        code = main(
            [
                "render",
                "-f",
                "html",
                "--data-dir",
                str(cv_data_dir),
                "--release-tag",
                "2026.09.14",
                "-o",
                str(out_dir),
            ]
        )
        assert code == 0
        html = (out_dir / "FranciscoPerezSorrosal_CV.html").read_text()
        assert '<meta name="cv-release-tag" content="2026.09.14">' in html
        assert "Release 2026.09.14" in html

    def test_html_has_no_release_tag_meta_when_not_given(self, cv_data_dir, tmp_path):
        out_dir = tmp_path / "out"
        code = main(
            [
                "render",
                "-f",
                "html",
                "--data-dir",
                str(cv_data_dir),
                "-o",
                str(out_dir),
            ]
        )
        assert code == 0
        html = (out_dir / "FranciscoPerezSorrosal_CV.html").read_text()
        assert "cv-release-tag" not in html

    def test_json_envelope_surfaces_the_release_tag(
        self, cv_data_dir, tmp_path, capsys
    ):
        code = main(
            [
                "render",
                "-f",
                "html",
                "--data-dir",
                str(cv_data_dir),
                "--release-tag",
                "2026.09.14",
                "-o",
                str(tmp_path),
                "--json",
            ]
        )
        assert code == 0
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["release_tag"] == "2026.09.14"

    def test_non_html_formats_accept_but_ignore_the_release_tag(
        self, cv_data_dir, tmp_path
    ):
        out_dir = tmp_path / "out"
        code = main(
            [
                "render",
                "-f",
                "md",
                "--data-dir",
                str(cv_data_dir),
                "--release-tag",
                "2026.09.14",
                "-o",
                str(out_dir),
            ]
        )
        assert code == 0
        md = (out_dir / "FranciscoPerezSorrosal_CV.md").read_text()
        assert "2026.09.14" not in md


# --- stdout discipline without --json ---


class TestStdoutWithoutJson:
    def test_stdout_carries_only_the_produced_output_paths(
        self, cv_data_dir, tmp_path, capsys
    ):
        out_dir = tmp_path / "out"
        code = main(
            [
                "render",
                "-f",
                "md,html",
                "--data-dir",
                str(cv_data_dir),
                "-o",
                str(out_dir),
            ]
        )
        assert code == 0
        stdout = capsys.readouterr().out
        lines = stdout.strip("\n").splitlines()
        assert len(lines) == 2
        assert str(out_dir / "FranciscoPerezSorrosal_CV.md") in stdout
        assert str(out_dir / "FranciscoPerezSorrosal_CV.html") in stdout
