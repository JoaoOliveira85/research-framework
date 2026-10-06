"""US7: scaffold places index placeholders under data_vault/ only (T080)."""

from __future__ import annotations

from pathlib import Path

from research_framework.generator.scaffold import scaffold
from research_framework.spec.parser import parse


class TestScaffoldIndexPathsUs7:
    def test_scaffold_creates_index_placeholders_under_data_vault_only(
        self, sample_spec_path: Path, tmp_path: Path
    ) -> None:
        spec = parse(sample_spec_path)
        vault = tmp_path / "vault"
        scaffold(spec, vault, spec_source=sample_spec_path)

        dv = vault / spec.vault_corpus_dir
        for name in ("_index.md", "_concepts.md", "_graph.md"):
            p = dv / name
            assert p.is_file(), (
                f"expected placeholder {name} under {spec.vault_corpus_dir}/"
            )
            assert p.read_text(encoding="utf-8").strip(), f"{name} must be non-empty"

        assert not (vault / "_index.md").exists()
        assert not (vault / "_concepts.md").exists()
        assert not (vault / "_graph.md").exists()

    def test_rescaffold_preserves_index_placeholders(
        self, sample_spec_path: Path, tmp_path: Path
    ) -> None:
        spec = parse(sample_spec_path)
        vault = tmp_path / "vault"
        scaffold(spec, vault, spec_source=sample_spec_path)

        dv = vault / spec.vault_corpus_dir
        before = {
            n: (dv / n).read_bytes() for n in ("_index.md", "_concepts.md", "_graph.md")
        }

        # User edits inside placeholders must survive idempotent scaffold
        for name in before:
            p = dv / name
            p.write_bytes(p.read_bytes() + b"\n<!-- user-marker -->\n")

        scaffold(spec, vault, spec_source=sample_spec_path)

        for name in before:
            text = (dv / name).read_text(encoding="utf-8")
            assert "<!-- user-marker -->" in text, (
                f"{name} placeholder should be preserved"
            )
