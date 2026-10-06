"""Tier-2 test for ``vault.indexer.inbound_link_counts`` (spec 051 FR3, T018).

The stub classifier needs each note's inbound-link tally to protect graph
anchors from deletion. ``inbound_link_counts`` exposes the inbound counts from
the same wikilink graph ``rebuild_all`` already walks, as a read-only helper
with no behaviour change to ``rebuild_all``.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.vault.indexer import inbound_link_counts


def _note(vault: Path, title: str, links: list[str]) -> None:
    body_links = " ".join(f"[[{t}]]" for t in links)
    content = f"---\ntitle: {title}\n---\n\n{title} body text. {body_links}\n"
    path = vault / "data_vault" / "01 - Concepts" / f"{title}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_inbound_counts_from_link_graph(tmp_path: Path) -> None:
    """A links B and C; B links C; C links nothing → {A:0, B:1, C:2}."""
    _note(tmp_path, "A", ["B", "C"])
    _note(tmp_path, "B", ["C"])
    _note(tmp_path, "C", [])
    assert inbound_link_counts(tmp_path) == {"A": 0, "B": 1, "C": 2}


def test_empty_vault_returns_empty_map(tmp_path: Path) -> None:
    (tmp_path / "data_vault").mkdir()
    assert inbound_link_counts(tmp_path) == {}


def test_helper_is_read_only_does_not_write_indexes(tmp_path: Path) -> None:
    """Unlike ``rebuild_all``, the helper must not emit the Layer-1 indexes."""
    _note(tmp_path, "A", ["B"])
    _note(tmp_path, "B", [])
    inbound_link_counts(tmp_path)
    data_vault = tmp_path / "data_vault"
    assert not (data_vault / "_index.md").exists()
    assert not (data_vault / "_concepts.md").exists()
    assert not (data_vault / "_graph.md").exists()
