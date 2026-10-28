"""Issue #26 — `archived: true` is enforced on EVERY research-writing verb.

Spec 071 guarded `run_cycles` and `generate`; the `cycle` verb
(`run_single_cycle`) and the `pipeline` run verbs wrote research content
straight past it. The same refusal now sits above every side effect on those
paths, and read / maintenance verbs stay open.
"""

from __future__ import annotations

import hashlib
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


def _legacy_vault(tmp_path: Path) -> Path:
    """Spec 071 FR4: a pre-spec-061 settings file — the flag and nothing else.

    The typed loader raises on this (no `pipeline.max_cycles`), which is
    exactly the vault the flag was written for.
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text("archived: true\n", encoding="utf-8")
    return vault


def _files(vault: Path) -> dict[str, str | None]:
    """``{relative path: sha256}`` — a modified file is a side effect too."""
    return {
        str(p.relative_to(vault)): (
            hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
        )
        for p in vault.rglob("*")
    }


def _assert_refused(
    rc: int, err: str, vault: Path, before: dict[str, str | None], *, verb: str
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


# --------------------------------------------------------------------------
# FR4 / FR5: the flag holds when the rest of settings does not
# --------------------------------------------------------------------------


def test_cycle_verb_refuses_a_legacy_settings_vault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _legacy_vault(tmp_path)
    before = _files(vault)

    rc = cli.main(["cycle", "--vault", str(vault), "--cycle", "1"])

    _assert_refused(rc, capsys.readouterr().err, vault, before, verb="cycle (legacy)")


def test_pipeline_verb_refuses_a_legacy_settings_vault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _legacy_vault(tmp_path)
    before = _files(vault)

    rc = cli.main(["pipeline", str(vault), "full"])

    _assert_refused(
        rc, capsys.readouterr().err, vault, before, verb="pipeline full (legacy)"
    )


@pytest.mark.parametrize("literal", ['"true"', "yes-please", "1", "'yes'"])
def test_only_a_boolean_true_archives(tmp_path: Path, literal: str) -> None:
    """FR5: strings and typos are a settings error, never an accidental freeze."""
    from research_framework.pipeline.archived import is_archived

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(f"archived: {literal}\n", encoding="utf-8")
    assert is_archived(vault) is False


def test_yaml_boolean_spelling_of_true_archives(tmp_path: Path) -> None:
    """`yes` is a YAML 1.1 boolean: PyYAML reads it as `true`, and so does the
    typed loader. Pinned so the two readers cannot drift apart."""
    from research_framework.pipeline.archived import is_archived
    from research_framework.pipeline.settings import load_vault_settings

    vault = _vault(tmp_path, archived=False)
    settings = vault / "settings.yaml"
    settings.write_text(
        "archived: yes\n" + settings.read_text(encoding="utf-8"), encoding="utf-8"
    )
    assert is_archived(vault) is True
    assert load_vault_settings(vault).archived is True


# --------------------------------------------------------------------------
# Archived mid-run (the flag flips while run_cycles is looping)
# --------------------------------------------------------------------------


def test_run_cycles_stops_cleanly_when_archived_between_cycles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from research_framework.pipeline import orchestrator as orch
    from tests.pipeline.test_archived_vault import _budget, _spec
    from tests.pipeline.test_archived_vault import _vault as _rc_vault

    vault = _rc_vault(tmp_path, archived="false")
    cycles: list[int] = []

    def _cycle(_vault_dir, cycle_num, *_a, **_k):
        cycles.append(cycle_num)
        # The operator archives the vault while cycle 1 is running.
        (vault / "settings.yaml").write_text(
            "archived: true\n"
            + (vault / "settings.yaml")
            .read_text(encoding="utf-8")
            .replace("archived: false\n", ""),
            encoding="utf-8",
        )
        return 0

    monkeypatch.setattr(orch, "run_single_cycle", _cycle)
    monkeypatch.setattr(orch, "_scout_new_topics", lambda *_a: ["more-work"])
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)

    rc = orch.run_cycles(_spec(vault), vault, budget=_budget(max_cycles=5))

    assert rc == ARCHIVED_EXIT
    assert cycles == [1], "no cycle may start once the vault is archived"
    assert not list((vault / "_pipeline").glob("**/*aborted*")), (
        "an archive is not a structural abort: no aborted marker"
    )


# --------------------------------------------------------------------------
# generate with no --output: the vault comes from settings / the spec
# --------------------------------------------------------------------------


@pytest.mark.parametrize("route", ["settings-output-dir", "spec-location"])
def test_fresh_generate_without_output_refuses_before_scaffolding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], route: str
) -> None:
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    spec_file = spec_dir / "research.spec.md"
    spec_location = tmp_path / "vault-from-spec"
    example = (Path(__file__).parents[2] / "examples" / "research.spec.md").read_text(
        encoding="utf-8"
    )
    assert "location: /Users/jdoe/Documents/macro-film-vault" in example
    spec_file.write_text(
        example.replace(
            "location: /Users/jdoe/Documents/macro-film-vault",
            f"location: {spec_location}",
        ),
        encoding="utf-8",
    )

    argv = ["generate", "--spec", str(spec_file)]
    if route == "settings-output-dir":
        vault = tmp_path / "vault-from-settings"
        profile = tmp_path / "profile.yaml"
        profile.write_text(f"output_dir: {vault}\n", encoding="utf-8")
        argv += ["--settings", str(profile)]
    else:
        vault = spec_location
    vault.mkdir(parents=True)
    (vault / "settings.yaml").write_text("archived: true\n", encoding="utf-8")
    before = _files(vault)

    rc = cli.main(argv)

    _assert_refused(
        rc, capsys.readouterr().err, vault, before, verb=f"generate ({route})"
    )
    assert not (vault / "data_vault").exists(), "scaffold must not have run"
