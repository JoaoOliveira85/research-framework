"""Tests for SG-004 and SG-005 (T036, feature 017).

Per `spec.md` Story 9b:

- **SG-004**: After note-writer, wrap ``scripts/validate_vault.py``; exit 0 →
  PASS; non-zero → WARN with a violation summary carried in ``metric_value``.
- **SG-005**: Frontmatter completeness — FAIL when any note in the batch lacks
  ``coverage_category``, ``source_urls``, or ``summary`` in YAML frontmatter.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class TestSG004ValidateVaultWrapper:
    """Exit-code translation for the validate_vault subprocess wrapper."""

    def test_exit_zero_is_pass(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from research_framework.pipeline.gates_step import SG004_validate_vault_wrapper

        def fake_run(*_a: object, **_k: object) -> MagicMock:
            r = MagicMock()
            r.returncode = 0
            r.stdout = b"ok\n"
            r.stderr = b""
            return r

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = SG004_validate_vault_wrapper(tmp_path)
        assert result.gate_id == "SG-004"
        assert result.status == "PASS"

    def test_exit_nonzero_is_warn_with_summary_in_metric_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from research_framework.pipeline.gates_step import SG004_validate_vault_wrapper

        def fake_run(*_a: object, **_k: object) -> MagicMock:
            r = MagicMock()
            r.returncode = 3
            r.stdout = b"2 violations: missing frontmatter on a.md\n"
            r.stderr = b"detail line\n"
            return r

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = SG004_validate_vault_wrapper(tmp_path)
        assert result.gate_id == "SG-004"
        assert result.status == "WARN"
        mv = str(result.metric_value)
        assert "violation" in mv.lower() or "2" in mv


class TestSG005FrontmatterCompleteness:
    """Required frontmatter keys on every note path in the batch."""

    def _write_note(self, path: Path, fm: str, body: str = "x\n") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\n{fm}\n---\n\n{body}", encoding="utf-8")

    def test_passes_when_all_notes_have_required_keys(self, tmp_path: Path) -> None:
        from research_framework.pipeline.gates_step import (
            SG005_frontmatter_completeness,
        )

        self._write_note(
            tmp_path / "a.md",
            "coverage_category: concepts\n"
            "source_urls:\n  - https://example.com\n"
            "summary: short",
        )
        self._write_note(
            tmp_path / "b.md",
            "coverage_category: flows\n"
            "source_urls:\n  - https://b.example\n"
            "summary: also short",
        )
        r = SG005_frontmatter_completeness([tmp_path / "a.md", tmp_path / "b.md"])
        assert r.status == "PASS"

    def test_fails_when_coverage_category_missing(self, tmp_path: Path) -> None:
        from research_framework.pipeline.gates_step import (
            SG005_frontmatter_completeness,
        )

        self._write_note(
            tmp_path / "bad.md",
            "source_urls:\n  - https://x.test\nsummary: ok",
        )
        r = SG005_frontmatter_completeness([tmp_path / "bad.md"])
        assert r.status == "FAIL"
        assert r.correction_hint

    def test_fails_when_source_urls_missing(self, tmp_path: Path) -> None:
        from research_framework.pipeline.gates_step import (
            SG005_frontmatter_completeness,
        )

        self._write_note(
            tmp_path / "bad.md",
            "coverage_category: concepts\nsummary: ok",
        )
        r = SG005_frontmatter_completeness([tmp_path / "bad.md"])
        assert r.status == "FAIL"

    def test_fails_when_summary_missing(self, tmp_path: Path) -> None:
        from research_framework.pipeline.gates_step import (
            SG005_frontmatter_completeness,
        )

        self._write_note(
            tmp_path / "bad.md",
            "coverage_category: concepts\nsource_urls:\n  - https://x.test\n",
        )
        r = SG005_frontmatter_completeness([tmp_path / "bad.md"])
        assert r.status == "FAIL"

    def test_boundary_empty_string_values_treated_as_missing(
        self, tmp_path: Path
    ) -> None:
        from research_framework.pipeline.gates_step import (
            SG005_frontmatter_completeness,
        )

        self._write_note(
            tmp_path / "edge.md",
            'coverage_category: ""\nsource_urls: []\nsummary: ""\n',
        )
        r = SG005_frontmatter_completeness([tmp_path / "edge.md"])
        assert r.status == "FAIL"
