"""Guard: every parser flag must reach a non-CLI consumer (issue #271).

Six accepted-but-inert options have been found in this repo so far — ``url:``,
``--target-topics`` (spec 074), ``source_policy: hard``, ``pipeline
--budget-cap`` (#232), ``vault.corpus_dir`` (#251), and ``verify``'s
``auto_fix`` / ``fail_threshold``. The 1.1.0 CHANGELOG names the pattern four
times. This is the guard that turns the documented pattern into an enforced
invariant, and these are its tests.

Note the shape of the allowlist tests: an allowlist that may rot is a guard
that can be switched off by accident, so a stale entry is a failure in its own
right. And per #217/#278, the scan must fail CLOSED — assert it found flags
before asserting they have consumers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:  # ``scripts/`` is not an installed package
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.guards import parser_flag_consumers as guard  # noqa: E402

# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------


def test_every_parser_flag_reaches_a_non_cli_consumer() -> None:
    report = guard.audit()
    assert not report.unconsumed, guard.format_failure(report)


# ---------------------------------------------------------------------------
# Fail closed (#217, #278): a guard whose scan goes empty passes vacuously
# ---------------------------------------------------------------------------


def test_flag_discovery_is_not_vacuous() -> None:
    report = guard.audit()
    assert len(report.flags) >= 50, (
        f"only {len(report.flags)} parser flag(s) discovered — the parser walk "
        "has broken and this guard is passing having checked nothing"
    )


def test_consumer_scan_is_not_vacuous() -> None:
    report = guard.audit()
    assert len(report.consumer_files) >= 100, (
        f"only {len(report.consumer_files)} consumer module(s) scanned — the "
        "scan root has moved and every flag would look unconsumed (or, with an "
        "empty flag set, consumed)"
    )


def test_subcommands_are_discovered_not_just_top_level_flags() -> None:
    subcommands = {flag.subcommand for flag in guard.audit().flags}
    assert len(subcommands) >= 10, (
        "the walk is not descending into subparsers; a top-level-only scan "
        "would exempt every verb's flags by construction"
    )


# ---------------------------------------------------------------------------
# Allowlist hygiene — the entries must stay true, not just present
# ---------------------------------------------------------------------------


def test_every_allowlist_entry_carries_a_reason() -> None:
    missing = [key for key, reason in guard.ALLOWLIST.items() if not reason.strip()]
    assert not missing, f"allowlist entries with no reason: {missing}"


def test_no_allowlist_entry_is_stale() -> None:
    """An entry for a deleted flag, or for one that has since acquired a
    consumer, must be removed — otherwise the allowlist silently grows into a
    list of flags nobody checks any more."""
    report = guard.audit()
    assert not report.stale_allowlist, (
        "these allowlist entries no longer describe reality (the flag is gone, "
        f"or it now reaches a consumer): {sorted(report.stale_allowlist)}"
    )


def test_allowlisted_flags_are_still_read_somewhere_in_cli() -> None:
    """The allowlist exempts a flag from *crossing* the cli/ boundary. It does
    not exempt it from being read at all — a flag nobody reads is the #232 bug
    itself, and no reason string makes it acceptable."""
    report = guard.audit()
    assert not report.unread, (
        "parsed but never read anywhere under src/research_framework/cli/: "
        f"{sorted(report.unread)}"
    )


# ---------------------------------------------------------------------------
# The scanner itself, on synthetic input
# ---------------------------------------------------------------------------


def test_scanner_finds_a_dest_used_by_a_consumer(tmp_path: Path) -> None:
    consumer = tmp_path / "engine.py"
    consumer.write_text("def go(max_cycles: int) -> None: ...\n", encoding="utf-8")
    assert guard.dest_is_referenced("max_cycles", [consumer])


def test_scanner_ignores_a_substring_match(tmp_path: Path) -> None:
    """``--cycle`` must not be satisfied by an unrelated ``max_cycles``."""
    consumer = tmp_path / "engine.py"
    consumer.write_text("def go(max_cycles: int) -> None: ...\n", encoding="utf-8")
    assert not guard.dest_is_referenced("cycle", [consumer])


def test_scanner_ignores_a_match_inside_a_comment(tmp_path: Path) -> None:
    """A flag mentioned in prose is not a flag that is consumed — that is
    exactly how ``--budget-cap`` read as wired for a whole release (#232)."""
    consumer = tmp_path / "engine.py"
    consumer.write_text("# budget_cap is honoured elsewhere\n", encoding="utf-8")
    assert not guard.dest_is_referenced("budget_cap", [consumer])


def test_scanner_ignores_a_match_inside_a_docstring(tmp_path: Path) -> None:
    consumer = tmp_path / "engine.py"
    consumer.write_text('"""Honours budget_cap."""\n', encoding="utf-8")
    assert not guard.dest_is_referenced("budget_cap", [consumer])


def test_scanner_ignores_a_match_inside_a_string_literal(tmp_path: Path) -> None:
    consumer = tmp_path / "engine.py"
    consumer.write_text('MSG = "pass budget_cap"\n', encoding="utf-8")
    assert not guard.dest_is_referenced("budget_cap", [consumer])


def test_scanner_counts_a_keyword_argument_name(tmp_path: Path) -> None:
    consumer = tmp_path / "engine.py"
    consumer.write_text("run(budget_cap=1.0)\n", encoding="utf-8")
    assert guard.dest_is_referenced("budget_cap", [consumer])


def test_scanner_counts_an_attribute_name(tmp_path: Path) -> None:
    consumer = tmp_path / "engine.py"
    consumer.write_text("value = settings.budget_cap\n", encoding="utf-8")
    assert guard.dest_is_referenced("budget_cap", [consumer])


def test_scanner_skips_a_file_it_cannot_parse(tmp_path: Path) -> None:
    """A syntax error in one module must not silently un-guard every flag."""
    broken = tmp_path / "broken.py"
    broken.write_text("def (\n", encoding="utf-8")
    with pytest.raises(SyntaxError):
        guard.dest_is_referenced("budget_cap", [broken])


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_the_guard_is_in_the_aggregator_battery() -> None:
    from scripts.guards import run_all

    names = {g.name for g in run_all.guard_battery()}
    assert "parser-flag-consumers" in names, (
        "a guard nobody runs is documentation; register it in "
        "scripts/guards/run_all.py::guard_battery"
    )


def test_the_guard_cli_exits_zero_on_a_clean_tree() -> None:
    assert guard.main([]) == 0
