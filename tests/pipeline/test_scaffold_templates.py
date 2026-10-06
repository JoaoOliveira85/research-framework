"""RED tests (T083): `data_vault/_templates/` per note type from scaffold.

Turns green when T085 emits one `{note_type}.md` per `NoteTypeConfig` with
`required_sections` as `##` headings and idempotent re-scaffold.
"""

from __future__ import annotations

import re
from pathlib import Path

from research_framework.generator.scaffold import scaffold
from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)

HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _spec_three_note_types() -> SpecConfig:
    scope = ScopeConfig(domain="d", organization="o")
    return SpecConfig(
        name="tpl-vault",
        location=Path("."),
        owner="tester",
        scope=scope,
        note_types=[
            NoteTypeConfig(
                name="concept",
                description="Concept notes",
                folder="concepts/",
                required_sections=["Overview", "Examples"],
                contextual_questions=["What is X?"],
            ),
            NoteTypeConfig(
                name="flow",
                description="Flow notes",
                folder="flows/",
                required_sections=["Trigger", "Steps", "Outcome"],
                contextual_questions=["When does Y run?"],
            ),
            NoteTypeConfig(
                name="decision",
                description="Decision records",
                folder="decisions/",
                required_sections=["Context", "Options", "Rationale"],
                contextual_questions=["Why Z?"],
            ),
        ],
        data_sources=[DataSourceConfig(name="s", type="external", priority=2)],
        search_dimensions=["domain"],
        coverage_targets=CoverageTargets(
            categories=[
                CoverageCategory(
                    name="c1", note_type="concept", target_count=1, met_count=0
                ),
            ]
        ),
        budget=BudgetConfig(),
    )


def test_scaffold_writes_one_template_per_note_type(tmp_path: Path) -> None:
    spec = _spec_three_note_types()
    vault = tmp_path / "v"
    scaffold(spec, vault)

    tmpl_dir = vault / "data_vault" / "_templates"
    assert tmpl_dir.is_dir()
    md_files = sorted(tmpl_dir.glob("*.md"))
    assert len(md_files) == len(spec.note_types)
    names_found = {p.stem for p in md_files}
    expected = {nt.name.replace(" ", "_").lower() for nt in spec.note_types}
    assert names_found == expected

    for nt in spec.note_types:
        path = tmpl_dir / f"{nt.name}.md"
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        headings = [h.strip() for h in HEADING_RE.findall(text)]
        assert headings == list(nt.required_sections)


def test_rescaffold_templates_idempotent_mtime(tmp_path: Path) -> None:
    spec = _spec_three_note_types()
    vault = tmp_path / "v2"
    scaffold(spec, vault)
    tmpl_dir = vault / "data_vault" / "_templates"
    files = sorted(tmpl_dir.glob("*.md"))
    assert files
    before = {p.resolve(): p.stat().st_mtime_ns for p in files}

    scaffold(spec, vault)

    for p in files:
        assert p.stat().st_mtime_ns == before[p.resolve()]
