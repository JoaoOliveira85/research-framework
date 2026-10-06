"""US7: indexer writes under data_vault/ and migrates root indexes (T079)."""

from __future__ import annotations

from pathlib import Path


def _rebuild_all():
    from research_framework.vault.indexer import rebuild_all

    return rebuild_all


def _minimal_note(data_vault: Path) -> None:
    p = data_vault / "solo" / "only.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "---\n"
        "title: Solo Note\n"
        "summary: Only note in vault\n"
        "coverage_category: x\n"
        "related: []\n"
        "---\n\n"
        "# Solo Note\n",
        encoding="utf-8",
    )


class TestIndexerPathsUs7:
    def test_rebuild_all_never_writes_vault_root_index(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        dv = vault / "data_vault"
        dv.mkdir(parents=True)
        _minimal_note(dv)

        rebuild_all = _rebuild_all()
        rebuild_all(vault)

        assert not (vault / "_index.md").exists(), (
            "_index.md must not exist at vault root after rebuild_all"
        )

    def test_migrates_root_index_into_data_vault_preserves_content(
        self, tmp_path: Path
    ) -> None:
        vault = tmp_path / "vault"
        dv = vault / "data_vault"
        dv.mkdir(parents=True)
        _minimal_note(dv)

        sentinel = "---\nmigrated: true\n---\n\n<!-- T079 sentinel -->\n"
        vault.mkdir(parents=True, exist_ok=True)
        (vault / "_index.md").write_text(sentinel, encoding="utf-8")

        rebuild_all = _rebuild_all()
        rebuild_all(vault)

        assert not (vault / "_index.md").exists()
        migrated = dv / "_index.md"
        assert migrated.is_file()
        text = migrated.read_text(encoding="utf-8")
        assert "<!-- T079 sentinel -->" in text
