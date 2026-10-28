"""Issue #26 — `archived: true` is enforced on EVERY research-writing verb.

Spec 071 guarded `run_cycles` and `generate`; the `cycle` verb
(`run_single_cycle`) and the `pipeline` run verbs wrote research content
straight past it. The same refusal now sits above every side effect on those
paths, and read / maintenance verbs stay open.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework import cli

ARCHIVED_EXIT = 2

_PIPELINE_RUN_VERBS = ["full", "collect", "extract", "scout", "resume", "finish"]


def _vault(tmp_path: Path, *, archived: bool = True) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    flag = "archived: true\n" if archived else ""
    (vault / "settings.yaml").write_text(
        f"schema_version: 1\n{flag}pipeline:\n  max_cycles: 5\n  budget_usd: 10.0\n",
        encoding="utf-8",
    )
    return vault


def _files(vault: Path) -> set[str]:
    return {str(p.relative_to(vault)) for p in vault.rglob("*")}


def _assert_refused(
    rc: int, err: str, vault: Path, before: set[str], *, verb: str
) -> None:
    assert rc == ARCHIVED_EXIT, f"{verb}: archived vault must exit 2, got {rc}"
    assert "archived" in err.lower(), f"{verb}: refusal must say why"
    assert "archived: false" in err, f"{verb}: refusal must say how to reverse it"
    assert _files(vault) == before, f"{verb}: refused run left side effects"


# --------------------------------------------------------------------------
# cycle verb
# --------------------------------------------------------------------------


def test_cycle_verb_refuses_an_archived_vault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)
    before = _files(vault)

    rc = cli.main(["cycle", "--vault", str(vault), "--cycle", "1"])

    _assert_refused(rc, capsys.readouterr().err, vault, before, verb="cycle")


def test_cycle_estimate_only_refuses_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pricing a cycle that can never run answers a question nobody can act on."""
    vault = _vault(tmp_path)
    before = _files(vault)

    rc = cli.main(["cycle", "--vault", str(vault), "--cycle", "1", "--estimate-only"])

    _assert_refused(rc, capsys.readouterr().err, vault, before, verb="cycle")


def test_run_single_cycle_is_guarded_for_direct_callers(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """FR2 of spec 071: an invariant, not a CLI courtesy."""
    from research_framework.pipeline.orchestrator import run_single_cycle

    vault = _vault(tmp_path)
    before = _files(vault)
    ran: list[int] = []

    def _stub(*_a: object) -> int:
        ran.append(1)
        return 0

    with caplog.at_level("ERROR"):
        rc = run_single_cycle(vault, 1, cycle_runner=_stub)

    assert rc == ARCHIVED_EXIT
    assert not ran, "no cycle step may run against an archived vault"
    assert _files(vault) == before
    assert "archived" in " ".join(r.getMessage() for r in caplog.records).lower()


def test_run_single_cycle_still_runs_when_not_archived(tmp_path: Path) -> None:
    from research_framework.pipeline.orchestrator import run_single_cycle

    vault = _vault(tmp_path, archived=False)
    ran: list[int] = []

    def _stub(*_a: object) -> int:
        ran.append(1)
        return 0

    run_single_cycle(vault, 1, budget_cap=1.0, max_cycles=1, cycle_runner=_stub)
    assert ran, "regression: the common path must be untouched"


# --------------------------------------------------------------------------
# pipeline run verbs
# --------------------------------------------------------------------------


@pytest.mark.parametrize("verb", _PIPELINE_RUN_VERBS)
def test_pipeline_cli_verb_refuses_an_archived_vault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], verb: str
) -> None:
    vault = _vault(tmp_path)
    before = _files(vault)

    rc = cli.main(["pipeline", str(vault), verb])

    _assert_refused(rc, capsys.readouterr().err, vault, before, verb=f"pipeline {verb}")


@pytest.mark.parametrize("verb", _PIPELINE_RUN_VERBS)
def test_pipeline_runner_is_guarded_for_direct_callers(
    tmp_path: Path, verb: str
) -> None:
    from research_framework.pipeline import runner

    vault = _vault(tmp_path)
    before = _files(vault)

    rc = getattr(runner, f"run_{verb}")(vault)

    assert rc == ARCHIVED_EXIT
    assert _files(vault) == before


def test_pipeline_budget_cap_refusal_does_not_outrank_archived(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The operator should read "archived", not an unrelated flag complaint."""
    vault = _vault(tmp_path)

    rc = cli.main(["pipeline", str(vault), "full", "--budget-cap", "5"])

    assert rc == ARCHIVED_EXIT
    assert "archived" in capsys.readouterr().err.lower()


# --------------------------------------------------------------------------
# generate --regenerate-plan-only writes _pipeline/research-plan.md
# --------------------------------------------------------------------------


def test_generate_regenerate_plan_only_refuses_an_archived_vault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)
    before = _files(vault)

    rc = cli.main(["generate", "--regenerate-plan-only", "--output", str(vault)])

    _assert_refused(
        rc,
        capsys.readouterr().err,
        vault,
        before,
        verb="generate --regenerate-plan-only",
    )


# --------------------------------------------------------------------------
# Read / maintenance verbs stay open
# --------------------------------------------------------------------------


def test_pipeline_status_and_prune_runs_work_on_an_archived_vault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)

    assert cli.main(["pipeline", str(vault), "status"]) == 0
    assert cli.main(["pipeline", str(vault), "prune-runs", "--dry-run"]) == 0
    assert "archived" not in capsys.readouterr().err.lower()


def test_unarchived_vault_is_not_refused(tmp_path: Path) -> None:
    from research_framework.pipeline.archived import archived_refusal_message

    assert archived_refusal_message(_vault(tmp_path, archived=False)) is None


# --------------------------------------------------------------------------
# One message, one place
# --------------------------------------------------------------------------


def test_the_refusal_text_names_vault_survivors_and_the_reversal(
    tmp_path: Path,
) -> None:
    from research_framework.pipeline.archived import archived_refusal_message

    vault = _vault(tmp_path)
    msg = archived_refusal_message(vault)
    assert msg is not None
    assert str(vault) in msg
    assert "archived: false" in msg
    assert "settings.yaml" in msg
    assert "./vault ask" in msg and "./vault update" in msg
