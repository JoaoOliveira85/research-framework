"""Spec 083 T012: state-writing verbs refuse a legacy vault; read-only verbs report."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from research_framework.cli import main
from research_framework.pipeline import coverage
from tests._helpers.legacy_layout import (
    build_legacy_vault,
)

REPO = Path(__file__).resolve().parents[2]


def _argv(verb: list[str], vault: Path) -> list[str]:
    out: list[str] = []
    for part in verb:
        out.append(str(vault) if part == "{v}" else part)
    return out


MUTATING = [
    ["generate", "--spec", "{v}/research.spec.md", "--output", "{v}", "--resume"],
    ["cycle", "--vault", "{v}", "--cycle", "3"],
    ["pipeline", "{v}", "full"],
    ["re-grade", "--vault", "{v}"],
    ["ask", "--vault", "{v}", "--escalate", "a question"],
]


@pytest.mark.parametrize(
    "verb", MUTATING, ids=lambda v: v[0] + ("-" + v[2] if v[0] == "pipeline" else "")
)
def test_mutating_verbs_exit_2_naming_the_migration(
    verb: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = build_legacy_vault(tmp_path)
    before = (vault / "_pipeline" / "coverage-targets.json").read_bytes()
    rc = main(_argv(verb, vault))
    err = capsys.readouterr().err
    assert rc == 2
    assert "./vault migrate-layout" in err
    assert (vault / "_pipeline" / "coverage-targets.json").read_bytes() == before
    assert not (vault / "_pipeline" / "state").exists()  # nothing written beside it


def test_health_apply_refuses_and_health_reports(tmp_path: Path) -> None:
    vault = build_legacy_vault(tmp_path)
    script = REPO / "scripts" / "vault_health.py"
    env = {"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"}
    applied = subprocess.run(
        [sys.executable, str(script), str(vault), "--apply", "--offline"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert applied.returncode == 2
    assert "./vault migrate-layout" in applied.stderr
    plain = subprocess.run(
        [sys.executable, str(script), str(vault), "--offline"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert plain.returncode in (0, 1)
    assert "legacy `_pipeline/` layout" in plain.stdout + plain.stderr


def test_status_reports_and_exits_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = build_legacy_vault(tmp_path)
    assert main(["status", "--vault", str(vault), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert (
        "legacy" in doc["legacy_layout"]
        and "./vault migrate-layout" in doc["legacy_layout"]
    )
    assert main(["status", "--vault", str(vault)]) == 0
    assert (
        "legacy `_pipeline/` layout — run `./vault migrate-layout`"
        in capsys.readouterr().out
    )


def test_a_migrated_vault_is_not_refused_or_flagged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from research_framework.pipeline import layout_migration

    vault = build_legacy_vault(tmp_path)
    assert layout_migration.migrate(vault).exit_code == 0
    assert main(["status", "--vault", str(vault), "--json"]) == 0
    assert "legacy_layout" not in json.loads(capsys.readouterr().out)


def test_migrate_layout_and_update_never_refuse(tmp_path: Path) -> None:
    vault = build_legacy_vault(tmp_path)
    assert main(["migrate-layout", "--vault", str(vault), "--dry-run"]) == 0


def test_no_reader_falls_back_to_a_legacy_path(tmp_path: Path) -> None:
    vault = build_legacy_vault(tmp_path)
    assert (vault / "_pipeline" / "coverage-targets.json").is_file()
    with pytest.raises(FileNotFoundError):
        coverage.load_targets(vault)


def test_an_unconverted_backlog_is_refused_like_a_legacy_layout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec 084 FR-020: state moved, Markdown backlog not yet converted."""
    from research_framework.pipeline import layout_migration

    vault = build_legacy_vault(tmp_path)
    step = layout_migration.MOVE_STATE_STEP
    step.apply(vault, step.plan(vault))
    md = vault / "_pipeline" / "research-backlog.md"
    assert md.is_file()
    assert not (vault / "_pipeline" / "state" / "research-backlog.json").exists()

    rc = main(["re-grade", "--vault", str(vault)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "./vault migrate-layout" in err
    assert "_pipeline/research-backlog.md" in err
    assert not (vault / "_pipeline" / "state" / "research-backlog.json").exists()

    # Read-only verbs report it rather than refuse.
    assert main(["status", "--vault", str(vault), "--json"]) == 0
    capsys.readouterr()

    # Migrating converts it, and the verb runs again.
    assert main(["migrate-layout", "--vault", str(vault), "--force"]) == 0
    capsys.readouterr()
    assert main(["re-grade", "--vault", str(vault)]) == 0
