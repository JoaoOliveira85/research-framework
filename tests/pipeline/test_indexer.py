"""Tests for research_framework.vault.indexer.rebuild_all — feature 017 US6 (T075)."""

from __future__ import annotations

import re
from pathlib import Path


def _rebuild_all():
    """RED until T077 exports ``rebuild_all`` on ``research_framework.vault.indexer``."""
    from research_framework.vault.indexer import rebuild_all

    return rebuild_all


def _write_note(
    data_vault: Path,
    *,
    folder: str,
    stem: str,
    title: str,
    summary: str,
    coverage_category: str,
    related: list[str] | None = None,
) -> Path:
    path = data_vault / folder / f"{stem}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    rel_fm = ""
    if related:
        rel_fm = "related:\n" + "".join(f"  - [[{t}]]\n" for t in related)
    else:
        rel_fm = "related: []\n"
    path.write_text(
        "---\n"
        f"title: {title}\n"
        f"summary: {summary}\n"
        f"coverage_category: {coverage_category}\n" + rel_fm + "---\n\n"
        f"# {title}\n",
        encoding="utf-8",
    )
    return path


def _build_multifolder_fixture(data_vault: Path) -> list[Path]:
    """Three folders, 2–3 notes each; titles/summaries unique for assertions."""
    notes = [
        ("apple", "a1", "Alpha One", "Summary A1", "cat-a", ["Beta One"]),
        ("apple", "a2", "Alpha Two", "Summary A2", "cat-a", ["Gamma One"]),
        ("banana", "b1", "Beta One", "Summary B1", "cat-b", ["Alpha One"]),
        ("banana", "b2", "Beta Two", "Summary B2", "cat-b", []),
        ("citrus", "c1", "Gamma One", "Summary G1", "cat-c", ["Alpha Two"]),
        ("citrus", "c2", "Gamma Two", "Summary G2", "cat-c", []),
        ("citrus", "c3", "Gamma Three", "Summary G3", "cat-c", ["Beta Two"]),
    ]
    return [
        _write_note(
            data_vault,
            folder=f,
            stem=s,
            title=t,
            summary=m,
            coverage_category=c,
            related=r,
        )
        for f, s, t, m, c, r in notes
    ]


class TestRebuildAllUs6:
    """US6: populated indexes + deterministic idempotency + return map."""

    def test_rebuild_all_produces_index_concepts_graph_and_return_map(
        self, tmp_path: Path
    ) -> None:
        vault_dir = tmp_path / "vault"
        data_vault = vault_dir / "data_vault"
        _build_multifolder_fixture(data_vault)

        rebuild_all = _rebuild_all()
        out = rebuild_all(vault_dir)

        assert set(out.keys()) == {"index", "concepts", "graph"}
        index_p = out["index"]
        concepts_p = out["concepts"]
        graph_p = out["graph"]
        assert index_p.is_file()
        assert concepts_p.is_file()
        assert graph_p.is_file()

        idx_text = index_p.read_text(encoding="utf-8")
        assert idx_text.strip(), "_index.md must be non-empty when notes exist"
        # Grouped by folder (implementation emits folder sections)
        assert "## apple" in idx_text
        assert "## banana" in idx_text
        assert "## citrus" in idx_text
        for title, summary in [
            ("Alpha One", "Summary A1"),
            ("Beta Two", "Summary B2"),
            ("Gamma Three", "Summary G3"),
        ]:
            assert title in idx_text
            assert summary in idx_text

        con_text = concepts_p.read_text(encoding="utf-8")
        for title in [
            "Alpha One",
            "Alpha Two",
            "Beta One",
            "Beta Two",
            "Gamma One",
            "Gamma Two",
            "Gamma Three",
        ]:
            assert title in con_text, f"_concepts.md must mention {title!r}"

        g_text = graph_p.read_text(encoding="utf-8")
        assert re.search(r"\[\[[^\]]+\]\]", g_text), (
            "_graph.md must contain [[wikilink]] patterns"
        )

    def test_graph_gives_a_zero_outdegree_note_no_edges(self, tmp_path: Path) -> None:
        """Issue #287: a note with no outgoing links used to render an edge
        to EVERY other note in the vault ("fallback: all notes"), which
        disagreed with :func:`inbound_link_counts` (documented to read the
        same edge set) and was O(n^2) noise in a large vault. Its `_graph.md`
        section must now list no targets at all."""
        from research_framework.vault.indexer import inbound_link_counts

        vault_dir = tmp_path / "vault"
        data_vault = vault_dir / "data_vault"
        _build_multifolder_fixture(data_vault)  # "Beta Two" has related: []

        rebuild_all = _rebuild_all()
        out = rebuild_all(vault_dir)
        g_text = out["graph"].read_text(encoding="utf-8")

        section = g_text.split("## Beta Two")[1].split("\n## ")[0]
        assert "[[" not in section, (
            f"zero-outdegree note must have no graph edges, got: {section!r}"
        )

        # Confirms the edge set this test pins matches the shared-edges
        # invariant the two functions' own docstrings claim.
        assert inbound_link_counts(vault_dir).get("Beta Two", 0) == 0

    def test_rebuild_all_is_idempotent_byte_identical(self, tmp_path: Path) -> None:
        vault_dir = tmp_path / "vault"
        data_vault = vault_dir / "data_vault"
        _build_multifolder_fixture(data_vault)

        rebuild_all = _rebuild_all()
        out1 = rebuild_all(vault_dir)
        out2 = rebuild_all(vault_dir)

        for key in ("index", "concepts", "graph"):
            p1 = out1[key]
            p2 = out2[key]
            assert p1 == p2
            assert p1.read_bytes() == p2.read_bytes()
