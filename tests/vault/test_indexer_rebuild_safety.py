"""`rebuild_all` must not lose a legacy root index on a bad note.

It unlinked the vault-root `_index.md` / `_concepts.md` / `_graph.md` first
and only then scanned the corpus. One non-UTF-8 note raised
`UnicodeDecodeError` (the canonical parser only wraps `OSError`), the rebuild
aborted, and the hand-curated root index was already gone.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.vault.indexer import rebuild_all


def test_undecodable_note_is_skipped_and_legacy_index_is_migrated(
    tmp_path: Path,
) -> None:
    notes = tmp_path / "data_vault" / "c"
    notes.mkdir(parents=True)
    (tmp_path / "_index.md").write_text("# hand-curated legacy index\n", "utf-8")
    (notes / "ok.md").write_text("---\ntitle: OK\n---\n\nbody\n", "utf-8")
    (notes / "bad.md").write_bytes(b"---\ntitle: Bad\nsummary: caf\xe9\n---\n\nx\n")

    paths = rebuild_all(tmp_path)

    index = paths["index"].read_text(encoding="utf-8")
    assert "[[OK]]" in index
    assert "hand-curated legacy index" in index
    assert not (tmp_path / "_index.md").exists()


def test_root_index_survives_a_failed_rebuild(tmp_path: Path, monkeypatch) -> None:
    """The root copy may only go once its content is safely in the new file."""
    import research_framework.vault.indexer as indexer

    notes = tmp_path / "data_vault" / "c"
    notes.mkdir(parents=True)
    root = tmp_path / "_index.md"
    root.write_text("# hand-curated legacy index\n", "utf-8")
    (notes / "ok.md").write_text("---\ntitle: OK\n---\n\nbody\n", "utf-8")

    def boom(*_a, **_k):
        raise RuntimeError("scan failed")

    monkeypatch.setattr(indexer, "_outgoing_links", boom)
    try:
        rebuild_all(tmp_path)
    except RuntimeError:
        pass

    assert root.read_text(encoding="utf-8") == "# hand-curated legacy index\n"


def test_a_corpus_at_the_vault_root_does_not_append_its_own_indexes(
    tmp_path: Path,
) -> None:
    """With ``vault.corpus_dir: "."`` the index files at the vault root are the
    ones the rebuild writes, not legacy copies to migrate.

    They were read back as "root index stubs" and appended under ``## Migrated
    from vault root``, so every rebuild carried the previous index along and
    the three files grew without bound, one copy per cycle.
    """
    (tmp_path / "_pipeline").mkdir()
    (tmp_path / "_pipeline" / "spec-parse.json").write_text(
        '{"vault_corpus_dir": "."}', "utf-8"
    )
    notes = tmp_path / "c"
    notes.mkdir()
    (notes / "ok.md").write_text("---\ntitle: OK\n---\n\nbody\n", "utf-8")

    first = {k: p.read_text("utf-8") for k, p in rebuild_all(tmp_path).items()}
    for _ in range(3):
        again = {k: p.read_text("utf-8") for k, p in rebuild_all(tmp_path).items()}

    assert again == first
    assert "[[OK]]" in again["index"]
    assert "Migrated from vault root" not in "".join(again.values())
