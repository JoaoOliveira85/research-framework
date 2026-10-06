"""spec 053 US3 (T017) — trunk-inversion gate (FR-007).

The derived-trunk source MUST resolve to ledger verdict USED (or an *explained*
ACCESS_FAIL). FAIL when the trunk is NOT_REACHED / SKIPPED_RELEVANCE while any
branch source is USED — the deterministic bad-faith / path-of-least-resistance
detector.

⚠️ Depends on spec 048 v2 (the Source-Consideration Ledger). This codes against
the documented ledger contract + a fixture; the gate's wire-in (T019) is held
until 048 v2 ships the real `cycle-NNN-source-ledger.json`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from research_framework.spec.parser import parse

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "check_trunk_inversion.py"
FIXTURE = Path(__file__).parent.parent / "fixtures" / "vault-bad-faith"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True
    )


def _stage(tmp_path: Path, ledger: list[dict], cycle: int = 1) -> Path:
    vault = tmp_path / "vault"
    (vault / "_pipeline" / "cycles").mkdir(parents=True)
    spec = parse(FIXTURE / "research.spec.md")
    (vault / "_pipeline" / "spec-parse.json").write_text(
        json.dumps(spec.to_dict()), encoding="utf-8"
    )
    (
        vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-source-ledger.json"
    ).write_text(json.dumps(ledger), encoding="utf-8")
    return vault


def test_bad_faith_trunk_not_reached_fails(tmp_path: Path) -> None:
    vault = _stage(
        tmp_path,
        [
            {"source": "GitHub repos", "role": "behaviour", "verdict": "NOT_REACHED"},
            {"source": "Confluence", "role": "intent", "verdict": "USED"},
        ],
    )
    result = _run(str(vault))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "GitHub repos" in result.stdout
    assert "NOT_REACHED" in result.stdout


def test_trunk_skipped_relevance_while_branch_used_fails(tmp_path: Path) -> None:
    vault = _stage(
        tmp_path,
        [
            {
                "source": "GitHub repos",
                "role": "behaviour",
                "verdict": "SKIPPED_RELEVANCE",
            },
            {"source": "Confluence", "role": "intent", "verdict": "USED"},
        ],
    )
    result = _run(str(vault))
    assert result.returncode == 1, result.stdout


def test_trunk_used_passes(tmp_path: Path) -> None:
    vault = _stage(
        tmp_path,
        [
            {"source": "GitHub repos", "role": "behaviour", "verdict": "USED"},
            {"source": "Confluence", "role": "intent", "verdict": "USED"},
        ],
    )
    result = _run(str(vault))
    assert result.returncode == 0, result.stdout + result.stderr


def test_explained_trunk_access_fail_passes(tmp_path: Path) -> None:
    vault = _stage(
        tmp_path,
        [
            {
                "source": "GitHub repos",
                "role": "behaviour",
                "verdict": "ACCESS_FAIL",
                "reason": "GitHub MCP 403 — token expired",
            },
            {"source": "Confluence", "role": "intent", "verdict": "USED"},
        ],
    )
    result = _run(str(vault))
    assert result.returncode == 0, result.stdout + result.stderr


def test_unexplained_trunk_access_fail_fails(tmp_path: Path) -> None:
    """ACCESS_FAIL without a reason is not an explanation → still inverted."""
    vault = _stage(
        tmp_path,
        [
            {"source": "GitHub repos", "role": "behaviour", "verdict": "ACCESS_FAIL"},
            {"source": "Confluence", "role": "intent", "verdict": "USED"},
        ],
    )
    result = _run(str(vault))
    assert result.returncode == 1, result.stdout


def test_no_branch_used_does_not_fail(tmp_path: Path) -> None:
    """If nothing was USED (e.g. an empty cycle), there's no inversion to flag."""
    vault = _stage(
        tmp_path,
        [
            {"source": "GitHub repos", "role": "behaviour", "verdict": "NOT_REACHED"},
            {"source": "Confluence", "role": "intent", "verdict": "NOT_REACHED"},
        ],
    )
    result = _run(str(vault))
    assert result.returncode == 0, result.stdout + result.stderr


def test_missing_ledger_exits_2(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    spec = parse(FIXTURE / "research.spec.md")
    (vault / "_pipeline" / "spec-parse.json").write_text(json.dumps(spec.to_dict()))
    result = _run(str(vault))
    assert result.returncode == 2


def test_ambiguous_role_fallback_does_not_false_pass(tmp_path: Path) -> None:
    """When the trunk name misses and multiple ledger entries share the trunk
    role, an arbitrary role match must not falsely PASS."""
    vault = _stage(
        tmp_path,
        [
            {"source": "Legacy GH", "role": "behaviour", "verdict": "USED"},
            {"source": "Other GH", "role": "behaviour", "verdict": "NOT_REACHED"},
            {"source": "Confluence", "role": "intent", "verdict": "USED"},
        ],
    )
    result = _run(str(vault))
    # Trunk is "GitHub repos" (name miss). Two behaviour rows → no role fallback.
    # Trunk treated as NOT_REACHED while Confluence USED → inversion FAIL.
    assert result.returncode == 1, result.stdout + result.stderr
    assert "TRUNK INVERSION" in result.stdout
