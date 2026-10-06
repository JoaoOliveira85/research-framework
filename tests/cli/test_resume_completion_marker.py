"""Regression lock: ``_highest_completed_cycle`` quality-report-name matching.

Spec 051 FR5 / REVIVAL-NOTES #4 (shipped 0.6.3). The sentinel-dir and
"only a quality report marks a cycle complete" behaviours are already locked by
``tests/cli/test_research_resume.py``
(``test_sentinel_cycle_dirs_do_not_count`` +
``test_only_a_quality_report_marks_a_cycle_complete``). This file adds the
``_QUALITY_REPORT_RX`` / suffix-check **edge cases** those tests don't probe:
zero-numbered, non-zero-padded width, upper-case ``.JSON`` suffix, and a very
large cycle number.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.cli.research_resume import _highest_completed_cycle


def _cycles_dir(vault: Path) -> Path:
    d = vault / "_pipeline" / "cycles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _report(cycles: Path, name: str) -> None:
    (cycles / name).write_text("{}", encoding="utf-8")


def test_missing_cycles_dir_returns_none(tmp_path: Path):
    assert _highest_completed_cycle(tmp_path) is None


def test_zero_numbered_report_is_not_a_completed_cycle(tmp_path: Path):
    # cycle-000 matches the regex (int 0) but 0 is not a real cycle → None.
    cycles = _cycles_dir(tmp_path)
    _report(cycles, "cycle-000-quality-report.json")
    assert _highest_completed_cycle(tmp_path) is None


def test_non_zero_padded_width_is_parsed_as_int(tmp_path: Path):
    # "01" → int 1; widths are not assumed to be 3-padded.
    cycles = _cycles_dir(tmp_path)
    _report(cycles, "cycle-01-quality-report.json")
    assert _highest_completed_cycle(tmp_path) == 1


def test_uppercase_json_suffix_does_not_match(tmp_path: Path):
    # Suffix check is exactly ".json"; ".JSON" must NOT count as complete.
    cycles = _cycles_dir(tmp_path)
    _report(cycles, "cycle-007-quality-report.JSON")
    assert _highest_completed_cycle(tmp_path) is None


def test_very_large_cycle_number(tmp_path: Path):
    cycles = _cycles_dir(tmp_path)
    _report(cycles, "cycle-999999-quality-report.json")
    assert _highest_completed_cycle(tmp_path) == 999999


def test_mixed_valid_and_edge_names_takes_highest_valid(tmp_path: Path):
    # 003 valid; 000 ignored (zero); .JSON ignored (suffix); a non-report
    # json ignored (no regex match) → highest valid is 3.
    cycles = _cycles_dir(tmp_path)
    _report(cycles, "cycle-003-quality-report.json")
    _report(cycles, "cycle-000-quality-report.json")
    _report(cycles, "cycle-050-quality-report.JSON")
    _report(cycles, "cycle-099-source-signals.json")
    assert _highest_completed_cycle(tmp_path) == 3
