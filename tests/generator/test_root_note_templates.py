"""Issue #20 — note templates are rendered once, at the vault root.

``<vault>/_templates/<type>.md`` is the only copy; the framework owns it, so
scaffold and ``./vault update`` always re-render it. Nothing lives under
``<corpus>/_templates/`` any more, and the files an older framework wrote there
are removed on update — but never an operator's own.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.generator.scaffold import scaffold
from research_framework.generator.templates import (
    PREVIOUS_DIR,
    TEMPLATE_REGISTRY,
    remove_legacy_corpus_templates,
    render_all,
    render_note_type_templates,
)
from research_framework.pipeline import vault_update
from research_framework.pipeline.vault_update import refresh_root_templates
from research_framework.spec.schema import NoteTypeConfig, SpecConfig
from research_framework.spec.simple import load as load_spec

TESTS = Path(__file__).resolve().parents[1]
SAMPLE_SPEC = TESTS / "fixtures" / "sample-spec.md"
# Output of the REAL pre-#20 corpus writer (``scaffold.py`` at bc39eae), run
# for the two note types built by ``_spec(two_types=True)``. Pinned as files so
# the expectation is not a re-implementation of the writer under test.
LEGACY_FIXTURES = TESTS / "fixtures" / "legacy_corpus_templates"


def _spec(corpus: str = "data_vault", *, two_types: bool = False) -> SpecConfig:
    spec = load_spec(SAMPLE_SPEC)
    spec.vault_corpus_dir = corpus
    if two_types:
        spec.note_types = [
            NoteTypeConfig(
                name="concept",
                description="d",
                folder="01 - Concepts",
                required_sections=["Overview", "Key Details"],
                contextual_questions=["What is this concept?", "How does it relate?"],
            ),
            NoteTypeConfig(
                name="Case Law",
                description="d",
                folder="02 - Case Law",
                required_sections=["Holding", "Reasoning"],
                contextual_questions=["Which court?"],
            ),
        ]
    return spec


def _seed_legacy(vault: Path, spec: SpecConfig) -> dict[str, Path]:
    """Lay the pinned old-writer output down as an older scaffold would have."""
    tmpl = vault / spec.vault_corpus_dir / "_templates"
    tmpl.mkdir(parents=True, exist_ok=True)
    seeded = {}
    for nt in spec.note_types:
        stem = nt.name.replace(" ", "_").lower()
        path = tmpl / f"{stem}.md"
        path.write_bytes((LEGACY_FIXTURES / f"{stem}.md").read_bytes())
        seeded[nt.name] = path
    return seeded


def _rel(vault: Path, paths: list[Path]) -> list[str]:
    return sorted(p.relative_to(vault).as_posix() for p in paths)


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


def test_scaffold_renders_every_note_type_including_spaced_and_cased_names(
    tmp_path: Path,
) -> None:
    spec = _spec(two_types=True)
    vault = tmp_path / "v"
    scaffold(spec, vault)

    tmpl = vault / "_templates"
    assert (tmpl / "concept.md").is_file()
    case_law = (tmpl / "Case Law.md").read_text(encoding="utf-8")
    assert "type: Case Law" in case_law
    assert "## Holding" in case_law and "## Reasoning" in case_law
    registry = (tmpl / TEMPLATE_REGISTRY).read_text(encoding="utf-8")
    assert "| concept.md | 1.0.0 |" in registry
    assert "| Case Law.md | 1.0.0 |" in registry
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
    spec = _spec(two_types=True)
    vault = tmp_path / "v"
    scaffold(spec, vault)
    files = sorted((vault / "_templates").glob("*.md"))
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files}

    result = render_note_type_templates(spec, vault)

    assert result.written == [] and result.overwritten == []
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files} == before
    assert not (vault / "_templates" / PREVIOUS_DIR).exists()


def test_render_all_still_writes_root_templates(tmp_path: Path) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    vault.mkdir()
    render_all(spec, vault)
    assert (vault / "_templates" / "concept.md").is_file()
    assert (vault / "_templates" / TEMPLATE_REGISTRY).is_file()


# --------------------------------------------------------------------------
# a copy of what an overwrite replaced (the root is git-ignored)
# --------------------------------------------------------------------------


def test_overwriting_an_edited_template_saves_the_previous_content(
    tmp_path: Path,
) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    path = vault / "_templates" / "concept.md"
    path.write_text("operator rewrote this\n", encoding="utf-8")

    result = render_note_type_templates(spec, vault)

    saved = vault / "_templates" / PREVIOUS_DIR / "concept.md"
    assert saved.read_text(encoding="utf-8") == "operator rewrote this\n"
    assert result.overwritten == [(path, saved)]
    assert "## Overview" in path.read_text()


def test_only_one_previous_copy_is_kept_and_it_is_replaced_each_time(
    tmp_path: Path,
) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    path = vault / "_templates" / "concept.md"
    saved = vault / "_templates" / PREVIOUS_DIR / "concept.md"

    path.write_text("first edit\n", encoding="utf-8")
    render_note_type_templates(spec, vault)
    path.write_text("second edit\n", encoding="utf-8")
    render_note_type_templates(spec, vault)

    assert saved.read_text(encoding="utf-8") == "second edit\n"
    assert sorted(p.name for p in saved.parent.iterdir()) == ["concept.md"]


def test_a_new_or_unchanged_template_saves_nothing(tmp_path: Path) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    result = render_note_type_templates(spec, vault)  # nothing there to overwrite
    assert result.overwritten == []
    assert not (vault / "_templates" / PREVIOUS_DIR).exists()


def test_the_previous_dir_does_not_leak_into_template_listings(
    tmp_path: Path,
) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    (vault / "_templates" / "concept.md").write_text("edited\n", encoding="utf-8")
    render_note_type_templates(spec, vault)

    assert PREVIOUS_DIR.startswith(".")
    assert sorted(p.name for p in (vault / "_templates").glob("*.md")) == [
        "CHANGELOG.md",
        "concept.md",
    ]


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


def test_a_registry_without_the_table_header_keeps_its_history(
    tmp_path: Path,
) -> None:
    """An operator-reshaped registry is never replaced wholesale."""
    spec = _spec()
    vault = tmp_path / "v"
    (vault / "_templates").mkdir(parents=True)
    registry = vault / "_templates" / TEMPLATE_REGISTRY
    original = "# My template log\n\n## 2025-01-01\n\nHand-written history.\n"
    registry.write_text(original, encoding="utf-8")

    render_note_type_templates(spec, vault)

    text = registry.read_text(encoding="utf-8")
    assert text.startswith(original)
    assert "Hand-written history." in text
    assert "| concept.md | 1.0.0 |" in text  # a fresh table was added


def test_a_hand_bumped_registry_version_is_left_alone(tmp_path: Path) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    registry = vault / "_templates" / TEMPLATE_REGISTRY
    bumped = registry.read_text(encoding="utf-8").replace(
        "| concept.md | 1.0.0 |", "| concept.md | 2.0.0 |"
    )
    registry.write_text(bumped, encoding="utf-8")

    render_note_type_templates(spec, vault)  # the spec still says 1.0.0

    assert registry.read_text(encoding="utf-8") == bumped


# --------------------------------------------------------------------------
# bytes that are not UTF-8 never abort a scaffold or an update
# --------------------------------------------------------------------------

LATIN1 = "café — notes\n".encode("latin-1", errors="replace") + b"\xe9\xff\n"


def test_a_non_utf8_corpus_template_is_kept_not_a_crash(tmp_path: Path) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    path = vault / "data_vault" / "_templates" / "concept.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(LATIN1)

    assert remove_legacy_corpus_templates(spec, vault) == []
    assert path.read_bytes() == LATIN1


def test_a_non_utf8_root_template_is_overwritten_and_its_bytes_saved(
    tmp_path: Path,
) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    path = vault / "_templates" / "concept.md"
    path.write_bytes(LATIN1)

    render_note_type_templates(spec, vault)

    assert "## Overview" in path.read_text(encoding="utf-8")
    assert (vault / "_templates" / PREVIOUS_DIR / "concept.md").read_bytes() == LATIN1


def test_a_non_utf8_registry_is_left_untouched(tmp_path: Path) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    registry = vault / "_templates" / TEMPLATE_REGISTRY
    registry.write_bytes(LATIN1)

    render_note_type_templates(spec, vault)

    assert registry.read_bytes() == LATIN1


def test_update_survives_non_utf8_files_everywhere(tmp_path: Path) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    (vault / "_templates" / "concept.md").write_bytes(LATIN1)
    (vault / "_templates" / TEMPLATE_REGISTRY).write_bytes(LATIN1)
    corpus = vault / "data_vault" / "_templates"
    corpus.mkdir(parents=True)
    (corpus / "concept.md").write_bytes(LATIN1)

    result = refresh_root_templates(vault)

    assert result is not None
    assert (corpus / "concept.md").read_bytes() == LATIN1


# --------------------------------------------------------------------------
# removing what the framework wrote under the corpus
# --------------------------------------------------------------------------


def test_remove_legacy_deletes_framework_written_and_keeps_operator_files(
    tmp_path: Path,
) -> None:
    spec = _spec(two_types=True)
    vault = tmp_path / "v"
    scaffold(spec, vault)
    framework = _seed_legacy(vault, spec)
    tmpl = vault / "data_vault" / "_templates"
    operator_added = tmpl / "my-own-note-type.md"
    operator_added.write_text("# mine\n", encoding="utf-8")

    removed = remove_legacy_corpus_templates(spec, vault)

    assert sorted(removed) == _rel(vault, list(framework.values()))
    assert sorted(removed) == [
        "data_vault/_templates/case_law.md",
        "data_vault/_templates/concept.md",
    ]
    assert all(not p.exists() for p in framework.values())
    assert operator_added.read_text(encoding="utf-8") == "# mine\n"
    assert tmpl.is_dir()  # non-empty, so the directory stays


def test_remove_legacy_keeps_a_file_the_operator_edited(tmp_path: Path) -> None:
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    (path,) = _seed_legacy(vault, spec).values()
    edited = path.read_text(encoding="utf-8") + "\nOperator addition.\n"
    path.write_text(edited, encoding="utf-8")

    assert remove_legacy_corpus_templates(spec, vault) == []
    assert path.read_text(encoding="utf-8") == edited


def test_remove_legacy_keeps_a_stale_skeleton_the_spec_no_longer_matches(
    tmp_path: Path,
) -> None:
    """The spec changed since first scaffold: the old text no longer matches."""
    spec = _spec()
    vault = tmp_path / "v"
    scaffold(spec, vault)
    (path,) = _seed_legacy(vault, spec).values()
    spec.note_types[0].required_sections.append("Added Later")

    assert remove_legacy_corpus_templates(spec, vault) == []
    assert path.is_file()


def test_remove_legacy_drops_the_directory_when_it_ends_up_empty(
    tmp_path: Path,
) -> None:
    spec = _spec(two_types=True)
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
    spec = _spec(two_types=True)
    vault = tmp_path / "v"
    scaffold(spec, vault)
    _seed_legacy(vault, spec)

    scaffold(spec, vault)

    assert not (vault / "data_vault" / "_templates").exists()


def test_corpus_dir_dot_leaves_the_root_templates_in_place(tmp_path: Path) -> None:
    """``vault_corpus_dir: "."`` makes the corpus ``_templates`` THE root one."""
    spec = _spec(corpus=".", two_types=True)
    vault = tmp_path / "v"
    scaffold(spec, vault)
    legacy = _seed_legacy(vault, spec)  # old skeletons at <vault>/_templates/<stem>.md

    scaffold(spec, vault)

    tmpl = vault / "_templates"
    assert not (tmpl / "case_law.md").exists()  # the stale skeleton is gone
    assert "type: concept" in (tmpl / "concept.md").read_text(encoding="utf-8")
    assert "type: Case Law" in (tmpl / "Case Law.md").read_text(encoding="utf-8")
    assert (tmpl / TEMPLATE_REGISTRY).is_file()
    assert legacy["Case Law"].parent == tmpl


def test_remove_legacy_with_corpus_dir_dot_never_removes_the_directory(
    tmp_path: Path,
) -> None:
    spec = _spec(corpus=".", two_types=True)
    vault = tmp_path / "v"
    scaffold(spec, vault)

    assert remove_legacy_corpus_templates(spec, vault) == []
    assert (vault / "_templates" / "concept.md").is_file()


# --------------------------------------------------------------------------
# ./vault update
# --------------------------------------------------------------------------


def _old_vault(tmp_path: Path) -> tuple[Path, SpecConfig]:
    """A scaffolded vault carrying a stale root template + legacy corpus copies."""
    spec = _spec(two_types=True)
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
    assert result.removed == (
        "data_vault/_templates/concept.md",
        "data_vault/_templates/case_law.md",
    )
    assert not (vault / "data_vault" / "_templates" / "concept.md").exists()
    assert operator_added.is_file()


def test_update_reports_each_overwrite_with_where_the_old_content_went(
    tmp_path: Path,
) -> None:
    vault, _spec_ = _old_vault(tmp_path)

    result = refresh_root_templates(vault)

    assert result is not None
    assert result.overwritten == (
        ("_templates/concept.md", "_templates/.previous/concept.md"),
    )
    previous = vault / "_templates" / PREVIOUS_DIR / "concept.md"
    assert previous.read_text(encoding="utf-8") == "stale\n"


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
    spec = _spec(corpus="corpus", two_types=True)
    vault = tmp_path / "v"
    scaffold(spec, vault)
    _seed_legacy(vault, spec)
    (vault / "_pipeline" / "spec-parse.json").write_text(
        json.dumps(spec.to_dict(), default=str), encoding="utf-8"
    )

    result = refresh_root_templates(vault)

    assert result is not None
    assert result.removed == (
        "corpus/_templates/concept.md",
        "corpus/_templates/case_law.md",
    )
    assert not (vault / "corpus" / "_templates").exists()


def test_update_without_a_loadable_spec_changes_nothing(tmp_path: Path) -> None:
    vault = tmp_path / "bare"
    (vault / "_templates").mkdir(parents=True)
    keep = vault / "_templates" / "concept.md"
    keep.write_text("keep\n", encoding="utf-8")

    assert refresh_root_templates(vault) is None
    assert keep.read_text() == "keep\n"


def test_update_reports_a_render_failure_instead_of_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, _spec_ = _old_vault(tmp_path)

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("jinja exploded")

    monkeypatch.setattr(
        "research_framework.generator.templates.render_note_type_templates", boom
    )

    assert refresh_root_templates(vault) is None


def test_the_shim_treats_the_template_refresh_as_non_fatal() -> None:
    from research_framework.generator.scaffold import render_vault_shim

    spec = _spec()
    shim = render_vault_shim(Path("/tmp/vault-under-test"), spec)
    start = shim.index("<<'RVTMPL'")
    first_line = shim[shim.rindex("\n", 0, start) + 1 : shim.index("\n", start)]
    assert "|| echo" in first_line and "WARNING" in first_line
    assert vault_update.refresh_root_templates.__name__ in shim
