"""US1 (spec-019 / 0.2.28): the ``build.sh`` smoke gate MUST enforce
tier-2 contract tests in addition to the original tier-4/5 e2e suite.

Background:

Feature 018 (0.2.25) introduced a smoke gate that ran ONLY
``tests/pipeline/test_full_cycle_e2e.py`` + ``test_multi_cycle_e2e.py``
+ ``tests/_helpers/``. Three subsequent seam-bug fixes (0.2.25 budget
field, 0.2.26 resume preconditions, 0.2.27 source_file shape) all
shipped DESPITE that gate, because each is a tier-2 contract test
class that the gate didn't include.

Spec-019 extends the gate. This test pins the expanded test list so a
future trim is caught at CI time, not at release time.

Companion: ``specs/019-pipeline-architecture/spec.md`` US1.
"""

from __future__ import annotations

import re
from pathlib import Path

BUILD_SH = Path(__file__).parent.parent.parent / "build.sh"

# The expansion shipped in 0.2.28. Adding to this set is fine; removing
# requires a deliberate spec amendment (raise the bar, not lower it).
REQUIRED_IN_GATE: set[str] = {
    # Original feature-018 tier-4/5 e2e files:
    "tests/pipeline/test_full_cycle_e2e.py",
    "tests/pipeline/test_multi_cycle_e2e.py",
    "tests/_helpers/",
    # Spec-019 tier-2 contract additions:
    "tests/scripts/test_prompt_validator_contract.py",
    "tests/scripts/test_validate_cycle_research_schema.py",
    "tests/scripts/test_validate_cycle_source_file_shapes.py",
    "tests/scripts/test_validate_cycle_budget_aliases.py",
    "tests/scripts/test_validate_cycle_sources_consulted.py",
    "tests/scripts/test_validate_cycle_termination_fields.py",
    "tests/scripts/test_validate_spec.py",
    "tests/scripts/test_check_abstraction.py",
    "tests/scripts/test_quality_report.py",
    "tests/scripts/test_probe_runner.py",
    "tests/pipeline/test_preconditions_resume.py",
    "tests/pipeline/test_resume_phase3_completion.py",
    # Spec-019 / 0.2.29 — scout-validation correction loop:
    "tests/scripts/test_validate_cycle_sidecar.py",
    "tests/pipeline/test_cycle_runner_scout_correction.py",
    # Spec-019 / 0.2.29 — install wizard skip-redundant-questions:
    "tests/build/test_install_wizard_skip_redundant_questions.py",
    # 0.3.2 post-mortem (spec 022 + 025) — tier-6 fake-agent interception
    # gate. Catches in-process LLM-dispatch bugs (e.g. the plan_narrator /
    # _cycle_helpers bootstrap regression that 0.3.0 + 0.3.1 silently
    # shipped) that the static dispatch guard cannot reach. ~7s.
    "tests/quality/test_fake_agent_interception.py",
    # Self-reference (2026-05-25, MONDAY §1.3) — without this entry, a
    # commit that deletes the meta-test path from build.sh::SMOKE_TESTS
    # would silently remove the gate's enforcement of the whole set
    # below, and this very test would pass on the next CI run. Adding it
    # closes the recursive bootstrap loop: the gate now defends its own
    # presence.
    "tests/build/test_smoke_gate_enforces_contract_tier.py",
    # Issue #288: these 7 SMOKE_TESTS entries carried their own
    # ship-blocking rationale in build.sh's comments (spec 026 fixture
    # isolation, spec 068 coverage recompute, spec 067 wikilink
    # corruption, spec 027 vault update, spec 048 v1.1 observability x3)
    # but were never added here — so de-listing any of them from
    # SMOKE_TESTS was invisible to both tests below, including
    # test_fixture_isolation's runner-subprocess check, the only
    # automated end-to-end exercise of
    # `python -m research_framework.quality.runner` outside the release
    # job. `test_required_in_gate_has_no_untracked_smoke_entries` below
    # now also asserts the reverse direction, so a *future* SMOKE_TESTS
    # addition needs a matching entry here or that test fails — the two
    # sets can no longer drift apart silently again.
    "tests/quality/test_fixture_isolation.py",
    "tests/quality/test_coverage_recompute_regression.py",
    "tests/quality/test_wikilink_corruption_regression.py",
    "tests/cli/test_vault_update.py",
    "tests/observability/test_log_surfaces.py",
    "tests/observability/test_health_header.py",
    "tests/observability/test_vault_status.py",
}


def _parse_smoke_tests_array_from_build_sh() -> set[str]:
    """Extract the SMOKE_TESTS=(...) bash array from build.sh. Skips
    comment lines. Anchors on ``\n)`` so parens inside in-array comments
    (e.g. ``# (feature 018)``) don't confuse the parser."""
    text = BUILD_SH.read_text(encoding="utf-8")
    match = re.search(r"SMOKE_TESTS=\(\n(.*?)\n\)", text, re.DOTALL)
    assert match, "could not locate SMOKE_TESTS=(\\n ... \\n) block in build.sh"
    block = match.group(1)
    tests: set[str] = set()
    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'"([^"]+)"', line)
        if m:
            tests.add(m.group(1))
    return tests


def _strip_bash_comments(text: str) -> str:
    """Return ``text`` with full-line ``#`` comments removed. (Doesn't
    attempt to handle inline comments after code — the bash quote rules
    are too subtle for a one-liner; the surface we care about doesn't
    use inline comments.)"""
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def test_smoke_gate_includes_all_spec019_contract_files() -> None:
    """Every file in REQUIRED_IN_GATE must be present in the SMOKE_TESTS
    array. If this fails, someone removed a tier-2 contract test from
    ship-blocking — review spec-019 US1 before approving the change."""
    smoke = _parse_smoke_tests_array_from_build_sh()
    missing = REQUIRED_IN_GATE - smoke
    assert not missing, (
        f"build.sh SMOKE_TESTS is missing required tier-2 contract "
        f"entries: {sorted(missing)}. See spec-019 US1; the smoke gate "
        f"must enforce the full contract tier, not just e2e."
    )


def test_required_in_gate_has_no_untracked_smoke_entries() -> None:
    """Issue #288: `test_smoke_gate_includes_all_spec019_contract_files` only
    checked REQUIRED_IN_GATE - smoke — a file living in SMOKE_TESTS but
    absent from REQUIRED_IN_GATE was invisible to it, so removing that file
    from build.sh raised no alarm anywhere. Both sets must now match
    exactly: every SMOKE_TESTS entry gets ship-blocking protection here, and
    adding a new one (fine, per this module's own docstring) means adding
    the matching REQUIRED_IN_GATE entry in the same commit — a one-line
    mechanical step, not a process burden."""
    smoke = _parse_smoke_tests_array_from_build_sh()
    untracked = smoke - REQUIRED_IN_GATE
    assert not untracked, (
        f"build.sh SMOKE_TESTS has {sorted(untracked)} with no matching "
        "REQUIRED_IN_GATE entry — add it there too, so a future removal is "
        "caught the same way every other smoke-gate entry already is."
    )


def test_smoke_gate_files_actually_exist_on_disk() -> None:
    """Every file in SMOKE_TESTS must exist (directories or files). A
    typo or stale path is a silent bypass — pytest just skips missing
    paths and the gate appears to pass."""
    repo_root = BUILD_SH.parent
    smoke = _parse_smoke_tests_array_from_build_sh()
    missing_on_disk = [p for p in smoke if not (repo_root / p).exists()]
    assert not missing_on_disk, (
        f"build.sh references paths that don't exist on disk: "
        f"{missing_on_disk}. The smoke gate would silently skip these."
    )


def test_smoke_gate_block_exists_and_is_mandatory() -> None:
    """The smoke-gate block in build.sh must include an ``exit 1`` on
    failure with no escape hatch (no ``--skip-smoke``, no env-var
    bypass) in the EXECUTABLE bash (comments are allowed to describe
    the policy). Locks the 'no shipping past a red gate' promise."""
    text = BUILD_SH.read_text(encoding="utf-8")
    assert "SMOKE_TESTS=(" in text
    assert "exit 1" in text, "smoke gate must exit 1 on failure"
    code_only = _strip_bash_comments(text)
    assert "--skip-smoke" not in code_only, (
        "smoke gate must not accept --skip-smoke as an executable flag "
        "(comments describing the policy are fine); the only way to "
        "ship past a red gate is to delete the SMOKE_TESTS block, which "
        "is a deliberate code change."
    )
