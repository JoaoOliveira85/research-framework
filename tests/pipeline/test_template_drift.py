"""Tests for template_drift — per-file template-version reader."""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.pipeline.template_drift import read_template_version


class TestReadTemplateVersion:
    def test_reads_template_version_from_markdown_frontmatter(
        self, tmp_path: Path
    ) -> None:
        """(a) reads _template_version from markdown frontmatter."""
        f = tmp_path / "note.md"
        f.write_text("---\n_template_version: 3\ntitle: Test\n---\n# Body\n")
        assert read_template_version(f) == 3

    def test_reads_template_version_from_sibling_json_for_non_markdown(
        self, tmp_path: Path
    ) -> None:
        """(b) reads sibling .tmpl-versions.json for non-markdown files."""
        script = tmp_path / "vault"
        script.write_text("#!/bin/bash\necho hi\n")
        sibling = tmp_path / ".tmpl-versions.json"
        sibling.write_text(json.dumps({"vault": 2}))
        assert read_template_version(script) == 2

    def test_returns_none_when_markdown_has_no_frontmatter(
        self, tmp_path: Path
    ) -> None:
        """(c) returns None when markdown has no frontmatter."""
        f = tmp_path / "plain.md"
        f.write_text("# Just a heading\nNo frontmatter here.\n")
        assert read_template_version(f) is None

    def test_returns_none_when_no_sibling_json_for_non_markdown(
        self, tmp_path: Path
    ) -> None:
        """(c) returns None when non-markdown has no sibling .tmpl-versions.json."""
        script = tmp_path / "run.sh"
        script.write_text("#!/bin/bash\n")
        assert read_template_version(script) is None

    def test_returns_none_when_frontmatter_lacks_template_version_key(
        self, tmp_path: Path
    ) -> None:
        """(c) returns None when frontmatter exists but _template_version key is absent."""
        f = tmp_path / "note.md"
        f.write_text("---\ntitle: Something\nauthor: me\n---\n# Body\n")
        assert read_template_version(f) is None

    def test_malformed_yaml_frontmatter_treated_as_version_unknown(
        self, tmp_path: Path
    ) -> None:
        """(d) malformed YAML frontmatter returns None without raising."""
        f = tmp_path / "broken.md"
        f.write_text("---\n: bad: yaml: [\n---\n# Body\n")
        assert read_template_version(f) is None

    def test_malformed_sibling_json_treated_as_version_unknown(
        self, tmp_path: Path
    ) -> None:
        """(d) malformed .tmpl-versions.json returns None without raising."""
        script = tmp_path / "vault"
        script.write_text("#!/bin/bash\n")
        sibling = tmp_path / ".tmpl-versions.json"
        sibling.write_text("{bad json")
        assert read_template_version(script) is None

    def test_sibling_json_missing_key_for_file(self, tmp_path: Path) -> None:
        """(c) sibling JSON exists but doesn't contain the file's name → None."""
        script = tmp_path / "vault"
        script.write_text("#!/bin/bash\n")
        sibling = tmp_path / ".tmpl-versions.json"
        sibling.write_text(json.dumps({"other_script": 1}))
        assert read_template_version(script) is None

    def test_returns_integer_not_string(self, tmp_path: Path) -> None:
        """Version read from frontmatter must be an int."""
        f = tmp_path / "note.md"
        f.write_text("---\n_template_version: 5\n---\n")
        result = read_template_version(f)
        assert isinstance(result, int)
        assert result == 5
