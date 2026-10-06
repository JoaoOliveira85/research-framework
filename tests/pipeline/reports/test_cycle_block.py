"""Per-cycle deterministic block tests (spec 040 T009)."""

from __future__ import annotations

from research_framework.pipeline.reports.layer1 import compose_cycle_block

pytest_plugins = ["tests.pipeline.reports.helpers"]


def test_cycle_block_self_contained(reports_vault) -> None:
    block = compose_cycle_block(reports_vault, 2)
    assert block.startswith("## Layer 1 metrics — cycle 002")
    assert "## Coverage Delta" in block
    assert "## Flagged Issues" in block


def test_cycle_block_scoped_to_single_cycle(reports_vault) -> None:
    block = compose_cycle_block(reports_vault, 3)
    assert "cycle 003" in block.lower() or "cycle-003" in block
    assert "reddit" in block
