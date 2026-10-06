"""Spec 063 US4 (T018) — in-vault domain probe-pack discovery.

The probe pack is in-vault DATA (D5: the framework discovers + summarises it, never
imports it). This pins the framework side: GOLD anchors (P1 fingerprint trap, P12
convergence confidence) are surfaced verbatim and a vault covering a *different*
valid slice (products B/C) earns partial-breadth credit, not a zero.
"""

from __future__ import annotations

from research_framework.cli import acceptance

# A B/C-covering pack: GOLD anchors retained verbatim + breadth probes that miss
# the GOLD-anchored product A but cover B and C → partial (not zero) credit.
_BC_PACK = """# Domain probes (in-vault)

## GOLD anchors

- P1: fingerprint `variantId` selection trap (must resolve variantId before cohort).
- P12: convergence confidence reported on the matching decision.

## Breadth probes

- B-product-B: settlement reconciliation flow.
- B-product-C: dispute-resolution flow.

breadth_score: 0.66
"""


def test_discovery_summarises_pack(snapshot_vault):
    probes = acceptance.discover_domain_probes(snapshot_vault)
    assert probes is not None
    assert probes["pack"].endswith("domain-probes.md")
    assert probes["gold_anchors"] == ["P1", "P12"]
    assert probes["breadth_score"] == 0.66


def test_discovery_absent_when_no_pack(tmp_path):
    (tmp_path / "_pipeline" / "acceptance").mkdir(parents=True)
    assert acceptance.discover_domain_probes(tmp_path) is None


def test_bc_covering_pack_scores_partial_breadth(tmp_path):
    acc = tmp_path / "_pipeline" / "acceptance"
    acc.mkdir(parents=True)
    pack = acc / "domain-probes.md"
    pack.write_text(_BC_PACK, encoding="utf-8")

    probes = acceptance.discover_domain_probes(tmp_path)
    # GOLD anchors retained byte-identically (no regression of high-signal probes).
    assert probes["gold_anchors"] == ["P1", "P12"]
    assert "P1: fingerprint `variantId`" in pack.read_text(encoding="utf-8")
    assert "P12: convergence confidence" in pack.read_text(encoding="utf-8")
    # A different-but-valid slice earns partial credit, not zero.
    assert 0.0 < probes["breadth_score"] < 1.0


def test_pack_surfaced_in_scorecard(snapshot_vault):
    card = acceptance.build_scorecard(snapshot_vault)
    assert card["domain_probes"]["gold_anchors"] == ["P1", "P12"]
