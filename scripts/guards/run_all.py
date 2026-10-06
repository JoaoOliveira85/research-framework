#!/usr/bin/env python3
"""Guard aggregator (issue #278): run every corpus-level guard as one battery.

Before this script, "run the guards" meant a human reading a CLAUDE.md
checklist and invoking each check by hand; CI ran exactly one of them
(the portability guard, as its own named step) and left the rest to
whatever happened to be inside `pytest -m "not e2e"`'s ~3000 tests — a
guard failure was indistinguishable from an ordinary test failure, and
nothing asserted the battery itself was intact.

Scope, deliberately narrow: this aggregates guards that run against THIS
repo with no external input. The `check_abstraction.py` /
`check_acronym_links.py` / `check_code_source_coverage.py` /
`check_intent_drift.py` / `check_template_compliance.py` /
`check_trunk_inversion.py` / `validate_cycle.py` / `validate_spec.py` /
`validate_vault.py` / `quality_report.py` / `vault_metrics.py` scripts
under `scripts/` all take a vault directory as a required positional
argument (verified against each script's argparse setup) — they guard a
*generated vault*, not this corpus, and there is no vault fixture in this
repo to point them at. Folding them in here would mean either fabricating
a fixture vault (a separate, real feature) or silently skipping them,
which is the exact "reports green having checked nothing" failure mode
issue #283 found in the acceptance-coverage guard. Naming the gap here
beats hiding it inside a passing aggregator.

The foreman Arm A verifier (`scripts/foreman/verify_test_coverage.py`) is
excluded for the same honesty reason: it verifies one spec's `tasks.md`
against `--tasks`, not the corpus, and has no `--all` / `--completed-only`
/ `--soft` corpus-sweep mode (issue #278's own suggested fix) — this PR
does not build that mode. See docs/testing-strategy.md § Guard battery.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Tier-2 lint/guard test modules that scan this repo's own tree (specs,
# source, tests) and were previously reachable only as anonymous members of
# `pytest -m "not e2e"`. Each is independently runnable; listing them here
# (rather than a marker) follows the same precedent build.sh's SMOKE_TESTS
# array already set: "the gate selects by file path, not tier number"
# (docs/testing-strategy.md).
GUARD_TEST_PATHS: tuple[str, ...] = (
    "tests/spec/test_acceptance_coverage_guard.py",
    "tests/spec/test_changelog_regression_links.py",
    "tests/spec/test_test_tree_is_fully_collected.py",
    "tests/docs/test_doc_sync.py",
    "tests/docs/test_spec_index_completeness.py",
    "tests/docs/test_prompt_corpus_is_current.py",
    "tests/docs/test_specify_templates_are_ours.py",
    "tests/docs/test_one_source_per_fact.py",
    "tests/_helpers/test_llm_dispatch_guard.py",
    "tests/_helpers/test_cycle_runner_seam_guard.py",
    "tests/quality/unit/test_marker_isolation.py",
    "tests/quality/test_baseline_update_isolation.py",
    "tests/benchmark/unit/test_marker_isolation.py",
    "tests/benchmark/unit/test_build_exclusion.py",
    "tests/cli/test_parser_flag_consumer_guard.py",
    "tests/cli/test_exit_code_contract.py",
)


@dataclass(frozen=True)
class Guard:
    name: str
    command: tuple[str, ...]


def _pytest_guard() -> Guard:
    return Guard(
        name="guard-test-battery",
        command=(sys.executable, "-m", "pytest", "-q", *GUARD_TEST_PATHS),
    )


def _portability_guard() -> Guard:
    return Guard(
        name="portability",
        command=(sys.executable, "scripts/check_portability.py"),
    )


def _agent_asset_references_guard() -> Guard:
    return Guard(
        name="agent-asset-references",
        command=(sys.executable, "scripts/guards/check_agent_asset_references.py"),
    )


def _parser_flag_guard() -> Guard:
    """Issue #271: every CLI flag must reach a non-CLI consumer.

    Named separately from the pytest battery so its failure line says which
    invariant broke, and so a contributor can run the check on its own while
    wiring a new flag (``--list`` prints the whole inventory).
    """
    return Guard(
        name="parser-flag-consumers",
        command=(sys.executable, "scripts/guards/parser_flag_consumers.py"),
    )


def guard_battery() -> list[Guard]:
    return [
        _portability_guard(),
        _agent_asset_references_guard(),
        _parser_flag_guard(),
        _pytest_guard(),
    ]


def missing_guard_paths() -> list[str]:
    """Existence pre-flight (mirrors build.sh's SMOKE_TESTS check) — a typo'd
    or deleted path must fail loudly, not have pytest silently skip it."""
    return [p for p in GUARD_TEST_PATHS if not (_REPO_ROOT / p).exists()]


def _run_guard(guard: Guard) -> int:
    # Flushed explicitly: this print precedes a subprocess that writes to the
    # same stdout, and an unflushed buffer would print the summary out of
    # order in CI logs (subprocess output is unbuffered by comparison).
    print(f"[guards] running {guard.name}: {' '.join(guard.command)}", flush=True)
    result = subprocess.run(guard.command, cwd=_REPO_ROOT)
    return result.returncode


def _print_summary(results: list[tuple[str, int]]) -> list[str]:
    print("\n[guards] summary:")
    failed = []
    for name, code in results:
        status = "PASS" if code == 0 else f"FAIL (exit {code})"
        print(f"  {name}: {status}")
        if code != 0:
            failed.append(name)
    return failed


def _list_guards(guards: list[Guard]) -> None:
    for guard in guards:
        print(f"{guard.name}: {' '.join(guard.command)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the guard battery (name + command) and exit 0 without running it",
    )
    args = parser.parse_args(argv)

    guards = guard_battery()
    if args.list:
        _list_guards(guards)
        return 0

    missing = missing_guard_paths()
    if missing:
        print("[guards] ERROR: guard test path(s) do not exist:", file=sys.stderr)
        for path in missing:
            print(f"  {path}", file=sys.stderr)
        return 2

    results = [(guard.name, _run_guard(guard)) for guard in guards]
    failed = _print_summary(results)
    if failed:
        print(
            f"\n[guards] {len(failed)} guard(s) failed: {', '.join(failed)}",
            file=sys.stderr,
        )
        return 1
    print("\n[guards] all guards passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
