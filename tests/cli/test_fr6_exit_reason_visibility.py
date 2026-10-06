"""Spec 070 FR6 on the orchestrator's own rc=1 paths (issue #242).

FR6 asks that "every non-zero exit MUST write a diagnosable message to
stderr". The blanket backstop in ``cli.main`` shipped; the paths that
actually produce rc=1 did not follow. Three of them:

* ``_constrained_exit`` narrated its reason and its punch list entirely at
  ``INFO``;
* the source-exhausted exit did the same;
* ``_resume``'s precondition rejection and ``_run_phase3``'s gate rejections
  went to **stdout**.

``_log_level`` FR-005 drops the level to ``WARNING`` whenever stdout is not a
TTY — i.e. on every cron/launchd/systemd run — so all of it was invisible on
stderr in exactly the mode the framework is built for. The tests below assert
the stream and the severity, never the wording, so they cannot rot when the
message is reworded.
"""

from __future__ import annotations

import argparse
import json
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


def _loud(caplog: pytest.LogCaptureFixture) -> str:
    """Everything the operator would still see under the non-TTY default."""
    return " ".join(
        r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
    )


# ---------------------------------------------------------------------------
# _constrained_exit — the punch list is the operator's whole remedy
# ---------------------------------------------------------------------------


def test_constrained_exit_reason_and_punch_list_survive_the_warning_default(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from research_framework.pipeline.orchestrator import _constrained_exit

    with caplog.at_level(logging.DEBUG):
        rc = _constrained_exit(
            tmp_path,
            reason="budget cap reached ($4.0100 ≥ $4.00)",
            new_topics=["topic-a", "topic-b"],
            followups=[{"title": "orphan"}],
            stubs_count=3,
            health_count=2,
            coverage_met=True,
        )

    assert rc == 1
    visible = _loud(caplog)
    assert "budget cap reached" in visible, "the exit reason itself was INFO-only"
    for fragment in ("2 new topic", "1 orphan wikilink", "3 stub", "2 unresolved"):
        assert fragment in visible, f"punch-list entry {fragment!r} was INFO-only"
    assert "--max-cycles" in visible, "the remedy line was INFO-only"


def test_constrained_exit_names_the_unmet_coverage_categories_loudly(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The unmet-coverage branch reads the vault, so it gets its own case."""
    from research_framework.pipeline.orchestrator import _constrained_exit

    save_targets(
        tmp_path,
        CoverageTargets(
            categories=[
                CoverageCategory(
                    name="services", note_type="service", target_count=3, met_count=1
                )
            ]
        ),
    )

    with caplog.at_level(logging.DEBUG):
        _constrained_exit(
            tmp_path,
            reason="max_cycles (2) reached",
            new_topics=[],
            followups=[],
            stubs_count=0,
            health_count=0,
            coverage_met=False,
        )

    assert "services" in _loud(caplog)


# ---------------------------------------------------------------------------
# The source-exhausted exit — rc=1 through run_cycles itself
# ---------------------------------------------------------------------------


def _spec(vault_dir: Path) -> SpecConfig:
    return SpecConfig(
        name="fr6-test",
        location=vault_dir,
        owner="test",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[
            NoteTypeConfig(
                name="service",
                description="d",
                folder="01 - Services",
                authoritative_role="behaviour",
            )
        ],
        data_sources=[],
        search_dimensions=["domain"],
        coverage_targets=CoverageTargets(
            categories=[
                CoverageCategory(name="services", note_type="service", target_count=3)
            ]
        ),
        budget=BudgetConfig(),
    )


def _budget(max_cycles: int):
    from research_framework.cli._budget_resolve import BudgetResolution

    return BudgetResolution(
        max_cycles=max_cycles,
        max_cycles_source="--max-cycles",
        max_usd=12.0,
        max_usd_source="--max-usd",
    )


def test_source_exhausted_exit_is_visible_under_the_warning_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """No fuel left and coverage unmet: rc=1, and the reason must be loud."""
    from research_framework.pipeline import orchestrator as orch

    vault = tmp_path / "vault"
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    save_targets(
        vault,
        CoverageTargets(
            categories=[
                CoverageCategory(
                    name="services", note_type="service", target_count=3, met_count=0
                )
            ]
        ),
    )

    def _one_dry_cycle(
        vault_dir, cycle_num, budget_cap, max_cycles, spec=None, resume=False
    ):
        (cycles / f"cycle-{cycle_num:03d}-scout.json").write_text(
            json.dumps({"topics_found": {"new": []}}), encoding="utf-8"
        )
        return 0

    monkeypatch.setattr(orch, "run_single_cycle", _one_dry_cycle)
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)
    monkeypatch.setattr(orch, "_run_health_gate", lambda _v: [])
    monkeypatch.setattr(orch, "scan_stubs", lambda _v, _s: [])

    with caplog.at_level(logging.DEBUG):
        rc = orch.run_cycles(_spec(vault), vault, start_cycle=1, budget=_budget(1))

    assert rc == 1
    visible = _loud(caplog)
    assert "services" in visible, "the unmet category list was INFO-only"
    assert "data_sources" in visible, "the remedy line was INFO-only"


# ---------------------------------------------------------------------------
# _resume — the precondition rejection
# ---------------------------------------------------------------------------


def test_resume_precondition_rejection_goes_to_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from research_framework import cli
    from research_framework.cli import research_resume
    from research_framework.pipeline import preconditions

    monkeypatch.setattr(cli, "load_spec", lambda *a, **k: object())
    monkeypatch.setattr(cli, "validate", lambda _s: None)
    monkeypatch.setattr(
        preconditions,
        "check",
        lambda *a, **k: (False, ["precondition 3: coverage-targets.json missing"]),
    )

    args = argparse.Namespace(
        output=tmp_path, spec=None, legacy_cycle_runner=False, cycle=None
    )
    rc = research_resume._resume(args)

    captured = capsys.readouterr()
    assert rc == 1
    assert "precondition 3" in captured.err, "FR6: the rejection must reach stderr"
    assert "precondition 3" not in captured.out


# ---------------------------------------------------------------------------
# _run_phase3 — the two finalisation gates
# ---------------------------------------------------------------------------


def test_phase3_coverage_gate_rejection_goes_to_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from research_framework.cli import research_phase3
    from research_framework.pipeline import coverage

    monkeypatch.setattr(coverage, "all_targets_met", lambda _v: False)
    monkeypatch.setattr(coverage, "unmet_targets", lambda _v: ["services: 1/3"])

    rc = research_phase3._run_phase3(argparse.Namespace(name="v"), tmp_path)

    captured = capsys.readouterr()
    assert rc == 1
    assert "services: 1/3" in captured.err, "FR6: the gate rejection must reach stderr"
    assert "services: 1/3" not in captured.out


def test_phase3_code_first_gate_rejection_goes_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The second gate is a subprocess; only the framework's own text is checked."""
    from research_framework.cli.research_phase3 import _phase3_code_first_gate

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "check_intent_drift.py").write_text(
        "import sys\nsys.exit(1)\n", encoding="utf-8"
    )

    rc = _phase3_code_first_gate(tmp_path)

    captured = capsys.readouterr()
    assert rc == 1
    assert "FAILED" in captured.err, "FR6: the gate rejection must reach stderr"
    assert "FAILED" not in captured.out


# ---------------------------------------------------------------------------
# Verbs whose legitimate non-zero exit said why on stdout only (spec 077
# FR-017). The CLI's backstop counts stderr and ERROR records, so each of
# these exits came out with the "framework bug" apology attached to a reason
# it had in fact given — on the stream an unattended run redirects away.
# ---------------------------------------------------------------------------

_APOLOGY = "framework bug"


def _main(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    from research_framework import cli

    rc = cli.main(argv)
    return rc, capsys.readouterr().err


def test_coverage_with_unmet_targets_says_why_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    save_targets(
        tmp_path,
        CoverageTargets(
            categories=[
                CoverageCategory(
                    name="services", note_type="service", target_count=3, met_count=1
                )
            ]
        ),
    )

    rc, err = _main(["coverage", "--vault", str(tmp_path)], capsys)

    assert rc == 1
    assert "services" in err, "FR-017: the unmet category is the reason for rc=1"
    assert _APOLOGY not in err


def test_acceptance_with_a_failing_gate_says_why_on_stderr(
    snapshot_vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from research_framework.cli.acceptance import build_scorecard

    failing = [
        g["gate_id"]
        for g in build_scorecard(snapshot_vault)["generic_gates"]
        if g["status"] == "FAIL"
    ]
    assert failing, "fixture precondition: the snapshot has FAIL gates"

    rc, err = _main(["acceptance", "--vault", str(snapshot_vault), "--json"], capsys)

    assert rc == 1
    for gate_id in failing:
        assert gate_id in err, f"FR-017: failing gate {gate_id} is the reason"
    assert _APOLOGY not in err


def test_onboard_abort_says_why_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = tmp_path / "vault"
    (vault / "Tech Notes").mkdir(parents=True)
    (vault / "Business Notes").mkdir()

    rc, err = _main(["onboard", str(vault), "--no-git"], capsys)

    assert rc == 2
    assert "Aborted at step 2" in err
    assert "multiple candidate" in err.lower(), "FR-017: the abort's reason"
    assert _APOLOGY not in err


def test_onboard_stop_for_spec_review_says_why_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = tmp_path / "vault"
    (vault / "Tech Notes").mkdir(parents=True)
    (vault / "Tech Notes" / "note.md").write_text("# Note\n", encoding="utf-8")

    rc, err = _main(["onboard", str(vault), "--no-git"], capsys)

    assert rc == 1
    assert "Stopped at step 3" in err
    assert _APOLOGY not in err


def _refresh_vault(tmp_path: Path, collectors: list[str] | None) -> Path:
    """A vault whose ``.venv`` python is this interpreter, so collectors run."""
    import sys

    vault = tmp_path / "vault"
    (vault / "scripts").mkdir(parents=True)
    (vault / ".venv" / "bin").mkdir(parents=True)
    (vault / ".venv" / "bin" / "python").symlink_to(sys.executable)
    settings = "pipeline:\n  max_cycles: 1\n  budget_usd: 1.0\n"
    if collectors is not None:
        settings += f"refresh_sources:\n  collectors: [{', '.join(collectors)}]\n"
    (vault / "settings.yaml").write_text(settings, encoding="utf-8")
    return vault


@pytest.fixture
def _no_host_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """The host checks probe the network; nothing here is about them."""
    from research_framework.cli import refresh_sources

    monkeypatch.setattr(refresh_sources, "_host_checks", lambda _vault: [])


@pytest.mark.usefixtures("_no_host_checks")
def test_refresh_sources_partial_failure_says_why_on_stderr_under_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _refresh_vault(tmp_path, ["collect_ok.py", "collect_bad.py"])
    (vault / "scripts" / "collect_ok.py").write_text("", encoding="utf-8")
    (vault / "scripts" / "collect_bad.py").write_text(
        "import sys\nsys.exit(3)\n", encoding="utf-8"
    )

    rc, err = _main(["refresh-sources", "--vault", str(vault), "--json"], capsys)

    assert rc == 1
    assert "collect_bad.py" in err, "FR-017: the failed collector is the reason"
    assert _APOLOGY not in err


@pytest.mark.usefixtures("_no_host_checks")
def test_refresh_sources_with_no_collectors_says_why_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _refresh_vault(tmp_path, None)

    rc, err = _main(["refresh-sources", "--vault", str(vault), "--dry-run"], capsys)

    assert rc == 2
    assert "no collector" in err.lower(), "FR-017: there was nothing to run"
    assert _APOLOGY not in err
