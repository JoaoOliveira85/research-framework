"""Tier-2 tests for the inbound-link-aware stub classifier (spec 051 FR3).

`classify_stub` is a *pure* additional lens over the existing `scan_stubs`
detector: a short note that has accumulated enough inbound wikilinks is a graph
anchor and must be flagged for research, never silently deleted. The state
machine (data-model.md FR3):

1. ``body_len > body_len_threshold``                  -> ``not-a-stub``
2. else ``inbound_links_count >= anchor_link_threshold`` -> ``anchor-stub``
3. else                                               -> ``deletable-stub``

The ``anchor_link_threshold`` default (5) and its ``settings.yaml::stubs``
override live in ``StubsSettings``.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.pipeline.settings import load_vault_settings
from research_framework.pipeline.stubs import (
    StubClassificationContext,
    classify_stub,
)


def _ctx(
    *, body_len: int, inbound: int, path: str = "data_vault/01 - Concepts/N.md"
) -> StubClassificationContext:
    return StubClassificationContext(
        path=Path(path),
        inbound_links_count=inbound,
        body_len=body_len,
    )


# ---------------------------------------------------------------------------
# Branch 1: a long-enough body is never a stub, regardless of inbound links
# ---------------------------------------------------------------------------


class TestNotAStub:
    def test_long_body_is_not_a_stub(self) -> None:
        verdict = classify_stub(
            _ctx(body_len=300, inbound=0),
            body_len_threshold=200,
            anchor_link_threshold=5,
        )
        assert verdict == "not-a-stub"

    def test_long_body_wins_even_with_many_inbound_links(self) -> None:
        """Body length is checked first — a substantial note is not a stub
        even if it is also a heavily-linked anchor."""
        verdict = classify_stub(
            _ctx(body_len=300, inbound=100),
            body_len_threshold=200,
            anchor_link_threshold=5,
        )
        assert verdict == "not-a-stub"

    def test_body_len_equal_to_threshold_is_still_a_stub(self) -> None:
        """Boundary: the predicate is ``>`` not ``>=`` — a body exactly at the
        threshold is short enough to be a stub, so it falls through to the
        link-count branch."""
        verdict = classify_stub(
            _ctx(body_len=200, inbound=5),
            body_len_threshold=200,
            anchor_link_threshold=5,
        )
        assert verdict == "anchor-stub"


# ---------------------------------------------------------------------------
# Branch 2: a short, heavily-linked note is an anchor (flag, never delete)
# ---------------------------------------------------------------------------


class TestAnchorStub:
    def test_short_body_many_inbound_is_anchor(self) -> None:
        verdict = classify_stub(
            _ctx(body_len=40, inbound=30),
            body_len_threshold=200,
            anchor_link_threshold=5,
        )
        assert verdict == "anchor-stub"

    def test_inbound_exactly_at_threshold_is_anchor(self) -> None:
        """Boundary: the predicate is ``>=`` — exactly N inbound links anchors."""
        verdict = classify_stub(
            _ctx(body_len=10, inbound=5),
            body_len_threshold=200,
            anchor_link_threshold=5,
        )
        assert verdict == "anchor-stub"


# ---------------------------------------------------------------------------
# Branch 3: a short, barely-linked note is a normal deletion candidate
# ---------------------------------------------------------------------------


class TestDeletableStub:
    def test_short_body_few_inbound_is_deletable(self) -> None:
        verdict = classify_stub(
            _ctx(body_len=40, inbound=2),
            body_len_threshold=200,
            anchor_link_threshold=5,
        )
        assert verdict == "deletable-stub"

    def test_inbound_just_below_threshold_is_deletable(self) -> None:
        verdict = classify_stub(
            _ctx(body_len=10, inbound=4),
            body_len_threshold=200,
            anchor_link_threshold=5,
        )
        assert verdict == "deletable-stub"

    def test_zero_inbound_is_deletable(self) -> None:
        verdict = classify_stub(
            _ctx(body_len=0, inbound=0),
            body_len_threshold=200,
            anchor_link_threshold=5,
        )
        assert verdict == "deletable-stub"


# ---------------------------------------------------------------------------
# The headline scenario from the spec's Independent Test
# ---------------------------------------------------------------------------


def test_independent_scenario_same_note_flips_on_inbound_count() -> None:
    """A 40-word note with 30 inbound links -> anchor; the same note with 2
    inbound links -> deletable."""
    anchored = classify_stub(
        _ctx(body_len=40, inbound=30),
        body_len_threshold=200,
        anchor_link_threshold=5,
    )
    orphaned = classify_stub(
        _ctx(body_len=40, inbound=2),
        body_len_threshold=200,
        anchor_link_threshold=5,
    )
    assert (anchored, orphaned) == ("anchor-stub", "deletable-stub")


# ---------------------------------------------------------------------------
# StubsSettings: default + settings.yaml override
# ---------------------------------------------------------------------------


def _write_vault(tmp_path: Path, body: str) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(body, encoding="utf-8")
    return vault


def test_default_anchor_link_threshold_is_5(tmp_path: Path) -> None:
    """A settings.yaml with no ``stubs`` block yields the default threshold."""
    vault = _write_vault(
        tmp_path,
        """
pipeline:
  max_cycles: 3
  budget_usd: 5.0
""",
    )
    settings = load_vault_settings(vault)
    assert settings.stubs.anchor_link_threshold == 5


def test_settings_yaml_anchor_link_threshold_override(tmp_path: Path) -> None:
    """``settings.yaml::stubs.anchor_link_threshold`` overrides the default,
    and feeding it to classify_stub changes the verdict at the boundary."""
    vault = _write_vault(
        tmp_path,
        """
pipeline:
  max_cycles: 3
  budget_usd: 5.0
stubs:
  anchor_link_threshold: 3
""",
    )
    settings = load_vault_settings(vault)
    assert settings.stubs.anchor_link_threshold == 3

    # 3 inbound links now anchors (would be deletable under the default of 5).
    verdict = classify_stub(
        _ctx(body_len=40, inbound=3),
        body_len_threshold=200,
        anchor_link_threshold=settings.stubs.anchor_link_threshold,
    )
    assert verdict == "anchor-stub"
