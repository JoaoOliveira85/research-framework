"""Spec 084 T009 (scaffold half): a fresh vault starts with an empty backlog store."""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.generator.scaffold import scaffold
from research_framework.pipeline import backlog, state_layout
from research_framework.spec.parser import parse


def test_a_fresh_vault_has_an_empty_store_and_a_rendered_view(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    scaffold(parse(sample_spec_path), vault)

    store = state_layout.research_backlog_path(vault)
    assert json.loads(store.read_text(encoding="utf-8")) == {
        "schema_version": backlog.SCHEMA_VERSION,
        "entries": [],
    }
    view = backlog.view_path(vault).read_text(encoding="utf-8")
    assert "_pipeline/state/research-backlog.json" in view
    assert "research-backlog-view sha256=" in view
    # A fresh vault is converted, not "unconverted legacy Markdown".
    assert backlog.is_unconverted(vault) is False
    # A second scaffold leaves an existing store alone.
    before = store.read_bytes()
    scaffold(parse(sample_spec_path), vault)
    assert store.read_bytes() == before
