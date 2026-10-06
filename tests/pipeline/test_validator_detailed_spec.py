"""Regression-lock: validator traverses detailed-spec frontmatter fields."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from research_framework.vault.frontmatter import parse_frontmatter

VALIDATE_VAULT = Path(__file__).resolve().parents[2] / "scripts" / "validate_vault.py"


def _load_validate_vault():
    spec = importlib.util.spec_from_file_location("validate_vault", VALIDATE_VAULT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["validate_vault"] = module
    spec.loader.exec_module(module)
    return module


def test_validator_traverses_detailed_spec_frontmatter_fields(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    note_dir = vault / "data_vault" / "Topics"
    note_dir.mkdir(parents=True)
    body_text = " ".join(["word"] * 210)
    note_path = note_dir / "Detailed.md"
    note_path.write_text(
        f"""---
title: Detailed Note
type: concept
summary: Detailed-spec shaped note for FR-011 regression lock.
tags: [ai, test]
source_urls:
  - url: https://example.com/paper
    role: primary
related: []
created: 2026-06-03
updated: 2026-06-03
lifecycle:
  created_at_cycle: 3
template_version: "1.0.0"
---
{body_text}
""",
        encoding="utf-8",
    )

    fm, _body = parse_frontmatter(note_path)
    assert fm.get("lifecycle", {}).get("created_at_cycle") == 3
    assert fm.get("template_version") == "1.0.0"
    assert isinstance(fm.get("source_urls"), list)

    vv = _load_validate_vault()
    violations, warnings = vv.validate(vault)
    note_violations = [v for v in violations if v.file == note_path]
    assert not note_violations
    lifecycle_warnings = [
        w
        for w in warnings
        if w.file == note_path and "lifecycle.created_at_cycle" in w.field
    ]
    assert not lifecycle_warnings
