"""SG-004 separates a Principle-VI violation from a style finding (issue #293).

Constitution Principle VI ("Two notes for the same concept MUST NOT exist") is
non-negotiable, and SG-004 is its only post-write backstop. It used to map
*every* non-zero ``validate_vault.py`` exit to ``WARN``, and only a ``FAIL``
drives the correction loop — so a duplicate note that slipped the pre-write
``proposed_filenames`` check was detected, logged, and written anyway.

Spec 017's gate table chose WARN deliberately for validate_vault findings ("log
violations for next cycle") and spec 019 US5 kept a soft default for backwards
compatibility. That judgement is preserved here: only the duplicate class is
promoted, everything else still WARNs.

The last test is a real producer↔consumer contract — it runs the actual script
against a vault with real duplicate notes, so a rename of the script's
``DUPLICATE_FIELD`` breaks the build rather than silently re-downgrading
Principle VI.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from research_framework.pipeline.gates_step import SG004_validate_vault_wrapper

REPO_ROOT = Path(__file__).resolve().parents[2]

_DUPLICATE_STDOUT = """FAIL  data_vault/Widget 2.md
      duplicate: OS-style numbered sibling of 'Widget.md'

1 violation(s) found. Fix before proceeding to Phase 3.
"""

_STYLE_STDOUT = """FAIL  data_vault/Widget.md
      summary: missing required frontmatter field

1 violation(s) found. Fix before proceeding to Phase 3.
"""

_NOTE = """---
title: {title}
note_type: concept
coverage_category: technical
summary: A widget that does widget things for the platform.
source_urls: [https://example.com/widget]
tags: [widget]
---

The widget coordinates things. It has enough body text here to clear the note
quality bar without needing anything else from the vault.
"""


def _stub_run(returncode: int, stdout: str, stderr: str = "") -> object:
    def fake_run(*_a: object, **_k: object) -> MagicMock:
        r = MagicMock()
        r.returncode = returncode
        r.stdout = stdout.encode()
        r.stderr = stderr.encode()
        return r

    return fake_run


def test_duplicate_note_is_a_fail_not_a_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", _stub_run(1, _DUPLICATE_STDOUT))
    result = SG004_validate_vault_wrapper(tmp_path)
    assert result.gate_id == "SG-004"
    assert result.status == "FAIL"
    assert result.metric_name == "validate_vault_duplicate_notes"
    assert result.metric_value == 1
    assert "Principle VI" in result.message


def test_duplicate_fail_carries_a_correction_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only FAIL results drive the correction loop, so the FAIL has to say what
    the note-writer should do about it."""
    monkeypatch.setattr(subprocess, "run", _stub_run(1, _DUPLICATE_STDOUT))
    result = SG004_validate_vault_wrapper(tmp_path)
    assert result.correction_hint
    assert "duplicate" in result.correction_hint


def test_non_duplicate_violations_still_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec 017's deliberate soft default for style/lint findings is preserved —
    this fix promotes the constitutional class only."""
    monkeypatch.setattr(subprocess, "run", _stub_run(1, _STYLE_STDOUT))
    result = SG004_validate_vault_wrapper(tmp_path)
    assert result.status == "WARN"
    assert result.metric_name == "validate_vault_violations"


def test_the_word_duplicate_in_a_message_does_not_forge_a_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The marker is the violation's FIELD, at its own indentation — a note
    whose message merely mentions duplicates is still a WARN."""
    stdout = (
        "FAIL  data_vault/Widget.md\n"
        "      summary: mentions a duplicate of the pricing table\n"
    )
    monkeypatch.setattr(subprocess, "run", _stub_run(1, stdout))
    assert SG004_validate_vault_wrapper(tmp_path).status == "WARN"


def test_clean_vault_still_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", _stub_run(0, "all checks passed\n"))
    assert SG004_validate_vault_wrapper(tmp_path).status == "PASS"


def test_contract_real_script_duplicate_notes_fail_the_gate(tmp_path: Path) -> None:
    """End-to-end producer↔consumer: the shipped ``validate_vault.py`` writes the
    marker, the gate reads it. No stubs — this is what pins the coupling."""
    vault = tmp_path / "vault"
    (vault / "data_vault").mkdir(parents=True)
    (vault / "scripts").mkdir(parents=True)
    (vault / "scripts" / "validate_vault.py").write_bytes(
        (REPO_ROOT / "scripts" / "validate_vault.py").read_bytes()
    )
    (vault / "data_vault" / "Widget.md").write_text(_NOTE.format(title="Widget"))
    # An OS-style numbered sibling: the exact spec-062 FR2 duplicate shape.
    (vault / "data_vault" / "Widget 2.md").write_text(_NOTE.format(title="Widget"))

    result = SG004_validate_vault_wrapper(vault)
    assert result.status == "FAIL", f"expected a Principle-VI FAIL, got {result}"
    assert result.metric_name == "validate_vault_duplicate_notes"


def test_contract_clean_vault_does_not_fail_the_gate(tmp_path: Path) -> None:
    """The negative half of the same contract: one note, no duplicate marker,
    so the gate must not be FAILing on something unrelated."""
    vault = tmp_path / "vault"
    (vault / "data_vault").mkdir(parents=True)
    (vault / "scripts").mkdir(parents=True)
    (vault / "scripts" / "validate_vault.py").write_bytes(
        (REPO_ROOT / "scripts" / "validate_vault.py").read_bytes()
    )
    (vault / "data_vault" / "Widget.md").write_text(_NOTE.format(title="Widget"))

    assert SG004_validate_vault_wrapper(vault).status != "FAIL"
