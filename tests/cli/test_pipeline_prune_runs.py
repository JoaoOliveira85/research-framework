"""``pipeline <vault> prune-runs`` — spec 080 FR-020 / T008.

Run directories are never pruned automatically, and that is the decision, not
an omission: the record of a bad night is what an operator goes looking for
weeks later, and a framework that deletes it on a schedule deletes the
evidence. This verb is the explicit ask.

Two bounds, both ceilings, the same shape #307 gave research branches so an
operator learns one retention policy rather than two: a directory survives if
it is among the newest ``--keep`` **or** younger than ``--older-than``. It is
removed only when it is outside both.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from research_framework.cli import main
from research_framework.pipeline import run_receipt
from research_framework.pipeline.runner import STATE_FILE, _blank_state, _save_state

_DAY = 86400


def _run(vault: Path, run_id: str, *, age_days: float) -> Path:
    path, _ = run_receipt.ensure_run_dir(vault, run_id)
    assert path is not None
    (path / "run.json").write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
    when = time.time() - age_days * _DAY
    for child in sorted(path.rglob("*"), reverse=True):
        os_utime(child, when)
    os_utime(path, when)
    return path


def os_utime(path: Path, when: float) -> None:
    import os

    os.utime(path, (when, when))


def _vault_with_runs(tmp_path: Path, ages: dict[str, float]) -> Path:
    vault = tmp_path / "vault"
    for run_id, age in ages.items():
        _run(vault, run_id, age_days=age)
    return vault


def _dirs(vault: Path) -> set[str]:
    return {p.name for p in run_receipt.runs_root(vault).iterdir() if p.is_dir()}


def test_prune_keeps_the_newest_n_and_anything_younger_than_the_age(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ages = {f"run-{i:02d}": float(i * 30) for i in range(8)}
    vault = _vault_with_runs(tmp_path, ages)

    rc = main(
        ["pipeline", str(vault), "prune-runs", "--keep", "5", "--older-than", "90"]
    )

    assert rc == 0
    survivors = _dirs(vault)
    # run-00 … run-03 are younger than 90 days; run-00 … run-04 are the newest
    # five. Everything from run-05 on is outside both bounds.
    assert {"run-00", "run-01", "run-02", "run-03", "run-04"} <= survivors
    assert {"run-05", "run-06", "run-07"}.isdisjoint(survivors)
    assert "Removed" in capsys.readouterr().out


def test_age_alone_saves_a_run_the_cap_would_drop(tmp_path: Path) -> None:
    """Each bound is a ceiling in its own right: eight runs from this morning
    are all young, so ``--keep 5`` removes none of them."""
    vault = _vault_with_runs(tmp_path, {f"run-{i}": 0.0 for i in range(8)})

    main(["pipeline", str(vault), "prune-runs", "--keep", "5", "--older-than", "90"])

    assert len(_dirs(vault)) == 8


def test_the_cap_alone_saves_a_run_the_age_would_drop(tmp_path: Path) -> None:
    """And the other way: three ancient runs are all that exist, so the cap
    keeps every one of them."""
    vault = _vault_with_runs(tmp_path, {f"run-{i}": 400.0 for i in range(3)})

    main(["pipeline", str(vault), "prune-runs", "--keep", "5", "--older-than", "90"])

    assert len(_dirs(vault)) == 3


def test_prune_never_removes_the_current_run(tmp_path: Path) -> None:
    """The run the state file names is the one `resume` and `finish` are about
    to write into. Whatever the bounds say, it stays."""
    ages = {f"run-{i:02d}": float(400 + i) for i in range(8)}
    vault = _vault_with_runs(tmp_path, ages)
    _save_state(vault, _blank_state("run-07", "2026-09-10T09:00:00Z"))

    main(["pipeline", str(vault), "prune-runs", "--keep", "1", "--older-than", "1"])

    assert "run-07" in _dirs(vault)


def test_dry_run_deletes_nothing_and_lists_what_it_would(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ages = {f"run-{i:02d}": float(400 + i) for i in range(8)}
    vault = _vault_with_runs(tmp_path, ages)

    rc = main(
        [
            "pipeline",
            str(vault),
            "prune-runs",
            "--keep",
            "2",
            "--older-than",
            "90",
            "--dry-run",
        ]
    )

    assert rc == 0
    assert len(_dirs(vault)) == 8
    out = capsys.readouterr().out
    assert "Would remove" in out
    assert "run-07" in out


def test_nothing_to_prune_is_not_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    rc = main(["pipeline", str(vault), "prune-runs"])

    assert rc == 0
    assert "Nothing to prune" in capsys.readouterr().out


def test_a_negative_bound_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 2 is "usage / abort" in the 077 exit-code model, and the message
    names the flag and the value — the failure #248 found in `digest`."""
    vault = tmp_path / "vault"
    vault.mkdir()

    rc = main(["pipeline", str(vault), "prune-runs", "--keep", "-1"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "--keep" in err and "-1" in err


def test_the_state_file_is_left_alone(tmp_path: Path) -> None:
    """Pruning removes directories under `_pipeline/runs/`, and nothing else.
    `pipeline-state.json` is the join key; deleting it would orphan every
    surviving receipt."""
    vault = _vault_with_runs(
        tmp_path, {f"run-{i:02d}": float(400 + i) for i in range(8)}
    )
    _save_state(vault, _blank_state("run-00", "2026-09-10T09:00:00Z"))

    main(["pipeline", str(vault), "prune-runs", "--keep", "1", "--older-than", "1"])

    assert (vault / STATE_FILE).is_file()
