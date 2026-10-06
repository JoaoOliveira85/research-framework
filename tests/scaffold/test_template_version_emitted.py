"""Tests that generated vault scaffold files carry _template_version metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from research_framework.generator.scaffold import scaffold
from research_framework.generator.templates import render_all
from research_framework.spec.simple import load as load_spec

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
_SAMPLE_SPEC = FIXTURES_DIR / "sample-spec.md"

# Scaffold files that are written directly (not managed for _template_version)
# because their content is append-only or user-controlled.
_SKIP_PATHS = {
    "_templates/CHANGELOG.md",  # version table is hand-edited, not _template_version
    # Feature 017 (US6/US7): index placeholders auto-regenerated each cycle by
    # `indexer.rebuild_all`; not managed by the migrator.
    "data_vault/_index.md",
    "data_vault/_concepts.md",
    "data_vault/_graph.md",
}


def _parse_frontmatter(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        fm = yaml.safe_load(parts[1])
        return fm if isinstance(fm, dict) else None
    except yaml.YAMLError:
        return None


@pytest.fixture(scope="module")
def generated_vault(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A freshly generated vault from the sample spec."""
    spec = load_spec(_SAMPLE_SPEC)
    vault = tmp_path_factory.mktemp("vault")
    scaffold(spec, vault)
    render_all(spec, vault)
    return vault


def _scaffold_markdown_files(vault: Path) -> list[Path]:
    """Return all markdown files that should carry _template_version."""
    results = []
    for p in vault.rglob("*.md"):
        rel = p.relative_to(vault).as_posix()
        if rel.startswith(".git/"):
            continue
        if rel in _SKIP_PATHS:
            continue
        # Skip user-note template files that use template_version (not _template_version)
        if rel.startswith("_templates/") and rel != "_templates/CHANGELOG.md":
            continue
        # Feature 017 (US8): per-vault note templates inside data_vault/_templates/
        # are user-customizable (mirror legacy _templates/ semantics).
        if rel.startswith("data_vault/_templates/"):
            continue
        results.append(p)
    return sorted(results)


def _non_markdown_scaffold_files(vault: Path) -> list[Path]:
    """Return non-markdown scaffold files that should have .tmpl-versions.json."""
    results = []
    for p in vault.rglob("*"):
        if p.is_dir() or p.suffix.lower() == ".md":
            continue
        rel = p.relative_to(vault).as_posix()
        if rel.startswith(".git/") or rel.endswith(".tmpl-versions.json"):
            continue
        # Only known scaffold extensions
        if p.suffix.lower() in (
            ".json",
            ".yaml",
            ".yml",
            ".py",
            ".sh",
            ".service",
        ) or p.name in ("vault",):
            results.append(p)
    return sorted(results)


class TestTemplateVersionEmitted:
    def test_every_markdown_scaffold_file_has_template_version(
        self, generated_vault: Path
    ) -> None:
        """(a) every markdown scaffold file has _template_version in frontmatter."""
        md_files = _scaffold_markdown_files(generated_vault)
        assert md_files, "no markdown scaffold files found in generated vault"
        missing = []
        for p in md_files:
            fm = _parse_frontmatter(p)
            rel = p.relative_to(generated_vault).as_posix()
            if fm is None or "_template_version" not in fm:
                missing.append(rel)
        assert not missing, (
            f"Markdown scaffold files missing _template_version frontmatter: {missing}"
        )

    def test_template_version_is_integer(self, generated_vault: Path) -> None:
        """_template_version values must be integers (not strings)."""
        md_files = _scaffold_markdown_files(generated_vault)
        bad = []
        for p in md_files:
            fm = _parse_frontmatter(p)
            rel = p.relative_to(generated_vault).as_posix()
            if fm and "_template_version" in fm:
                if not isinstance(fm["_template_version"], int):
                    bad.append(f"{rel}: got {type(fm['_template_version']).__name__}")
        assert not bad, f"Non-integer _template_version values: {bad}"

    def test_every_non_markdown_scaffold_file_has_tmpl_versions_json(
        self, generated_vault: Path
    ) -> None:
        """(b) every non-markdown scaffold file's directory has .tmpl-versions.json."""
        non_md = _non_markdown_scaffold_files(generated_vault)
        assert non_md, "no non-markdown scaffold files found"
        missing = []
        for p in non_md:
            sibling = p.parent / ".tmpl-versions.json"
            rel = p.relative_to(generated_vault).as_posix()
            if not sibling.exists():
                missing.append(rel)
                continue
            try:
                data = json.loads(sibling.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                missing.append(f"{rel} (sibling JSON invalid)")
                continue
            if p.name not in data:
                missing.append(f"{rel} (name missing from sibling JSON)")
        assert not missing, (
            f"Non-markdown scaffold files without .tmpl-versions.json entry: {missing}"
        )
