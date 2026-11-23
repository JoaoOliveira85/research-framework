"""Tier 1: sharing a cycle's topics between new topics and updates (spec 087
FR-015..FR-017)."""

from __future__ import annotations

import pytest

from research_framework.pipeline.currency import split_quota
from research_framework.pipeline.settings import CycleSplit

LOTS = 1000
SHARES = CycleSplit()  # 60 / 30 / 10


@pytest.mark.parametrize("quota", [1, 3, 10, 17])
def test_split_rounds_to_the_quota_and_empty_shares_fall_to_the_others(
    quota: int,
) -> None:
    # both kinds have work: the shares sum to the quota; discovery's 10 goes
    # to new topics, so the split is 70 / 30
    new_n, update_n = split_quota(
        quota, SHARES, mode="expand", new_available=LOTS, updates_available=LOTS
    )
    assert new_n + update_n == quota
    assert update_n == {1: 0, 3: 1, 10: 3, 17: 5}[quota]

    # no open update entries: everything goes to new topics
    assert split_quota(
        quota, SHARES, mode="expand", new_available=LOTS, updates_available=0
    ) == (quota, 0)

    # no coverage gaps: everything goes to updates (what there is of it)
    assert split_quota(
        quota, SHARES, mode="expand", new_available=0, updates_available=LOTS
    ) == (0, quota)
    assert split_quota(
        quota, SHARES, mode="expand", new_available=0, updates_available=2
    ) == (0, min(quota, 2))

    # fewer updates than their share: the rest falls to new topics
    n, u = split_quota(
        quota, SHARES, mode="expand", new_available=LOTS, updates_available=1
    )
    assert (n + u, u) == (quota, min(1, update_n))

    # discovery is always empty: a split of 0/0/100 is all new topics
    only_discovery = CycleSplit(new=0, updates=0, discovery=100)
    assert split_quota(
        quota, only_discovery, mode="expand", new_available=LOTS, updates_available=LOTS
    ) == (quota, 0)

    # nothing anywhere: nothing is planned
    assert split_quota(
        quota, SHARES, mode="expand", new_available=0, updates_available=0
    ) == (0, 0)


def test_mode_overrides_the_split() -> None:
    kwargs = {"new_available": LOTS, "updates_available": LOTS}
    assert split_quota(10, SHARES, mode="bootstrap", **kwargs) == (10, 0)
    assert split_quota(10, SHARES, mode="refresh", **kwargs) == (0, 10)
    assert split_quota(10, SHARES, mode="expand", **kwargs) == (7, 3)
    # a mode's zero is never filled from the other kind
    assert split_quota(
        10, SHARES, mode="bootstrap", new_available=LOTS, updates_available=LOTS
    ) == (10, 0)
    assert split_quota(
        10, SHARES, mode="refresh", new_available=LOTS, updates_available=0
    ) == (0, 0)
    assert split_quota(
        10, SHARES, mode="bootstrap", new_available=0, updates_available=LOTS
    ) == (0, 0)


def test_a_mapping_of_shares_is_accepted_and_zero_quota_plans_nothing() -> None:
    shares = {"new": 50, "updates": 50, "discovery": 0}
    assert split_quota(
        4, shares, mode="expand", new_available=LOTS, updates_available=LOTS
    ) == (2, 2)
    assert split_quota(
        0, shares, mode="expand", new_available=LOTS, updates_available=LOTS
    ) == (0, 0)
