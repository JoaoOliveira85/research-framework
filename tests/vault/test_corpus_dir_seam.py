"""`vault.corpus_dir` must reach every reader, not just the generator.

The simple-spec parser validates `vault.corpus_dir` and scaffold/templates
honour it, so a vault can legitimately call its corpus `cases/`. Every
downstream reader used to hardcode `data_vault/` instead, which meant such a
vault got a second, empty `data_vault/` created under it, its indexes written
there, and `met_count` stuck at 0 — a setting accepted and silently ignored
(#251).

Each test here builds a vault whose corpus is NOT `data_vault` and asserts the
reader sees the notes that are actually there.
"""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.pipeline import wikilinks
from research_framework.pipeline.coverage import (
    existing_vault_filenames,
    recompute_from_disk,
    save_targets,
    unmet_expected_filenames,
)
from research_framework.pipeline.orchestrator import _quarantine_rejected_notes
from research_framework.spec.schema import CoverageCategory, CoverageTargets
from research_framework.vault import indexer
from research_framework.vault.corpus import DEFAULT_CORPUS_DIR, corpus_dir

CORPUS = "cases"


def _write_note(dir_: Path, filename: str, body: str = "Body text.", **fm: object):
    dir_.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for key, value in fm.items():
        lines.append(f"{key}: {value}")
    lines += ["---", "", body, ""]
    (dir_ / filename).write_text("\n".join(lines), encoding="utf-8")


def _vault_with_custom_corpus(tmp_path: Path, corpus: str = CORPUS) -> Path:
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    (vault / "_pipeline" / "spec-parse.json").write_text(
        json.dumps({"name": "Casework", "vault_corpus_dir": corpus}),
        encoding="utf-8",
    )
    return vault


class TestCorpusDirResolution:
    def test_reads_the_declared_corpus_from_spec_parse(self, tmp_path: Path) -> None:
        vault = _vault_with_custom_corpus(tmp_path)
        assert corpus_dir(vault) == vault / CORPUS

    def test_defaults_when_the_vault_declares_nothing(self, tmp_path: Path) -> None:
        vault = tmp_path / "bare"
        vault.mkdir()
        assert corpus_dir(vault) == vault / DEFAULT_CORPUS_DIR

    def test_survives_an_unreadable_spec_parse(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        (vault / "_pipeline").mkdir(parents=True)
        (vault / "_pipeline" / "spec-parse.json").write_text("{not json", "utf-8")
        assert corpus_dir(vault) == vault / DEFAULT_CORPUS_DIR


class TestIndexer:
    def test_rebuild_writes_indexes_into_the_declared_corpus(
        self, tmp_path: Path
    ) -> None:
        vault = _vault_with_custom_corpus(tmp_path)
        _write_note(
            vault / CORPUS / "01 - Concepts",
            "Alpha.md",
            type="concept",
            title="Alpha",
        )

        paths = indexer.rebuild_all(vault)

        assert paths["index"] == vault / CORPUS / "_index.md"
        assert "Alpha" in paths["index"].read_text(encoding="utf-8")
        assert not (vault / DEFAULT_CORPUS_DIR).exists(), (
            "a second, empty data_vault/ was created beside the real corpus"
        )

    def test_inbound_links_are_counted_in_the_declared_corpus(
        self, tmp_path: Path
    ) -> None:
        vault = _vault_with_custom_corpus(tmp_path)
        notes = vault / CORPUS / "01 - Concepts"
        _write_note(notes, "Alpha.md", type="concept", title="Alpha")
        _write_note(notes, "Beta.md", body="See [[Alpha]].", type="concept")

        assert indexer.inbound_link_counts(vault).get("Alpha") == 1


class TestCoverage:
    def _seed(self, vault: Path) -> None:
        save_targets(
            vault,
            CoverageTargets(
                categories=[
                    CoverageCategory(
                        name="concepts",
                        note_type="concept",
                        target_count=5,
                        met_count=0,
                        expected_filenames=["Alpha.md", "Gamma.md"],
                    )
                ]
            ),
        )

    def test_recompute_counts_notes_in_the_declared_corpus(
        self, tmp_path: Path
    ) -> None:
        vault = _vault_with_custom_corpus(tmp_path)
        self._seed(vault)
        _write_note(
            vault / CORPUS / "01 - Concepts",
            "Alpha.md",
            type="concept",
            title="Alpha",
            coverage_category="concepts",
        )

        targets = recompute_from_disk(vault)

        by = {c.name: c.met_count for c in targets.categories}
        assert by["concepts"] == 1, "met_count stuck at 0 — the corpus was not read"

    def test_expected_filenames_resolve_against_the_declared_corpus(
        self, tmp_path: Path
    ) -> None:
        vault = _vault_with_custom_corpus(tmp_path)
        self._seed(vault)
        _write_note(
            vault / CORPUS / "01 - Concepts",
            "Alpha.md",
            type="concept",
            coverage_category="concepts",
        )

        assert existing_vault_filenames(vault) == ["Alpha.md"]
        assert unmet_expected_filenames(vault) == {"concepts": ["Gamma.md"]}


class TestQuarantine:
    def test_rejected_notes_are_found_in_the_declared_corpus(
        self, tmp_path: Path
    ) -> None:
        vault = _vault_with_custom_corpus(tmp_path)
        _write_note(
            vault / CORPUS / "01 - Concepts",
            "Rejected.md",
            type="concept",
            verifier_status="rejected",
        )

        moved = _quarantine_rejected_notes(vault)

        assert moved == 1
        assert not (vault / CORPUS / "01 - Concepts" / "Rejected.md").exists()
        assert (vault / "_pipeline" / "quarantine" / "Rejected.md").exists()


class TestWikilinks:
    def test_acronym_map_is_built_from_the_declared_corpus(
        self, tmp_path: Path
    ) -> None:
        vault = _vault_with_custom_corpus(tmp_path)
        _write_note(
            vault / CORPUS / "01 - Concepts",
            "Service Level Objective (SLO).md",
            type="concept",
            title="Service Level Objective (SLO)",
        )

        acronyms, _ambiguous = wikilinks.build_acronym_map(vault)

        assert "SLO" in acronyms
