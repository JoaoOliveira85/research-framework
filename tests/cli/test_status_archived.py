"""Issue #26 — `./vault status` says plainly when a vault is archived."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.cli.status import build_status_json, run_status


def _vault(tmp_path: Path, *, archived: bool) -> Path:
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    flag = "archived: true\n" if archived else ""
    (vault / "settings.yaml").write_text(f"schema_version: 1\n{flag}", encoding="utf-8")
    return vault


@pytest.mark.parametrize("archived", [True, False])
def test_status_json_carries_archived(tmp_path: Path, archived: bool) -> None:
    status = build_status_json(_vault(tmp_path, archived=archived))
    assert status["archived"] is archived


def test_status_text_shows_an_archived_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_status(_vault(tmp_path, archived=True))
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("ARCHIVED")
    assert "archived: false" in out, "status must say how to reverse it"


def test_status_text_is_unchanged_for_a_live_vault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_status(_vault(tmp_path, archived=False))
    assert "ARCHIVED" not in capsys.readouterr().out


def test_status_json_output_mode_has_the_flag_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_status(_vault(tmp_path, archived=True), json_output=True)
    assert json.loads(capsys.readouterr().out)["archived"] is True
