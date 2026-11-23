"""Spec 083 T006 — re-grade reads the notes quarantine under ``_pipeline/state/``."""

from __future__ import annotations

from pathlib import Path

from research_framework.cli.regrade import run_regrade
from research_framework.pipeline import state_layout as L
from tests.cli.test_regrade import _CRED_NOTE, _build_vault, _quarantine


def test_regrade_reinstates_from_the_state_quarantine(tmp_path: Path) -> None:
    vault = _build_vault(tmp_path)
    note = _quarantine(vault, "Fastify", url="https://fastify.dev/", notes=[_CRED_NOTE])
    assert note.parent == L.quarantine_dir(vault)
    assert run_regrade(vault, json_output=False) == 0
    assert not note.exists()
    assert (vault / "data_vault" / "01 - Concepts" / "Fastify.md").is_file()


def test_regrade_ignores_a_note_left_at_the_legacy_quarantine(tmp_path: Path) -> None:
    vault = _build_vault(tmp_path)
    legacy = vault / "_pipeline" / "quarantine" / "Fastify.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("---\ntitle: Fastify\n---\nBody.\n", encoding="utf-8")
    assert run_regrade(vault, json_output=False) == 0
    assert legacy.exists()
