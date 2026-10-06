"""`settings.yaml::archived: true` freezes a vault's content (spec 071).

An archived vault is finished: its notes are still queried, indexed, digested
and re-graded, and it still takes framework upgrades — but no research cycle
may ever write to it again. The guard is deliberately fail-closed and lives in
the orchestrator, not only the CLI, so *every* caller is covered: a stale shim,
a cron entry, a script, a test harness.

It must refuse BEFORE any side effect. `run_cycles` opens a git branch and
writes a run report early; an archived vault must come away with neither.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from research_framework.pipeline.coverage import save_targets
from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)

ARCHIVED_EXIT = 2


def _budget(max_cycles: int = 5):
    from research_framework.cli._budget_resolve import BudgetResolution

    return BudgetResolution(
        max_cycles=max_cycles,
        max_cycles_source="settings",
        max_usd=10.0,
        max_usd_source="settings",
    )


def _spec(vault_dir: Path) -> SpecConfig:
    return SpecConfig(
        name="archived-test",
        location=vault_dir,
        owner="t",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[
            NoteTypeConfig(
                name="concept",
                description="d",
                folder="01 - Concepts",
                authoritative_role="domain",
            )
        ],
        data_sources=[],
        search_dimensions=["domain"],
        coverage_targets=CoverageTargets(
            categories=[CoverageCategory(name="c", note_type="concept", target_count=1)]
        ),
        budget=BudgetConfig(),
    )


_SETTINGS = """schema_version: 1
{archived}pipeline:
  max_cycles: 5
  budget_usd: 10.0
dimensions: [domain]
"""


def _vault(tmp_path: Path, *, archived: str | None) -> Path:
    vault = tmp_path / "vault"
    (vault / "_pipeline" / "cycles").mkdir(parents=True)
    line = "" if archived is None else f"archived: {archived}\n"
    (vault / "settings.yaml").write_text(_SETTINGS.format(archived=line), "utf-8")
    save_targets(
        vault,
        CoverageTargets(
            categories=[CoverageCategory(name="c", note_type="concept", target_count=1)]
        ),
    )
    return vault


# --------------------------------------------------------------------------
# Settings surface
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [("true", True), ("false", False), (None, False)],
)
def test_settings_exposes_archived(tmp_path: Path, raw, expected: bool) -> None:
    from research_framework.pipeline.settings import load_vault_settings

    vault = _vault(tmp_path, archived=raw)
    assert load_vault_settings(vault).archived is expected


def test_non_boolean_archived_is_rejected(tmp_path: Path) -> None:
    """A typo must not silently read as "not archived" — fail closed."""
    from research_framework.pipeline.settings import SettingsError, load_vault_settings

    vault = _vault(tmp_path, archived="yes-please")
    with pytest.raises(SettingsError):
        load_vault_settings(vault)


# --------------------------------------------------------------------------
# The guard
# --------------------------------------------------------------------------


def test_run_cycles_refuses_on_an_archived_vault(
    tmp_path: Path, monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    from research_framework.pipeline import orchestrator as orch

    vault = _vault(tmp_path, archived="true")
    called: list[int] = []
    monkeypatch.setattr(orch, "run_single_cycle", lambda *a, **k: called.append(1) or 0)

    with caplog.at_level(logging.ERROR):
        rc = orch.run_cycles(_spec(vault), vault, budget=_budget())

    assert rc == ARCHIVED_EXIT
    assert not called, "no cycle may run against an archived vault"
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "archived" in joined.lower()
    assert "settings.yaml" in joined, "the message must say where to change it"


def test_refusal_leaves_no_side_effects(tmp_path: Path, monkeypatch) -> None:
    """No git branch, no run report — it must bail before touching anything."""
    from research_framework.pipeline import orchestrator as orch

    vault = _vault(tmp_path, archived="true")
    opened: list[str] = []
    monkeypatch.setattr(
        orch.vault_commit, "begin_run", lambda *a, **k: opened.append("branch")
    )
    monkeypatch.setattr(orch, "run_single_cycle", lambda *a, **k: 0)

    orch.run_cycles(_spec(vault), vault, budget=_budget())

    assert not opened, "archived guard must precede begin_run"
    assert not (vault / "_pipeline" / "run-report.md").exists()


def test_unarchived_vault_is_unaffected(tmp_path: Path, monkeypatch) -> None:
    """Regression: the common path must not change."""
    from research_framework.pipeline import orchestrator as orch

    vault = _vault(tmp_path, archived="false")
    ran: list[int] = []

    def _cycle(vault_dir, cycle_num, *a, **k):
        ran.append(cycle_num)
        return 2  # abort immediately; we only care that it was reached

    monkeypatch.setattr(orch, "run_single_cycle", _cycle)
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)

    orch.run_cycles(_spec(vault), vault, budget=_budget())
    assert ran, "a non-archived vault must still run cycles"


def test_absent_flag_is_unaffected(tmp_path: Path, monkeypatch) -> None:
    from research_framework.pipeline import orchestrator as orch

    vault = _vault(tmp_path, archived=None)
    ran: list[int] = []
    monkeypatch.setattr(
        orch, "run_single_cycle", lambda v, c, *a, **k: ran.append(c) or 2
    )
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)

    orch.run_cycles(_spec(vault), vault, budget=_budget())
    assert ran


def test_unreadable_settings_do_not_archive_by_accident(
    tmp_path: Path, monkeypatch
) -> None:
    """A broken settings.yaml must not be mistaken for `archived: true`."""
    from research_framework.pipeline import orchestrator as orch

    vault = _vault(tmp_path, archived=None)
    (vault / "settings.yaml").write_text("{{ not yaml", encoding="utf-8")
    ran: list[int] = []
    monkeypatch.setattr(
        orch, "run_single_cycle", lambda v, c, *a, **k: ran.append(c) or 2
    )
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)

    orch.run_cycles(_spec(vault), vault, budget=_budget())
    assert ran, "an unparseable settings.yaml is a different error, not an archive"


# --------------------------------------------------------------------------
# Read paths stay open
# --------------------------------------------------------------------------


def test_read_only_verbs_still_work_on_an_archived_vault(tmp_path: Path) -> None:
    """Archived means frozen, not inaccessible — querying must still work."""
    from research_framework.pipeline.coverage import load_targets
    from research_framework.pipeline.settings import load_vault_settings

    vault = _vault(tmp_path, archived="true")
    assert load_vault_settings(vault).archived is True
    assert load_targets(vault) is not None


def test_archived_is_honoured_even_when_other_settings_are_invalid(
    tmp_path: Path, monkeypatch
) -> None:
    """The promise is "under no circumstance" — it cannot depend on the rest
    of settings.yaml being valid.

    Found on the real codebase-vault: its settings predate spec 061 and carry
    no `pipeline.max_cycles`, so the typed loader raises. An `is_archived` that
    went through that loader swallowed the error and returned False — the flag
    silently did nothing on the exact vault it was added for.
    """
    from research_framework.pipeline import orchestrator as orch

    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    (vault / "settings.yaml").write_text(
        "schema_version: 1\narchived: true\n# no pipeline.max_cycles — invalid\n",
        encoding="utf-8",
    )
    assert orch.is_archived(vault) is True


def test_non_boolean_archived_does_not_freeze_a_vault(tmp_path: Path) -> None:
    """A typo is a settings error, not an archive — the guard must not fire."""
    from research_framework.pipeline import orchestrator as orch

    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    (vault / "settings.yaml").write_text(
        "schema_version: 1\narchived: yes-please\n", encoding="utf-8"
    )
    assert orch.is_archived(vault) is False


def test_missing_settings_file_is_not_archived(tmp_path: Path) -> None:
    from research_framework.pipeline import orchestrator as orch

    vault = tmp_path / "vault"
    vault.mkdir()
    assert orch.is_archived(vault) is False
