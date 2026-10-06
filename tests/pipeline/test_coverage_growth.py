"""coverage.grow_targets_if_met — a run is a request for MORE.

`target_count` was read as a lifetime ceiling, so a vault that reached it was
finished forever: feeds-vault held 441 notes against a 55-note target, computed a
remaining of 1, and planned `cycle_quota: 2` while its own scout surfaced
current material the plan discarded. These tests pin the four decisions that
fix without over-firing: grow only when everything is met, never when archived,
never at the default factor, and always by at least one note.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.coverage import grow_targets_if_met, load_targets


def _vault(tmp_path: Path, cats: list[tuple[str, int, int]]) -> Path:
    v = tmp_path / "v"
    (v / "_pipeline").mkdir(parents=True)
    (v / "_pipeline" / "coverage-targets.json").write_text(
        json.dumps(
            {
                "categories": [
                    {
                        "name": n,
                        "note_type": "concept",
                        "target_count": t,
                        "met_count": m,
                        "required": True,
                    }
                    for n, t, m in cats
                ]
            }
        ),
        encoding="utf-8",
    )
    return v


def test_a_met_vault_grows_by_the_factor(tmp_path):
    v = _vault(tmp_path, [("a", 5, 5), ("b", 10, 12)])
    grown, old, new = grow_targets_if_met(v, growth=1.5)
    assert grown
    assert (old, new) == (15, 26)  # ceil(5*1.5)=8, ceil(12*1.5)=18
    after = {c.name: c.target_count for c in load_targets(v).categories}
    assert after == {"a": 8, "b": 18}


def test_growth_compounds_across_rounds(tmp_path):
    """Each round multiplies a LARGER base — exponential, not a fixed step."""
    v = _vault(tmp_path, [("a", 10, 10)])
    grow_targets_if_met(v, growth=1.5)
    assert load_targets(v).categories[0].target_count == 15
    # the vault fills the new bar, then grows again from 15, not from 10
    cats = load_targets(v)
    cats.categories[0].met_count = 15
    (v / "_pipeline" / "coverage-targets.json").write_text(
        json.dumps(cats.to_dict()), encoding="utf-8"
    )
    grow_targets_if_met(v, growth=1.5)
    assert load_targets(v).categories[0].target_count == 23  # ceil(15*1.5)


def test_a_vault_with_work_left_is_untouched(tmp_path):
    """Growth is for a FINISHED vault. One unmet category means there is
    already work, and moving the bar mid-round would make it unreachable."""
    v = _vault(tmp_path, [("a", 5, 5), ("b", 10, 3)])
    grown, old, new = grow_targets_if_met(v, growth=2.0)
    assert not grown and old == new == 15
    assert [c.target_count for c in load_targets(v).categories] == [5, 10]


def test_an_archived_vault_never_grows(tmp_path):
    """spec 071's flag means finished; an operator who archived a vault did
    not ask for more of it."""
    v = _vault(tmp_path, [("a", 5, 5)])
    grown, _, _ = grow_targets_if_met(v, growth=3.0, archived=True)
    assert not grown
    assert load_targets(v).categories[0].target_count == 5


@pytest.mark.parametrize("factor", [None, 1.0, 0.5])
def test_default_and_non_growing_factors_are_one_and_done(tmp_path, factor):
    """Absent or <= 1.0 keeps today's behaviour exactly, so every existing
    vault is unaffected until it opts in."""
    v = _vault(tmp_path, [("a", 5, 5)])
    grown, old, new = grow_targets_if_met(v, growth=factor)
    assert not grown and old == new == 5


def test_a_small_target_always_gains_at_least_one(tmp_path):
    """ceil(1 * 1.2) == 2, but ceil(1 * 1.0001) == 1 would stall the vault
    forever on a category of one."""
    v = _vault(tmp_path, [("a", 1, 1)])
    grown, _, new = grow_targets_if_met(v, growth=1.0001)
    assert grown and new == 2


def test_growth_counts_from_what_the_vault_HOLDS_not_its_old_target(tmp_path):
    """The feeds-vault case: 441 notes behind a 55-note target. Growing the target
    rather than the holdings would leave it starved for another round."""
    # cap lifted so this isolates the "measures from held notes" property
    v = _vault(tmp_path, [("a", 5, 60)])
    _, _, new = grow_targets_if_met(v, growth=1.2, cap=99)
    assert new == 72  # ceil(60 * 1.2), not ceil(5 * 1.2)


# --- the cap: "exponential" was never meant literally ------------------------


def test_a_large_category_grows_linearly_not_by_percentage(tmp_path):
    """1.4 on a 200-note category is +80. Nobody writes that in a round, and a
    permanently-unmet vault is as useless as a permanently-finished one."""
    v = _vault(tmp_path, [("a", 200, 200)])
    _, _, new = grow_targets_if_met(v, growth=1.4, cap=10)
    assert new == 210


def test_a_small_category_still_grows_by_the_percentage(tmp_path):
    """Below the cap the multiplier is the sensible unit — the cap must not
    flatten a young category into the same +10 as a mature one."""
    v = _vault(tmp_path, [("a", 10, 10)])
    _, _, new = grow_targets_if_met(v, growth=1.4, cap=10)
    assert new == 14


def test_the_bar_cannot_outrun_what_gets_written(tmp_path):
    """Four rounds of an UNCAPPED 1.4 take 143 -> 549. Capped, the same four
    rounds stay in reach of a real run."""
    v = _vault(tmp_path, [("a", 143, 143)])
    target = 143
    for _ in range(4):
        cats = load_targets(v)
        cats.categories[0].met_count = target  # the round was actually completed
        (v / "_pipeline" / "coverage-targets.json").write_text(
            json.dumps(cats.to_dict()), encoding="utf-8"
        )
        _, _, target = grow_targets_if_met(v, growth=1.4, cap=10)
    assert target == 183  # not 549
