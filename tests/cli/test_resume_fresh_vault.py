"""`--resume` on a fresh vault must start at cycle 1, not error (issue #150).

`--resume` is the documented happy-path verb — "safe to re-run if interrupted".
On a brand-new scaffold it did the opposite of safe: it hard-errored with
`no in-progress cycle found; use --cycle <N> to specify`, which is exactly the
moment an operator is least sure what is going on. The rc7 reference-vault
validation hit it on its very first invocation and the staging script grew a
workaround that injected `--cycle 1` — doing by hand what `--resume` is for.

Resolution order is unchanged; this only replaces the final hard error with the
obvious answer when there is genuinely nothing on disk yet.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pytest

from research_framework.cli.research_resume import _resolve_resume_cycle


def _args(vault: Path) -> argparse.Namespace:
    return argparse.Namespace(output=vault, cycle=None)


def _vault(tmp_path: Path) -> Path:
    v = tmp_path / "vault"
    (v / "_pipeline" / "cycles").mkdir(parents=True)
    return v


def test_fresh_scaffold_starts_at_cycle_one(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """No state.json, no cycles on disk — the issue #150 case."""
    vault = _vault(tmp_path)
    with caplog.at_level(logging.INFO):
        assert _resolve_resume_cycle(_args(vault)) == 1
    assert "cycle 1" in " ".join(r.getMessage() for r in caplog.records).lower()


def test_state_json_with_null_in_progress_and_no_cycles(tmp_path: Path) -> None:
    """A scaffold that wrote state.json but never ran is the same case."""
    vault = _vault(tmp_path)
    (vault / "_pipeline" / "state.json").write_text(
        json.dumps({"in_progress_cycle": None}), encoding="utf-8"
    )
    assert _resolve_resume_cycle(_args(vault)) == 1


def test_missing_pipeline_dir_entirely(tmp_path: Path) -> None:
    vault = tmp_path / "bare"
    vault.mkdir()
    assert _resolve_resume_cycle(_args(vault)) == 1


def test_in_progress_cycle_still_wins(tmp_path: Path) -> None:
    """Regression: resolution order 1 is unchanged."""
    vault = _vault(tmp_path)
    (vault / "_pipeline" / "state.json").write_text(
        json.dumps({"in_progress_cycle": 4}), encoding="utf-8"
    )
    assert _resolve_resume_cycle(_args(vault)) == 4


def test_completed_cycles_still_advance(tmp_path: Path) -> None:
    """Regression: resolution order 2 is unchanged."""
    vault = _vault(tmp_path)
    for n in (1, 2):
        (
            vault / "_pipeline" / "cycles" / f"cycle-{n:03d}-quality-report.json"
        ).write_text("{}", encoding="utf-8")
    assert _resolve_resume_cycle(_args(vault)) == 3


def test_a_lone_aborted_cycle_retries_it(tmp_path: Path) -> None:
    """Spec 070 F10 + issue #150 together: cycle 1 aborted and is the only one,
    so there is no completed cycle — resume must retry 1, not error."""
    from research_framework.pipeline.orchestrator import mark_cycle_aborted

    vault = _vault(tmp_path)
    (vault / "_pipeline" / "cycles" / "cycle-001-quality-report.json").write_text(
        "{}", encoding="utf-8"
    )
    mark_cycle_aborted(vault, 1, reason="aborted")
    assert _resolve_resume_cycle(_args(vault)) == 1


def test_corrupt_state_json_still_errors(tmp_path: Path) -> None:
    """Regression: a corrupt state file is a real error, not a fresh vault."""
    vault = _vault(tmp_path)
    (vault / "_pipeline" / "state.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit):
        _resolve_resume_cycle(_args(vault))
