"""spec 053 US1 (T007) — code-first regression lock.

Proves the generalized source-authority gates produce IDENTICAL verdicts to the
pre-053 hardcoded gates on the `vault-code-first` fixture, now that the fixture
carries a `research.spec.md` declaring `role`/`priority` + note_type
`authoritative_role`/sections. These verdicts must not move when T009 (grounding)
and T010 (drift) generalize the gates.

Gate 3 (trunk-seed) code-first regression is covered directly in
`test_validate_cycle.py` (T008b), which unit-tests `check_termination_v2`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from research_framework.spec.parser import parse

GROUNDING = (
    Path(__file__).parent.parent.parent / "scripts" / "check_code_source_coverage.py"
)
DRIFT = Path(__file__).parent.parent.parent / "scripts" / "check_intent_drift.py"

# The 6 fixture notes, all type `service` (the hard, behaviour-authoritative type).
NOTES = (
    "service-agree.md",
    "service-disagree-flagged.md",
    "service-disagree-unflagged.md",
    "service-intent-none-applicable.md",
    "service-intent-pending.md",
    "service-prose-difference.md",
)


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
    )


def _stage_with_spec(fixtures_dir: Path, tmp_path: Path) -> Path:
    """Copy the service notes into a vault and derive `_pipeline/spec-parse.json`
    from the fixture's `research.spec.md` (the real parse path)."""
    vault = tmp_path / "vault"
    (vault / "data_vault").mkdir(parents=True)
    for name in NOTES:
        (vault / "data_vault" / name).write_text(
            (fixtures_dir / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    (vault / "_pipeline").mkdir(parents=True)
    spec = parse(fixtures_dir / "research.spec.md")
    (vault / "_pipeline" / "spec-parse.json").write_text(
        json.dumps(spec.to_dict()), encoding="utf-8"
    )
    return vault


def test_fixture_spec_is_valid_code_first(
    vault_code_first_fixtures_dir: Path,
) -> None:
    """The fixture spec parses + validates as a code-first 053 spec (unique
    behaviour trunk at priority 1, note_type authoritative_role declared)."""
    from research_framework.spec.schema import derive_trunk
    from research_framework.spec.validator import validate

    spec = parse(vault_code_first_fixtures_dir / "research.spec.md")
    validate(spec)
    trunk = derive_trunk(spec)
    assert trunk is not None and trunk.name == "GitHub repos"
    assert trunk.role == "behaviour"
    service = next(nt for nt in spec.note_types if nt.name == "service")
    assert service.authoritative_role == "behaviour"


def test_grounding_all_service_notes_pass(
    vault_code_first_fixtures_dir: Path, tmp_path: Path
) -> None:
    """Gate 1 verdict (unchanged): every service note cites a behaviour source."""
    vault = _stage_with_spec(vault_code_first_fixtures_dir, tmp_path)
    result = _run(GROUNDING, str(vault))
    assert result.returncode == 0, result.stdout + result.stderr


def test_drift_only_unflagged_disagreement_fails(
    vault_code_first_fixtures_dir: Path, tmp_path: Path
) -> None:
    """Gate 2 verdict (unchanged): only the unflagged disagreement violates."""
    vault = _stage_with_spec(vault_code_first_fixtures_dir, tmp_path)
    result = _run(DRIFT, str(vault))
    assert result.returncode == 1, result.stdout
    assert "service-disagree-unflagged.md" in result.stdout
    # The flagged disagreement must NOT be reported as a violation.
    assert "service-disagree-flagged.md" not in result.stdout
