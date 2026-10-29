"""Layer-1 index files are pinned to hand-written golden files (issue #16).

``tests/fixtures/index_golden/vault`` is a small vault built to hit the cases a
self-comparing test cannot see: a note whose title differs from its file name,
a note with no front matter, and a note with no links. The files under
``tests/fixtures/index_golden/expected`` were written by hand from the rules
below, NOT captured from the indexer. If the indexer changes on purpose, edit
them by hand and read the diff.

Rules the goldens encode:

- A link uses the file stem and shows the title: ``[[stem|Title]]``
  (``[[stem]]`` when the two are equal).
- A note with no front matter is listed under its file stem.
- A note with no outgoing links has no edges in ``_graph.md``; a link to a note
  that does not exist is not an edge.
- File names and ``##`` headings are unchanged.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import sys
from pathlib import Path

import pytest

from research_framework.vault.indexer import inbound_link_counts, rebuild_all

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "index_golden"
_VALIDATOR = Path(__file__).parent.parent.parent / "scripts" / "validate_vault.py"
_LAYER1 = ("_index.md", "_concepts.md", "_graph.md")


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    # The vault directory name is part of every Layer-1 heading.
    dest = tmp_path / "golden-vault"
    shutil.copytree(_FIXTURES / "vault", dest)
    rebuild_all(dest)
    return dest


@pytest.mark.parametrize("name", _LAYER1)
def test_layer1_file_matches_golden(vault: Path, name: str) -> None:
    actual = (vault / "data_vault" / name).read_text(encoding="utf-8")
    expected = (_FIXTURES / "expected" / name).read_text(encoding="utf-8")
    assert actual == expected


def test_agents_md_topic_index_matches_golden(vault: Path) -> None:
    actual = (vault / "AGENTS.md").read_text(encoding="utf-8")
    expected = (_FIXTURES / "expected" / "AGENTS.md").read_text(encoding="utf-8")
    assert actual == expected


def test_rebuild_is_byte_stable(vault: Path) -> None:
    before = {n: (vault / "data_vault" / n).read_bytes() for n in _LAYER1}
    rebuild_all(vault)
    assert {n: (vault / "data_vault" / n).read_bytes() for n in _LAYER1} == before


def test_every_layer1_link_resolves_with_the_validators_resolver(vault: Path) -> None:
    """No dead link: each target passes the check ``validate_vault.py`` applies."""
    spec = importlib.util.spec_from_file_location("_validate_vault", _VALIDATOR)
    assert spec is not None and spec.loader is not None
    validator = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = validator  # @dataclass looks the module up here
    try:
        spec.loader.exec_module(validator)
    finally:
        sys.modules.pop(spec.name, None)
    stems = validator._vault_note_stems(vault)

    targets: list[str] = []
    for name in _LAYER1:
        text = (vault / "data_vault" / name).read_text(encoding="utf-8")
        targets += [m.split("|")[0] for m in re.findall(r"\[\[([^\]]+)\]\]", text)]
    assert targets, "the fixture must produce links to check"
    dead = [t for t in targets if not validator._related_target_resolves(t, stems)]
    assert dead == []


def test_inbound_counts_agree_with_the_graph(vault: Path) -> None:
    """Links written by stem, title, alias or path all count toward the title."""
    assert inbound_link_counts(vault) == {
        "Duplicate Concept": 0,
        "Duplicate Tool": 1,  # glossary, by a path link in another case
        "Event Sourcing": 2,  # idempotent_consumer + the note without front matter
        "Glossary": 1,  # kafka_basics
        "Idempotent Consumer": 1,  # event_sourcing, by title
        "Kafka Basics": 2,  # event_sourcing (related) + outbox_pattern
        "Lonely Note": 0,
        # event_sourcing as [[outbox_pattern|outbox]], idempotent_consumer by title
        "Transactional Outbox Pattern": 2,
        "scratch_no_frontmatter": 0,
    }


def test_notes_sharing_a_stem_link_by_path(tmp_path: Path) -> None:
    """``[[Folder/stem|Title]]`` keeps both links unambiguous."""
    for folder, title in (("a", "First"), ("b", "Second")):
        note = tmp_path / "data_vault" / folder / "same.md"
        note.parent.mkdir(parents=True)
        note.write_text(f"---\ntitle: {title}\n---\n\nbody\n", encoding="utf-8")

    rebuild_all(tmp_path)

    index = (tmp_path / "data_vault" / "_index.md").read_text(encoding="utf-8")
    assert "- [[a/same|First]]" in index
    assert "- [[b/same|Second]]" in index


def test_tooling_markdown_without_front_matter_is_not_indexed(tmp_path: Path) -> None:
    """Markdown with no front matter is a note unless it is tooling.

    The ``_`` / ``.`` / ``raw_data`` / ``*.spec.md`` exclusions hold in every
    corpus; the root documents only matter with the corpus at the vault root.
    """
    (tmp_path / "_pipeline").mkdir()
    (tmp_path / "_pipeline" / "spec-parse.json").write_text(
        '{"vault_corpus_dir": "."}', encoding="utf-8"
    )
    for tooling in (
        "_pipeline/research-plan.md",
        "AGENTS.md",
        "raw_data/scraped-page.md",
        "my-vault.spec.md",
        ".obsidian/workspace.md",
    ):
        path = tmp_path / tooling
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Tooling\n", "utf-8")
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "bare.md").write_text("# Bare\n", "utf-8")

    rebuild_all(tmp_path)

    index = (tmp_path / "_index.md").read_text(encoding="utf-8")
    assert "[[bare]]" in index
    for name in ("research-plan", "AGENTS", "scraped-page", "my-vault", "workspace"):
        assert name not in index


def test_underscore_folders_without_front_matter_are_skipped_in_any_corpus(
    tmp_path: Path,
) -> None:
    """Not only a root corpus: ``data_vault/_drafts/x.md`` is not a note."""
    corpus = tmp_path / "data_vault"
    (corpus / "_drafts").mkdir(parents=True)
    (corpus / "_drafts" / "scratch.md").write_text("# Scratch\n", "utf-8")
    (corpus / "c").mkdir()
    (corpus / "c" / "bare.md").write_text("# Bare\n", "utf-8")

    rebuild_all(tmp_path)

    index = (corpus / "_index.md").read_text(encoding="utf-8")
    assert "[[bare]]" in index
    assert "scratch" not in index


def test_empty_title_falls_back_to_the_stem(tmp_path: Path) -> None:
    """``title: ""`` (or a bare ``title:``) must not render ``[[stem|]]``."""
    notes = tmp_path / "data_vault" / "c"
    notes.mkdir(parents=True)
    (notes / "blank_title.md").write_text('---\ntitle: ""\n---\n\nx\n', "utf-8")
    (notes / "null_title.md").write_text("---\ntitle:\n---\n\nx\n", "utf-8")

    rebuild_all(tmp_path)

    for name in ("_index.md", "_concepts.md", "_graph.md"):
        text = (tmp_path / "data_vault" / name).read_text(encoding="utf-8")
        assert "|]]" not in text and "None" not in text
    index = (tmp_path / "data_vault" / "_index.md").read_text(encoding="utf-8")
    assert "- [[blank_title]]" in index
    assert "- [[null_title]]" in index
