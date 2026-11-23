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
    new_n, update_n, discovery_n = split_quota(
        quota, SHARES, mode="expand", new_available=LOTS, updates_available=LOTS
    )
    assert discovery_n == 0  # no discovery topic waiting: its share is new topics
    assert new_n + update_n == quota
    assert update_n == {1: 0, 3: 1, 10: 3, 17: 5}[quota]

    # no open update entries: everything goes to new topics
    assert split_quota(
        quota, SHARES, mode="expand", new_available=LOTS, updates_available=0
    ) == (quota, 0, 0)

    # no coverage gaps: everything goes to updates (what there is of it)
    assert split_quota(
        quota, SHARES, mode="expand", new_available=0, updates_available=LOTS
    ) == (0, quota, 0)
    assert split_quota(
        quota, SHARES, mode="expand", new_available=0, updates_available=2
    ) == (0, min(quota, 2), 0)

    # fewer updates than their share: the rest falls to new topics
    n, u, _ = split_quota(
        quota, SHARES, mode="expand", new_available=LOTS, updates_available=1
    )
    assert (n + u, u) == (quota, min(1, update_n))

    # discovery is always empty: a split of 0/0/100 is all new topics
    only_discovery = CycleSplit(new=0, updates=0, discovery=100)
    assert split_quota(
        quota, only_discovery, mode="expand", new_available=LOTS, updates_available=LOTS
    ) == (quota, 0, 0)

    # nothing anywhere: nothing is planned
    assert split_quota(
        quota, SHARES, mode="expand", new_available=0, updates_available=0
    ) == (0, 0, 0)


def test_mode_overrides_the_split() -> None:
    kwargs = {"new_available": LOTS, "updates_available": LOTS}
    assert split_quota(10, SHARES, mode="bootstrap", **kwargs) == (10, 0, 0)
    assert split_quota(10, SHARES, mode="refresh", **kwargs) == (0, 10, 0)
    assert split_quota(10, SHARES, mode="expand", **kwargs) == (7, 3, 0)
    # a mode's zero is never filled from the other kind
    assert split_quota(
        10, SHARES, mode="bootstrap", new_available=LOTS, updates_available=LOTS
    ) == (10, 0, 0)
    assert split_quota(
        10, SHARES, mode="refresh", new_available=LOTS, updates_available=0
    ) == (0, 0, 0)
    assert split_quota(
        10, SHARES, mode="bootstrap", new_available=0, updates_available=LOTS
    ) == (0, 0, 0)


def test_a_mapping_of_shares_is_accepted_and_zero_quota_plans_nothing() -> None:
    shares = {"new": 50, "updates": 50, "discovery": 0}
    assert split_quota(
        4, shares, mode="expand", new_available=LOTS, updates_available=LOTS
    ) == (2, 2, 0)
    assert split_quota(
        0, shares, mode="expand", new_available=LOTS, updates_available=LOTS
    ) == (0, 0, 0)


def test_a_ten_percent_share_yields_one_slot_every_ten_quota_units() -> None:
    """The carried credit (spec 088 Q1): a quota of 3 at 10% is 0.3 a cycle, so
    one discovery slot opens every fourth cycle (the first whole unit), and
    every ten quota units over any run."""
    credit = 0.0
    slots = []
    for _ in range(10):
        credit += 3 * 10 / 100
        _, _, discovery_n = split_quota(
            3,
            SHARES,
            mode="expand",
            new_available=LOTS,
            updates_available=LOTS,
            discovery_available=LOTS,
            discovery_credit=credit,
        )
        slots.append(discovery_n)
        credit -= discovery_n
    assert slots == [0, 0, 0, 1, 0, 0, 1, 0, 0, 1]
    assert sum(slots) == 3  # 30 quota units at 10%

    # without a carried credit the plain share of one cycle is used: 10% of 10
    n, u, d = split_quota(
        10,
        SHARES,
        mode="expand",
        new_available=LOTS,
        updates_available=LOTS,
        discovery_available=LOTS,
    )
    assert (d, n + u + d) == (1, 10)
    # the slot comes out of the cycle's quota: the rest is split 60:30
    assert (n, u) == (6, 3)


def test_unused_discovery_share_falls_to_new_topics_and_refresh_dispatches_none() -> (
    None
):
    kwargs = {"new_available": LOTS, "updates_available": LOTS}
    # nothing waiting: the share is new topics, as before spec 088
    assert split_quota(10, SHARES, mode="expand", **kwargs) == (7, 3, 0)
    # waiting, but the share (10% of 10 = 1) caps it
    assert (
        split_quota(10, SHARES, mode="expand", discovery_available=5, **kwargs)[2] == 1
    )
    # fewer waiting than the share allows: the rest falls to new topics
    only_one = split_quota(
        10, SHARES, mode="expand", discovery_available=1, discovery_credit=4.0, **kwargs
    )
    assert only_one[2] == 1 and sum(only_one) == 10
    # a credit under one whole unit dispatches none, and the share is new topics
    assert split_quota(
        10, SHARES, mode="expand", discovery_available=5, discovery_credit=0.9, **kwargs
    ) == (7, 3, 0)
    # a discovery share of 0 is off, whatever the credit
    off = CycleSplit(new=70, updates=30, discovery=0)
    assert split_quota(
        10, off, mode="expand", discovery_available=5, discovery_credit=9.0, **kwargs
    ) == (7, 3, 0)
    # refresh: no discovery topic is dispatched
    assert split_quota(10, SHARES, mode="refresh", discovery_available=5, **kwargs) == (
        0,
        10,
        0,
    )
    # a credit larger than the quota never dispatches more than the quota
    assert split_quota(
        2, SHARES, mode="expand", discovery_available=9, discovery_credit=9.0, **kwargs
    ) == (0, 0, 2)
