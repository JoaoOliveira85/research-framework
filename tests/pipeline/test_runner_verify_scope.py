"""Tier-3 integration: the pipeline's verify phase against a REAL vault.

Everything here runs the production ``_drive_verify`` and the production
``research_framework.processors.verify.verify`` — no mocks — over a vault
built by ``tests/_helpers/vault_factory.build_minimal_vault``.

This is the regression gate for two shipped defects that the existing runner
tests could not see, because they patched ``processors.verify.verify`` out
entirely:

1. ``_drive_verify`` called ``verify(vault)`` on the vault ROOT with auto-fix
   defaulted ON.  ``EXCLUDE_DIRS`` excluded only ``_pipeline``, ``_templates``
   and ``.obsidian``, so ``.claude/commands/*.md``, ``CLAUDE.md``,
   ``README.md``, ``raw_data/README.md``, ``research.spec.md`` and ``.venv/**``
   site-package READMEs were walked as notes, graded as orphans or
   missing-summary, and REWRITTEN in place.
2. Those bogus flags pushed the flag/notes ratio past ``fail_threshold`` — the
   FAIL that hit 7 of 7 real vaults on 2026-09-01.  A freshly generated vault
   FAILed its own verify phase.

Deliberately unmarked (no ``e2e``): it builds one vault and runs pure-Python
structural checks, no LLM and no subprocess.
"""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.pipeline.runner import (
    DONE,
    STATE_FILE,
    _blank_state,
    _corpus_dir,
    _drive_verify,
)
from tests._helpers.vault_factory import build_minimal_vault


def _snapshot(vault: Path) -> dict[Path, str]:
    """Every markdown file in the vault, keyed by path, excluding pipeline state."""
    return {
        p: p.read_text(encoding="utf-8")
        for p in sorted(vault.rglob("*.md"))
        if "_pipeline" not in p.relative_to(vault).parts
    }


def _run_verify_phase(vault: Path) -> dict:
    state = _blank_state("2026-09-01-1200", "2026-09-01T12:00:00Z")
    _drive_verify(vault, state, quiet=True)
    return state


class TestVerifyPhaseDoesNotMutate:
    def test_claude_commands_are_untouched(self, tmp_path: Path) -> None:
        vault = build_minimal_vault(tmp_path)
        commands = sorted((vault / ".claude" / "commands").glob("*.md"))
        assert commands, "vault factory should scaffold .claude/commands/*.md"
        before = {p: p.read_text(encoding="utf-8") for p in commands}

        _run_verify_phase(vault)

        for path, text in before.items():
            assert path.read_text(encoding="utf-8") == text, path

    def test_no_markdown_anywhere_is_rewritten(self, tmp_path: Path) -> None:
        vault = build_minimal_vault(tmp_path)
        before = _snapshot(vault)

        _run_verify_phase(vault)

        assert _snapshot(vault) == before

    def test_venv_site_packages_are_untouched(self, tmp_path: Path) -> None:
        vault = build_minimal_vault(tmp_path)
        vendored = (
            vault
            / ".venv"
            / "lib"
            / "python3.12"
            / "site-packages"
            / "pkg"
            / "README.md"
        )
        vendored.parent.mkdir(parents=True, exist_ok=True)
        vendored.write_text("# vendored package\n", encoding="utf-8")

        _run_verify_phase(vault)

        assert vendored.read_text(encoding="utf-8") == "# vendored package\n"


class TestVerifyPhaseScope:
    def test_grades_the_corpus_not_the_vault_root(self, tmp_path: Path) -> None:
        vault = build_minimal_vault(tmp_path)
        assert _corpus_dir(vault) == vault / "data_vault"

    def test_corpus_dir_falls_back_to_the_vault_root(self, tmp_path: Path) -> None:
        bare = tmp_path / "bare"
        bare.mkdir()
        assert _corpus_dir(bare) == bare

    def test_corpus_dir_honours_spec_parse_json(self, tmp_path: Path) -> None:
        vault = tmp_path / "v"
        (vault / "notes").mkdir(parents=True)
        (vault / "_pipeline").mkdir()
        (vault / "_pipeline" / "spec-parse.json").write_text(
            json.dumps({"vault_corpus_dir": "notes"}), encoding="utf-8"
        )
        assert _corpus_dir(vault) == vault / "notes"

    def test_tooling_markdown_is_not_counted_as_notes(self, tmp_path: Path) -> None:
        """A freshly generated vault has no notes yet — only tooling markdown."""
        vault = build_minimal_vault(tmp_path)

        state = _run_verify_phase(vault)

        assert state["phases"]["verify"]["summary"]["notes_checked"] == 0

    def test_fresh_vault_passes_its_own_verify_phase(self, tmp_path: Path) -> None:
        """The 2026-09-01 FAIL: a vault failed on its own scaffolding."""
        vault = build_minimal_vault(tmp_path)

        state = _run_verify_phase(vault)

        assert state["phases"]["verify"]["summary"]["verdict"] == "PASS"
        assert state["phases"]["verify"]["status"] == DONE

    def test_real_notes_are_still_graded(self, tmp_path: Path) -> None:
        """Scoping must not blind verify to the corpus it exists to check."""
        vault = build_minimal_vault(tmp_path)
        note = vault / "data_vault" / "01 - Concepts" / "Lonely.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(
            "---\ntitle: Lonely\n---\n\nNo links in or out.\n", encoding="utf-8"
        )

        state = _run_verify_phase(vault)
        summary = state["phases"]["verify"]["summary"]

        assert summary["notes_checked"] == 1
        assert summary["verdict"] == "FAIL"  # orphan + missing status/related/summary

    def test_state_file_is_written(self, tmp_path: Path) -> None:
        vault = build_minimal_vault(tmp_path)

        _run_verify_phase(vault)

        state = json.loads((vault / STATE_FILE).read_text(encoding="utf-8"))
        assert "verdict" in state["phases"]["verify"]["summary"]
