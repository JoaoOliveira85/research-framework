"""Tests for scripts/check_intent_drift.py — code/intent drift detection."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "check_intent_drift.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True
    )


def _stage(fixtures_dir: Path, tmp_path: Path, *fixture_names: str) -> Path:
    """Copy selected fixture notes into a fresh vault under tmp_path."""
    vault = tmp_path / "vault"
    (vault / "data_vault").mkdir(parents=True)
    for name in fixture_names:
        shutil.copy(fixtures_dir / name, vault / "data_vault" / name)
    return vault


def _write_note_with_sections(
    vault: Path,
    name: str,
    ntype: str,
    authority_heading: str,
    authority_body: str,
    complementary_heading: str,
    complementary_body: str,
    *,
    authority_drift: bool | None = None,
    legacy_flag: bool | None = None,
) -> None:
    (vault / "data_vault").mkdir(parents=True, exist_ok=True)
    fm = ["---", f"type: {ntype}", "intent_status: captured"]
    if authority_drift is not None:
        fm.append(f"authority_drift: {str(authority_drift).lower()}")
        fm.append("drift_notes: [explained]")
    if legacy_flag is not None:
        fm.append(f"intent_implementation_drift: {str(legacy_flag).lower()}")
        fm.append("drift_notes: [explained]")
    fm.append("---")
    body = (
        f"\n## {authority_heading}\n\n{authority_body}\n\n"
        f"## {complementary_heading}\n\n{complementary_body}\n"
    )
    (vault / "data_vault" / name).write_text("\n".join(fm) + body, encoding="utf-8")


def _write_spec(vault: Path, note_types: list[dict]) -> None:
    (vault / "_pipeline").mkdir(parents=True, exist_ok=True)
    (vault / "_pipeline" / "spec-parse.json").write_text(
        json.dumps({"note_types": note_types}), encoding="utf-8"
    )


class TestGeneralizedDriftSections:
    """spec 053 FR-005 / T010 — the drift gate compares the note_type's declared
    authority/complementary sections (opt-in) and honours the renamed
    `authority_drift` flag."""

    def test_custom_sections_drift_fails_unflagged(self, tmp_path: Path) -> None:
        """A finding note_type with non-default headings is drift-checked on
        those headings — the hardcoded gate would have found no sections and
        skipped (PASS); the generalized gate FAILs the unflagged disagreement."""
        vault = tmp_path / "vault"
        _write_spec(
            vault,
            [
                {
                    "name": "finding",
                    "authoritative_role": "domain",
                    "authority_section": "## Evidence",
                    "complementary_section": "## Interpretation",
                }
            ],
        )
        _write_note_with_sections(
            vault,
            "finding-drift.md",
            "finding",
            "Evidence",
            "Latency: 200ms. Owner: SRE.",
            "Interpretation",
            "Latency: 900ms. Owner: SRE.",
        )
        result = _run(str(vault))
        assert result.returncode == 1, result.stdout
        assert "from ## Evidence" in result.stdout
        assert "from ## Interpretation" in result.stdout
        assert "from ## Current Behaviour" not in result.stdout

    def test_authority_drift_flag_is_honoured(self, tmp_path: Path) -> None:
        """A disagreement flagged with the new `authority_drift: true` passes."""
        vault = tmp_path / "vault"
        _write_spec(
            vault,
            [
                {
                    "name": "finding",
                    "authoritative_role": "domain",
                    "authority_section": "## Evidence",
                    "complementary_section": "## Interpretation",
                }
            ],
        )
        _write_note_with_sections(
            vault,
            "finding-flagged.md",
            "finding",
            "Evidence",
            "Latency: 200ms.",
            "Interpretation",
            "Latency: 900ms.",
            authority_drift=True,
        )
        result = _run(str(vault))
        assert result.returncode == 0, result.stdout

    def test_note_type_without_both_sections_is_skipped(self, tmp_path: Path) -> None:
        """Opt-in (D3): a note_type declaring only one section is not drift-checked."""
        vault = tmp_path / "vault"
        _write_spec(
            vault,
            [
                {
                    "name": "reference",
                    "authoritative_role": "domain",
                    "authority_section": "## Evidence",
                }
            ],
        )
        _write_note_with_sections(
            vault,
            "ref.md",
            "reference",
            "Evidence",
            "Latency: 200ms.",
            "Interpretation",
            "Latency: 900ms.",
        )
        result = _run(str(vault))
        assert result.returncode == 0, result.stdout


def test_agree_passes(vault_code_first_fixtures_dir: Path, tmp_path: Path) -> None:
    vault = _stage(vault_code_first_fixtures_dir, tmp_path, "service-agree.md")
    result = _run(str(vault))
    assert result.returncode == 0, result.stdout + result.stderr


def test_unflagged_drift_fails(
    vault_code_first_fixtures_dir: Path, tmp_path: Path
) -> None:
    vault = _stage(
        vault_code_first_fixtures_dir, tmp_path, "service-disagree-unflagged.md"
    )
    result = _run(str(vault))
    assert result.returncode == 1
    assert "DRIFT UNFLAGGED" in result.stdout
    assert "retries" in result.stdout


def test_flagged_drift_passes(
    vault_code_first_fixtures_dir: Path, tmp_path: Path
) -> None:
    vault = _stage(
        vault_code_first_fixtures_dir, tmp_path, "service-disagree-flagged.md"
    )
    result = _run(str(vault))
    assert result.returncode == 0, result.stdout


def test_intent_pending_skipped(
    vault_code_first_fixtures_dir: Path, tmp_path: Path
) -> None:
    vault = _stage(vault_code_first_fixtures_dir, tmp_path, "service-intent-pending.md")
    result = _run(str(vault))
    assert result.returncode == 0, result.stdout


def test_none_applicable_skipped(
    vault_code_first_fixtures_dir: Path, tmp_path: Path
) -> None:
    vault = _stage(
        vault_code_first_fixtures_dir, tmp_path, "service-intent-none-applicable.md"
    )
    result = _run(str(vault))
    assert result.returncode == 0, result.stdout


def test_prose_only_difference_not_flagged(
    vault_code_first_fixtures_dir: Path, tmp_path: Path
) -> None:
    """Narrative differences without structured facts must not be flagged (v1)."""
    vault = _stage(
        vault_code_first_fixtures_dir, tmp_path, "service-prose-difference.md"
    )
    result = _run(str(vault))
    assert result.returncode == 0, result.stdout


def test_json_output_format(
    vault_code_first_fixtures_dir: Path, tmp_path: Path
) -> None:
    vault = _stage(
        vault_code_first_fixtures_dir, tmp_path, "service-disagree-unflagged.md"
    )
    result = _run(str(vault), "--json")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["scanned"] == 1
    assert len(payload["violations"]) >= 1
    assert payload["violations"][0]["fact"]
    assert payload["violations"][0]["code_value"]
    assert payload["violations"][0]["intent_value"]


def test_missing_vault_exits_2(tmp_path: Path) -> None:
    result = _run(str(tmp_path / "nope"))
    assert result.returncode == 2
    assert "not found" in result.stderr


def test_whole_fixture_dir(vault_code_first_fixtures_dir: Path, tmp_path: Path) -> None:
    """All 6 fixtures together — should fail only because of the unflagged one."""
    vault = tmp_path / "vault"
    (vault / "data_vault").mkdir(parents=True)
    for p in vault_code_first_fixtures_dir.glob("*.md"):
        shutil.copy(p, vault / "data_vault" / p.name)
    result = _run(str(vault))
    assert result.returncode == 1, result.stdout
    # Only the unflagged disagreement should violate
    assert "service-disagree-unflagged.md" in result.stdout
    assert "service-disagree-flagged.md" not in result.stdout
