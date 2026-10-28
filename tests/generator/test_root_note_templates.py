"""Issue #20 — note templates are rendered once, at the vault root.

``<vault>/_templates/<type>.md`` is the only copy; the framework owns it, so
scaffold and ``./vault update`` always re-render it. Nothing lives under
``<corpus>/_templates/`` any more, and the files an older framework wrote there
are removed on update — but never an operator's own.
"""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.generator.scaffold import scaffold
from research_framework.generator.templates import (
    TEMPLATE_REGISTRY,
    remove_legacy_corpus_templates,
    render_all,
    render_note_type_templates,
)
from research_framework.pipeline.vault_update import refresh_root_templates
from research_framework.spec.schema import SpecConfig
from research_framework.spec.simple import load as load_spec

SAMPLE_SPEC = Path(__file__).resolve().parents[1] / "fixtures" / "sample-spec.md"


def _spec(corpus: str = "data_vault") -> SpecConfig:
    spec = load_spec(SAMPLE_SPEC)
    spec.vault_corpus_dir = corpus
    return spec


def _legacy_corpus_text(name: str, sections: list[str], questions: list[str]) -> str:
    """Byte-for-byte what the removed ``data_vault/_templates/`` writer emitted."""
    lines = [
        f"# {name}",
        "",
        f"> Template for {name} notes. Required sections below.",
        "",
    ]
    for section in sections:
        lines += [f"## {section}", ""]
    lines += ["### Contextual questions", ""]
    lines += [f"- {q}" for q in questions]
    lines.append("")
    return "\n".join(lines)


def _seed_legacy(vault: Path, spec: SpecConfig) -> list[Path]:
    """Write the old corpus-level templates the way an older scaffold did."""
    tmpl = vault / spec.vault_corpus_dir / "_templates"
    tmpl.mkdir(parents=True, exist_ok=True)
    written = []
    for nt in spec.note_types:
        path = tmpl / f"{nt.name.replace(' ', '_').lower()}.md"
        path.write_text(
            _legacy_corpus_text(nt.name, nt.required_sections, nt.contextual_questions),
            encoding="utf-8",
        )
        written.append(path)
    return written


# --------------------------------------------------------------------------
# scaffold
# --------------------------------------------------------------------------


def test_scaffold_alone_writes_root_templates_and_none_under_corpus(
    tmp_path: Path,
) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)

    for nt in spec.note_types:
        text = (vault / "_templates" / f"{nt.name}.md").read_text(encoding="utf-8")
        assert f"type: {nt.name}" in text
        assert f'template_version: "{nt.template_version}"' in text
        for section in nt.required_sections:
            assert f"## {section}" in text
    assert (vault / "_templates" / TEMPLATE_REGISTRY).is_file()
    assert not (vault / "data_vault" / "_templates").exists()


def test_scaffold_honours_a_custom_corpus_dir(tmp_path: Path) -> None:
    spec = _spec(corpus="corpus")
    vault = tmp_path / "v"
    scaffold(spec, vault)

    assert (vault / "_templates" / "concept.md").is_file()
    assert not (vault / "corpus" / "_templates").exists()
    assert not (vault / "data_vault").exists()


def test_rescaffold_rerenders_an_existing_template(tmp_path: Path) -> None:
    """A section added to the spec reaches a vault scaffolded earlier."""
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    assert "## Brand New" not in (vault / "_templates" / "concept.md").read_text()

    spec.note_types[0].required_sections.append("Brand New")
    scaffold(spec, vault)

    assert "## Brand New" in (vault / "_templates" / "concept.md").read_text()


def test_rescaffold_overwrites_operator_edits_to_a_root_template(
    tmp_path: Path,
) -> None:
    """Root templates are framework-owned; this is the documented trade."""
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    path = vault / "_templates" / "concept.md"
    path.write_text("operator rewrote this\n", encoding="utf-8")

    scaffold(spec, vault)

    assert "operator rewrote this" not in path.read_text()
    assert "## Overview" in path.read_text()


def test_rerender_is_idempotent_and_does_not_touch_unchanged_files(
    tmp_path: Path,
) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    files = sorted((vault / "_templates").glob("*.md"))
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files}

    assert render_note_type_templates(spec, vault) == []

    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files} == before


def test_render_all_still_writes_root_templates(tmp_path: Path) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    vault.mkdir()
    render_all(spec, vault)
    assert (vault / "_templates" / "concept.md").is_file()
    assert (vault / "_templates" / TEMPLATE_REGISTRY).is_file()


# --------------------------------------------------------------------------
# the version registry (_templates/CHANGELOG.md)
# --------------------------------------------------------------------------


def test_registry_lists_every_note_type_version(tmp_path: Path) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    text = (vault / "_templates" / TEMPLATE_REGISTRY).read_text(encoding="utf-8")
    for nt in spec.note_types:
        assert f"| {nt.name}.md | {nt.template_version} |" in text


def test_rerender_records_a_version_bump_and_keeps_hand_written_history(
    tmp_path: Path,
) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    registry = vault / "_templates" / TEMPLATE_REGISTRY
    registry.write_text(
        registry.read_text(encoding="utf-8")
        + "\n## Operator log\n\nHand-written note that must survive.\n",
        encoding="utf-8",
    )

    spec.note_types[0].template_version = "1.1.0"
    render_note_type_templates(spec, vault)

    text = registry.read_text(encoding="utf-8")
    assert f"| {spec.note_types[0].name}.md | 1.1.0 |" in text
    assert "| concept.md | 1.0.0 |" not in text
    assert "#### 1.1.0" in text
    assert "#### 1.0.0" in text  # the original entry is kept
    assert "Hand-written note that must survive." in text
    assert (
        'template_version: "1.1.0"' in (vault / "_templates" / "concept.md").read_text()
    )


# --------------------------------------------------------------------------
# removing what the framework wrote under the corpus
# --------------------------------------------------------------------------


def test_remove_legacy_deletes_framework_written_and_keeps_operator_files(
    tmp_path: Path,
) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    framework = _seed_legacy(vault, spec)
    tmpl = vault / "data_vault" / "_templates"
    operator_added = tmpl / "my-own-note-type.md"
    operator_added.write_text("# mine\n", encoding="utf-8")

    removed = remove_legacy_corpus_templates(spec, vault)

    assert sorted(removed) == sorted(p.relative_to(vault).as_posix() for p in framework)
    assert all(not p.exists() for p in framework)
    assert operator_added.read_text(encoding="utf-8") == "# mine\n"
    assert tmpl.is_dir()  # non-empty, so the directory stays


def test_remove_legacy_keeps_a_file_the_operator_edited(tmp_path: Path) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    (path,) = _seed_legacy(vault, spec)
    edited = path.read_text(encoding="utf-8") + "\nOperator addition.\n"
    path.write_text(edited, encoding="utf-8")

    assert remove_legacy_corpus_templates(spec, vault) == []
    assert path.read_text(encoding="utf-8") == edited


def test_remove_legacy_drops_the_directory_when_it_ends_up_empty(
    tmp_path: Path,
) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    _seed_legacy(vault, spec)

    remove_legacy_corpus_templates(spec, vault)

    assert not (vault / "data_vault" / "_templates").exists()


def test_remove_legacy_is_a_noop_without_a_corpus_templates_dir(
    tmp_path: Path,
) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    assert remove_legacy_corpus_templates(spec, vault) == []


def test_scaffold_over_an_old_vault_removes_the_framework_written_copies(
    tmp_path: Path,
) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    _seed_legacy(vault, spec)

    scaffold(spec, vault)

    assert not (vault / "data_vault" / "_templates").exists()


# --------------------------------------------------------------------------
# ./vault update
# --------------------------------------------------------------------------


def _old_vault(tmp_path: Path) -> tuple[Path, SpecConfig]:
    """A scaffolded vault carrying a stale root template + legacy corpus copies."""
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    (vault / "_templates" / "concept.md").write_text("stale\n", encoding="utf-8")
    _seed_legacy(vault, spec)
    return vault, spec


def test_update_rerenders_root_templates_and_removes_legacy_copies(
    tmp_path: Path,
) -> None:
    vault, spec = _old_vault(tmp_path)
    operator_added = vault / "data_vault" / "_templates" / "mine.md"
    operator_added.write_text("# mine\n", encoding="utf-8")

    result = refresh_root_templates(vault)

    assert result is not None
    assert "_templates/concept.md" in result.rendered
    assert "## Overview" in (vault / "_templates" / "concept.md").read_text()
    assert result.removed == ("data_vault/_templates/concept.md",)
    assert not (vault / "data_vault" / "_templates" / "concept.md").exists()
    assert operator_added.is_file()


def test_update_reads_the_spec_from_spec_parse_json(tmp_path: Path) -> None:
    """The vault's parsed spec wins: a section added there reaches the template."""
    vault, spec = _old_vault(tmp_path)
    spec.note_types[0].required_sections.append("From Parse")
    (vault / "_pipeline" / "spec-parse.json").write_text(
        json.dumps(spec.to_dict(), default=str), encoding="utf-8"
    )

    refresh_root_templates(vault)

    assert "## From Parse" in (vault / "_templates" / "concept.md").read_text()


def test_update_honours_a_custom_corpus_dir(tmp_path: Path) -> None:
    spec = _spec(corpus="corpus")
    vault = tmp_path / "v"
    scaffold(spec, vault)
    _seed_legacy(vault, spec)
    (vault / "_pipeline" / "spec-parse.json").write_text(
        json.dumps(spec.to_dict(), default=str), encoding="utf-8"
    )

    result = refresh_root_templates(vault)

    assert result is not None
    assert result.removed == ("corpus/_templates/concept.md",)
    assert not (vault / "corpus" / "_templates").exists()


def test_update_without_a_loadable_spec_changes_nothing(tmp_path: Path) -> None:
    vault = tmp_path / "bare"
    (vault / "_templates").mkdir(parents=True)
    keep = vault / "_templates" / "concept.md"
    keep.write_text("keep\n", encoding="utf-8")

    assert refresh_root_templates(vault) is None
    assert keep.read_text() == "keep\n"
