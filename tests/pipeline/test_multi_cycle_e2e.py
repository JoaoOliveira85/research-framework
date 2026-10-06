"""Tier-5 multi-cycle end-to-end tests (feature 018, US3).

Drives the real ``research_framework.pipeline.orchestrator.run_cycles`` for
3 cycles back-to-back against a vault built by ``vault_factory``. Tests
the **cycle-to-cycle state transfer surfaces** — the next class of seam
bug we expect to bite once the user runs past cycle 1 in production.

Spec: ``specs/018-testing-strategy/spec.md`` § US3.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.orchestrator import run_single_cycle
from research_framework.spec.schema import SpecConfig
from tests._helpers.vault_factory import build_minimal_vault

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_spec(vault: Path) -> SpecConfig:
    parse = json.loads(
        (vault / "_pipeline" / "spec-parse.json").read_text(encoding="utf-8")
    )
    return SpecConfig.from_dict(parse)


def _coverage_met_per_cycle(vault: Path) -> list[dict]:
    """Snapshot ``met_count`` per category for every cycle quality report."""
    cdir = vault / "_pipeline" / "cycles"
    snapshots: list[dict] = []
    for qr in sorted(cdir.glob("cycle-*-quality-report.json")):
        doc = json.loads(qr.read_text(encoding="utf-8"))
        snap = doc.get("coverage_snapshot") or []
        snapshots.append(
            {
                row["name"]: int(row.get("met", 0))
                for row in snap
                if isinstance(row, dict)
            }
        )
    return snapshots


def _run_cycles_inline(
    vault: Path, *, n_cycles: int, spec: SpecConfig, max_cycles: int
) -> list[int]:
    """Iterate ``run_single_cycle`` ourselves so the test can assert per-cycle
    state without relying on ``run_cycles`` short-circuiting on the
    "successful exit" / "source-exhausted" triggers (which mock vaults
    can hit before they meant to).

    Each cycle goes through the same orchestrator wrapper that
    production uses — coverage update, quality report, narrative
    rendering — so cycle-to-cycle state is exercised identically.
    """
    rcs: list[int] = []
    for n in range(1, n_cycles + 1):
        rc = run_single_cycle(
            vault,
            cycle_num=n,
            budget_cap=10.0,
            max_cycles=max_cycles,
            spec=spec,
        )
        rcs.append(rc)
        if rc == 2:
            break
    return rcs


def _notes_with_lifecycle(vault: Path) -> list[tuple[str, int]]:
    """Return ``(filename, created_at_cycle)`` for every data_vault note."""
    import yaml

    out: list[tuple[str, int]] = []
    dv = vault / "data_vault"
    if not dv.is_dir():
        return out
    for p in sorted(dv.rglob("*.md")):
        if p.name in ("_index.md", "_concepts.md", "_graph.md"):
            continue
        if "_templates" in p.parts:
            continue
        text = p.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        try:
            fm = yaml.safe_load(text.split("---", 2)[1]) or {}
        except yaml.YAMLError:
            continue
        cycle = int(((fm.get("lifecycle") or {}).get("created_at_cycle")) or 0)
        out.append((p.name, cycle))
    return out


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def test_three_cycles_progress_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three clean cycles must produce three quality reports and monotonic coverage."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    vault = build_minimal_vault(
        tmp_path,
        num_categories=2,
        num_targets_per_category=2,  # 4 targets total → fewer notes per cycle
        max_cycles=3,
    )
    spec = _read_spec(vault)

    rcs = _run_cycles_inline(vault, n_cycles=3, spec=spec, max_cycles=3)
    assert all(rc in (0, 1) for rc in rcs), f"unexpected exit codes: {rcs}"
    assert len(rcs) == 3, f"expected three cycles to run; got {rcs}"

    cdir = vault / "_pipeline" / "cycles"
    for n in (1, 2, 3):
        assert (cdir / f"cycle-{n:03d}-scout.json").is_file(), (
            f"missing scout for cycle {n}"
        )
        assert (cdir / f"cycle-{n:03d}-research.json").is_file(), (
            f"missing research for cycle {n}"
        )
        assert (cdir / f"cycle-{n:03d}-quality-report.json").is_file(), (
            f"missing quality report for cycle {n}"
        )

    snapshots = _coverage_met_per_cycle(vault)
    assert len(snapshots) >= 3, snapshots
    for cat in snapshots[0]:
        for i in range(1, len(snapshots)):
            assert snapshots[i].get(cat, 0) >= snapshots[i - 1].get(cat, 0), (
                f"category {cat!r} regressed between cycles {i} and {i + 1}: "
                f"{snapshots[i - 1].get(cat)} → {snapshots[i].get(cat)}"
            )


def test_cycle_two_picks_up_where_cycle_one_left_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No note from cycle 1 must be overwritten by cycle 2; new notes come from
    the remaining gaps."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    vault = build_minimal_vault(
        tmp_path,
        num_categories=2,
        num_targets_per_category=2,
        max_cycles=2,
    )
    spec = _read_spec(vault)

    rc1 = run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=2, spec=spec)
    assert rc1 in (0, 1)
    notes_after_c1 = _notes_with_lifecycle(vault)
    assert notes_after_c1, "no notes after cycle 1"
    c1_names = {name for name, _ in notes_after_c1}

    rc2 = run_single_cycle(vault, cycle_num=2, budget_cap=10.0, max_cycles=2, spec=spec)
    assert rc2 in (0, 1)

    notes_after_c2 = _notes_with_lifecycle(vault)
    assert len(notes_after_c2) >= len(notes_after_c1), (
        "cycle 2 produced no new notes (or shrank data_vault)"
    )

    for name, cycle in notes_after_c2:
        if name in c1_names:
            assert cycle == 1, (
                f"{name} was created in cycle 1 but its lifecycle.created_at_cycle "
                f"is now {cycle} — cycle 2 overwrote the frontmatter."
            )


def test_correction_loop_across_cycles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cycle 1 fails frontmatter on the first batch (SG-005); cycle 2 succeeds clean.

    This exercises the cross-cycle correction surface — the correction
    directive from cycle 1's failing batch is in the cycle-1 batch
    sidecars but must NOT persist into cycle 2's prompts.
    """
    monkeypatch.setenv("FAKE_AGENT_SCOUT_SCENARIO", "happy")
    monkeypatch.setenv("FAKE_AGENT_NOTE_WRITER_SCENARIO", "fail_frontmatter")
    vault = build_minimal_vault(
        tmp_path,
        num_categories=2,
        num_targets_per_category=2,
        max_cycles=2,
        note_writer_batch_size=3,
    )
    spec = _read_spec(vault)

    rc1 = run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=2, spec=spec)
    assert rc1 in (0, 1, 2), rc1

    batches_c1 = sorted((vault / "_pipeline" / "cycles").glob("cycle-001-batch-*.json"))
    assert batches_c1, "cycle 1 produced no batch reports"
    first = json.loads(batches_c1[0].read_text(encoding="utf-8"))
    sg005 = next(
        (
            g
            for g in (first.get("sg_gate_results") or [])
            if g.get("gate_id") == "SG-005"
        ),
        None,
    )
    assert sg005 is not None and sg005.get("status") == "FAIL", (
        f"expected cycle 1 first batch SG-005 FAIL; got {sg005}"
    )

    monkeypatch.delenv("FAKE_AGENT_NOTE_WRITER_SCENARIO", raising=False)
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    rc2 = run_single_cycle(vault, cycle_num=2, budget_cap=10.0, max_cycles=2, spec=spec)
    assert rc2 in (0, 1), rc2

    batches_c2 = sorted((vault / "_pipeline" / "cycles").glob("cycle-002-batch-*.json"))
    assert batches_c2, "cycle 2 produced no batch reports"
    last_c2 = json.loads(batches_c2[-1].read_text(encoding="utf-8"))
    sg005_c2 = next(
        (
            g
            for g in (last_c2.get("sg_gate_results") or [])
            if g.get("gate_id") == "SG-005"
        ),
        None,
    )
    if sg005_c2 is not None:
        assert sg005_c2.get("status") != "FAIL", (
            f"cycle 2 final batch SG-005 unexpectedly failed: {sg005_c2}"
        )
