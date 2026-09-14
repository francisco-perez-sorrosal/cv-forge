"""Behavioral tests for `mcp/main.py::_build_provider_or_exit`'s three-way
startup-error split, backed by `data.bootstrap.describe_startup_error`.

`pydantic.ValidationError` is a `ValueError` subclass, so a malformed
`resume.yaml` and an unparseable `CV_REFRESH_INTERVAL` used to collide under
one `except ValueError` and both reported the interval message
(`LIGHT_REVIEW_M1.8-rev.md` N1). These tests pin the fix: each failure gets
its own three-part (`INTERFACE_DESIGN.md §1.6`) message and its own `§1.3`
exit code.
"""

from __future__ import annotations

import pytest

from cv_forge.mcp.main import _build_provider_or_exit

VALID_RESUME_YAML = "personal_info:\n  name: Test\ninstitutions: []\nwork: []\n"


def test_malformed_resume_yaml_at_startup_reports_the_data_file_not_the_interval(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "resume.yaml").write_text("personal_info: 12345\n")
    monkeypatch.setenv("CV_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CV_REFRESH_INTERVAL", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        _build_provider_or_exit()

    assert exc_info.value.code == 3  # INTERFACE_DESIGN.md §1.3: data invalid
    stderr = capsys.readouterr().err
    assert str(tmp_path) in stderr
    assert "personal_info" in stderr
    assert "CV_REFRESH_INTERVAL" not in stderr


def test_invalid_refresh_interval_still_reports_the_env_message_not_the_data_one(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "resume.yaml").write_text(VALID_RESUME_YAML)
    monkeypatch.setenv("CV_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CV_REFRESH_INTERVAL", "not-a-number")

    with pytest.raises(SystemExit) as exc_info:
        _build_provider_or_exit()

    assert exc_info.value.code == 1
    stderr = capsys.readouterr().err
    assert "invalid CV_REFRESH_INTERVAL" in stderr
    assert "is not valid" not in stderr
