"""Phase 2 entry preconditions (6 checks).

Returns ``(all_pass, unmet_messages)``.

The check set was originally designed for **initial generate** (Phase 0/1
have finished, we're about to enter Phase 2 for the first time). When v0.2.x
gained ``--resume``, those same checks were dropped onto the resume path
unchanged. Three of them are inappropriate for resume:

- **Precondition 1** runs the framework's own pytest suite. It exists to
  catch developers running ``generate`` against a broken framework checkout.
  On a bundled install the framework is pip-installed (so the wheel install
  already verified its integrity) and the bundled vault does NOT ship
  ``scripts/tests/``. The v0.2.x fallback that ran ``pytest tests/scripts/``
  from CWD silently picked up *any* ``tests/scripts/`` directory the user
  happened to be standing in (or, worse, blew up because none existed) —
  always failing on real-world bundled installs.

- **Precondition 2** demands ``validate_vault.py`` exit 0. That is exactly
  the opposite of what ``--resume`` means: we're resuming **because** the
  vault still has unresolved quality issues that later cycles are supposed
  to fix. The cycle's own SG-004 gate handles validate_vault findings
  correctly (downgrades vault-issues to WARN); the precondition was the
  only thing turning those WARNs back into a hard block.

- **Precondition 6** runs source preflight. The preflight checker's
  recognized-access-method set is narrower than the spec validator's, so a
  spec with ``access_method: "web fetch"`` or ``"local filesystem"``
  reaches preflight and gets reported as "unreachable: unknown
  access_method". That's a preflight bug, not a real reachability problem
  — the existing cycles ran fine against those sources. On resume we
  downgrade the preflight verdict to WARN so it doesn't block.

v0.2.26 introduces ``for_resume: bool`` to encode the semantic difference.
When ``True``:

- Precondition 1 is skipped with an INFO breadcrumb (framework was already
  installed and previous cycles ran).
- Precondition 2 is skipped with an INFO breadcrumb (cycle's SG-004 gate
  owns this signal).
- Precondition 6 still runs, but a fail verdict becomes a warning instead
  of an unmet entry. A spec that's **fundamentally** broken still trips
  preconditions 3/4/5 (structural files) so we don't accept a corrupted
  vault.

Initial generate still runs all six (after the Precondition-1 fallback
bug is also fixed: we only run the framework-tests fallback when the
caller's CWD actually looks like the research-framework repo).
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

from research_framework.spec.schema import SpecValidationError

from .preflight import check_all, load_spec_for_preflight

logger = logging.getLogger(__name__)


def _cwd_looks_like_framework_repo() -> bool:
    """Best-effort detection of "am I running from inside the framework repo
    source tree?". Used by precondition 1 to decide whether the
    framework-tests fallback should run at all. We look for two co-located
    markers (``pyproject.toml`` declaring ``research-framework`` AND a
    ``tests/scripts/`` directory). Both being present is unambiguous; either
    one alone could be a coincidence.
    """
    cwd = Path.cwd()
    pyproject = cwd / "pyproject.toml"
    scripts_tests_dir = cwd / "tests" / "scripts"
    if not (pyproject.is_file() and scripts_tests_dir.is_dir()):
        return False
    try:
        pyproject_text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    return (
        "research-framework" in pyproject_text or "research_framework" in pyproject_text
    )


def check(
    vault_dir: Path,
    *,
    for_resume: bool = False,
) -> tuple[bool, list[str]]:
    """Run the Phase-2 entry preconditions.

    Returns ``(all_pass, unmet)``. ``unmet`` is the list of blocking
    problems the caller should surface to the user.

    Args:
        vault_dir: The vault root to inspect.
        for_resume: Set to ``True`` when called from the ``--resume`` path.
            Skips Precondition 1 and 2 entirely and downgrades Precondition
            6 (source preflight) from fail→warn. See module docstring for
            the rationale.
    """
    unmet: list[str] = []

    # ------------------------------------------------------------------
    # 1. Framework tests (skip on --resume; skip if no embedded vault tests
    #    AND CWD is not the framework repo).
    # ------------------------------------------------------------------
    if for_resume:
        logger.info(
            "precondition 1 (framework tests): skipped on --resume "
            "(framework already installed, previous cycle ran)"
        )
    else:
        scripts_tests = vault_dir / "scripts" / "tests"
        if scripts_tests.exists():
            # Vault ships its own test directory — run those.
            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(scripts_tests), "-q"],
                capture_output=True,
                cwd=vault_dir,
                # Isolate the nested pytest in its own session so any
                # process-group signal it raises (tests that exercise
                # os.killpg, e.g. the process-tree regression suite) cannot
                # escape to OUR process group — which, under the build.sh
                # smoke gate, IS the gate's own pytest. Without this, a
                # killpg inside the nested run takes the gate down with it
                # on Linux (release CI exit 143; see spec-051 / 0.7.x fix).
                start_new_session=True,
            )
            if result.returncode != 0:
                unmet.append("precondition 1: pytest scripts/tests/ failed")
        elif _cwd_looks_like_framework_repo():
            # Developer is running ``generate`` from a framework checkout —
            # run the framework's own tests as a sanity check.
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/scripts/", "-q"],
                capture_output=True,
                start_new_session=True,  # sever signal escape to caller; see note above
            )
            if result.returncode != 0:
                unmet.append(
                    "precondition 1: pytest tests/scripts/ failed in "
                    "research-framework repo"
                )
        else:
            # Bundled-install path: framework is pip-installed (the wheel
            # install verified it) and there are no tests to run. Don't
            # invent a failure.
            logger.info(
                "precondition 1 (framework tests): no scripts/tests/ in "
                "vault and CWD is not the framework repo; skipping. "
                "Framework integrity was verified at install time."
            )

    # ------------------------------------------------------------------
    # 2. validate_vault.py (skip on --resume).
    # ------------------------------------------------------------------
    if for_resume:
        logger.info(
            "precondition 2 (validate_vault.py): skipped on --resume "
            "(SG-004 gate inside the cycle owns this signal; "
            "validate_vault violations are why we're running more cycles)"
        )
    else:
        validator = vault_dir / "scripts" / "validate_vault.py"
        if not validator.exists():
            unmet.append(
                f"precondition 2: scripts/validate_vault.py missing in {vault_dir}"
            )
        else:
            result = subprocess.run(
                [sys.executable, str(validator), str(vault_dir)],
                capture_output=True,
            )
            if result.returncode != 0:
                unmet.append("precondition 2: validate_vault.py reports violations")

    # ------------------------------------------------------------------
    # 3-5. Structural files. ALWAYS required (resume needs them too).
    # ------------------------------------------------------------------
    targets_file = vault_dir / "_pipeline" / "coverage-targets.json"
    if not targets_file.exists():
        unmet.append("precondition 3: _pipeline/coverage-targets.json missing")
    else:
        try:
            json.loads(targets_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            unmet.append(f"precondition 3: coverage-targets.json malformed ({e})")

    if not (vault_dir / "_pipeline" / "budget-log.md").exists():
        unmet.append("precondition 4: _pipeline/budget-log.md missing")

    claude = vault_dir / "CLAUDE.md"
    if not claude.exists():
        unmet.append("precondition 5: CLAUDE.md missing")
    else:
        text = claude.read_text(encoding="utf-8").lower()
        if "naming convention" not in text:
            unmet.append(
                "precondition 5: CLAUDE.md does not declare a naming convention"
            )

    # ------------------------------------------------------------------
    # 6. Source preflight (downgrade fail→warn on --resume).
    # ------------------------------------------------------------------
    spec_path = vault_dir / "research.spec.md"
    if not spec_path.exists():
        unmet.append(
            "precondition 6: research.spec.md missing — cannot run source preflight"
        )
    else:
        try:
            spec = load_spec_for_preflight(spec_path, vault_dir)
        except SpecValidationError as e:
            unmet.append(
                f"precondition 6: research.spec.md invalid for source preflight: {e}"
            )
        except Exception as e:
            unmet.append(
                "precondition 6: could not load research.spec.md for source preflight: "
                f"{e}"
            )
        else:
            # spec 069 FR2: declared-source backing is a hard, fail-closed gate
            # (not a transient connectivity issue), so it is NOT downgraded on
            # --resume — an unbacked source must be fixed before any cycle runs.
            from research_framework.spec.source_backing import (
                build_available_registry,
                credibility_binding,
                source_is_backed,
                unbacked_message,
                unbindable_credibility_message,
            )

            registry = build_available_registry(vault_dir)
            for ds in spec.data_sources:
                if source_is_backed(ds, registry) == "unbacked":
                    unmet.append(f"precondition 6: {unbacked_message(ds.name)}")
                # spec 070 FR2 is scoped to SCAFFOLDING ("scaffolding MUST fail
                # closed"), so here it WARNs rather than blocks. The distinction
                # is deliberate: an unbacked source (above) means a cycle cannot
                # do its job, whereas an inert credibility claim only means one
                # declaration is doing nothing — and a catch-all source like
                # "Open web search" is legitimately unbindable, since you cannot
                # enumerate the domains of the open web. Blocking an existing
                # vault mid-life over that would be disproportionate; the spec
                # gate catches it when the spec is written or regenerated.
                if credibility_binding(ds, registry) == "unbindable":
                    logger.warning(
                        "precondition 6: %s", unbindable_credibility_message(ds.name)
                    )

            preflight_result = check_all(spec, vault_dir)
            if preflight_result.overall_status == "fail":
                if for_resume:
                    logger.warning(
                        "precondition 6 (source preflight): FAIL downgraded to "
                        "WARN on --resume. Existing cycles ran against these "
                        "sources, so the failure usually indicates the "
                        "preflight checker doesn't recognize the access_method "
                        "rather than a real reachability problem. See "
                        "_pipeline/preflight.json for details."
                    )
                else:
                    unmet.append(
                        "precondition 6: source preflight failed — see "
                        "_pipeline/preflight.json for details"
                    )
            elif preflight_result.overall_status == "warn":
                logger.warning(
                    "precondition 6: source preflight reported warnings "
                    "(overall_status=warn); see _pipeline/preflight.json for "
                    "details"
                )

    return (len(unmet) == 0, unmet)
