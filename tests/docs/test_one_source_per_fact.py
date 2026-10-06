"""One source of truth per fact (#281).

Three fact classes drifted because nothing checked a copy against its
canonical source: test tiers existed in five hand-copied tables that
disagreed with each other and with ADR-0008 (CONTRIBUTING's table even
inverted Tier 5's meaning — real LLM vs hermetic fake-agent cycle); test
counts were quoted as literals in five docs and none of them matched a
live ``pytest --collect-only`` the moment a test was added or removed;
and the release/constitution versions cited in README/CLAUDE.md lagged
``pyproject.toml`` and the constitution's own footer.

The fix designates one canonical source per fact and keeps every other
mention either a pointer (no number quoted, just a link — CONTRIBUTING,
``docs/RELEASE.md``) or a checked copy (``docs/testing-strategy.md``'s
tier table and count, ``ARCHITECTURE.md``'s tier table). This module is
the drift guard: it fails the moment a canonical source and a checked
copy disagree, or a checked copy disagrees with the live truth.

Deliberately NOT covered: the pre-ADR-0008 tier tables in CONTRIBUTING.md
(``choosing a test tier`` §4) and the ``1692``-test comment in its
project-setup block, and README.md's ``v0.7.0`` release-curl example.
Both files carry an explicit "this table/number is stale, defer to X"
correction paragraph instead (see #281's PR body) rather than a
mechanical check, because fixing them in place would have exceeded this
change's one-additive-paragraph budget for those two heavily-shared
files.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR_0008 = REPO_ROOT / "docs" / "adr" / "0008-testing-pyramid-restructure.md"
TESTING_STRATEGY = REPO_ROOT / "docs" / "testing-strategy.md"
ARCHITECTURE = REPO_ROOT / "ARCHITECTURE.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
CONSTITUTION = REPO_ROOT / ".specify" / "memory" / "constitution.md"
README = REPO_ROOT / "README.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_md(name: str) -> str:
    """Drop markdown bold and a trailing parenthetical, then casefold."""
    name = name.replace("**", "").strip()
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    return name.casefold()


# ---------------------------------------------------------------------------
# Tier table: ADR-0008 is canonical; testing-strategy.md and ARCHITECTURE.md
# carry checked copies (elaborated with examples/costs for a reader who
# hasn't opened the ADR).
# ---------------------------------------------------------------------------

_ADR_TIER_CELL_RE = re.compile(r"^Tier\s+(\d+)\s*[—-]\s*(.+)$")


def _adr0008_tiers() -> dict[int, str]:
    """tier number -> casefolded name, from ADR-0008's own restructure table."""
    text = _read(ADR_0008)
    header = "| Old (Feature 018) | New (ADR-0008) | Scope |"
    start = text.index(header)
    # Seven data rows follow the header + its "|---|---|---|" separator line.
    rows = text[start:].splitlines()[2:9]
    tiers: dict[int, str] = {}
    for row in rows:
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        assert len(cells) == 3, f"unexpected ADR-0008 tier row shape: {row!r}"
        m = _ADR_TIER_CELL_RE.match(cells[1].strip())
        assert m, f"ADR-0008 'New (ADR-0008)' cell didn't parse: {cells[1]!r}"
        tiers[int(m.group(1))] = _strip_md(m.group(2))
    assert set(tiers) == set(range(1, 8)), f"expected tiers 1-7, got {sorted(tiers)}"
    return tiers


_TESTING_STRATEGY_TABLE_ROW_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*.+?\s*\|\s*.+?\s*\|\s*.+?\s*\|\s*$",
    re.MULTILINE,
)


def _testing_strategy_tiers() -> dict[int, str]:
    """tier number -> casefolded name, from the seven-tier pyramid table."""
    text = _read(TESTING_STRATEGY)
    header = "| Tier | Name | Scope | Canonical example | Approx cost |"
    start = text.index(header)
    section = text[start:]
    tiers: dict[int, str] = {}
    for m in _TESTING_STRATEGY_TABLE_ROW_RE.finditer(section):
        tiers[int(m.group(1))] = _strip_md(m.group(2))
        if len(tiers) == 7:
            break
    assert set(tiers) == set(range(1, 8)), f"expected tiers 1-7, got {sorted(tiers)}"
    return tiers


_ARCHITECTURE_TABLE_ROW_RE = re.compile(
    r"^\|\s*(\d+)\s*[—-]\s*(.+?)\s*\|\s*.+?\s*\|\s*.+?\s*\|\s*.+?\s*\|\s*$",
    re.MULTILINE,
)


def _architecture_tiers() -> dict[int, str]:
    """tier number -> casefolded name, from ARCHITECTURE.md § 9's table."""
    text = _read(ARCHITECTURE)
    header = "| Tier | Purpose | Example | Speed |"
    start = text.index(header)
    section = text[start:]
    tiers: dict[int, str] = {}
    for m in _ARCHITECTURE_TABLE_ROW_RE.finditer(section):
        tiers[int(m.group(1))] = _strip_md(m.group(2))
        if len(tiers) == 7:
            break
    assert set(tiers) == set(range(1, 8)), f"expected tiers 1-7, got {sorted(tiers)}"
    return tiers


def test_testing_strategy_tiers_match_adr_0008() -> None:
    canonical = _adr0008_tiers()
    copy = _testing_strategy_tiers()
    mismatched = {
        n: (canonical[n], copy[n]) for n in canonical if canonical[n] != copy[n]
    }
    assert not mismatched, (
        "docs/testing-strategy.md's seven-tier table disagrees with the "
        f"canonical docs/adr/0008-testing-pyramid-restructure.md (tier -> "
        f"(canonical, copy)): {mismatched}"
    )


def test_architecture_tiers_match_adr_0008() -> None:
    canonical = _adr0008_tiers()
    copy = _architecture_tiers()
    mismatched = {
        n: (canonical[n], copy[n]) for n in canonical if canonical[n] != copy[n]
    }
    assert not mismatched, (
        "ARCHITECTURE.md § 9's tier table disagrees with the canonical "
        f"docs/adr/0008-testing-pyramid-restructure.md (tier -> (canonical, "
        f"copy)): {mismatched}"
    )


# ---------------------------------------------------------------------------
# Test counts: docs/testing-strategy.md's TL;DR marker comment is the one
# committed number in the repo. It must match a live collection, and its own
# prose restatement must match the comment (so a hand-edit of one without the
# other is caught too).
# ---------------------------------------------------------------------------

_COUNT_MARKER_RE = re.compile(
    r"<!--\s*test-count:\s*not_e2e=(\d+)\s+total=(\d+)\s+e2e_only=(\d+)"
    r"\s+refreshed=(\d{4}-\d{2}-\d{2})\s*-->"
)


def _committed_count_marker() -> tuple[int, int, int]:
    text = _read(TESTING_STRATEGY)
    m = _COUNT_MARKER_RE.search(text)
    assert m, (
        "docs/testing-strategy.md's TL;DR is missing the "
        "'<!-- test-count: ... -->' marker tests/docs/test_one_source_per_fact.py "
        "reads as the canonical count."
    )
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _prose_count_restatement() -> tuple[int, int, int]:
    text = _read(TESTING_STRATEGY)
    idx = text.index("<!-- test-count:")
    # The human-readable paragraph immediately follows the marker.
    paragraph = text[idx : idx + 600]
    bolded = [int(n) for n in re.findall(r"\*\*(\d+)\*\*", paragraph)]
    assert len(bolded) >= 3, (
        "expected at least 3 bolded numbers (not_e2e, total, e2e_only) in the "
        f"paragraph following the test-count marker; found {bolded}"
    )
    return bolded[0], bolded[1], bolded[2]


def _live_collected_counts() -> tuple[int, int]:
    """(not_e2e, total) from a real ``pytest --collect-only`` run."""

    def _collect(marker_expr: str | None) -> tuple[int, int, int]:
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
        ]
        if marker_expr:
            cmd += ["-m", marker_expr]
        result = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, "PYTHONWARNINGS": "ignore"},
        )
        out = result.stdout
        m = re.search(r"(\d+)/(\d+)\s+tests? collected \((\d+) deselected\)", out)
        if m:
            return int(m.group(1)), int(m.group(2)), int(m.group(3))
        m = re.search(r"(\d+)\s+tests? collected", out)
        assert m, (
            f"couldn't parse a collection summary from `{' '.join(cmd)}`; "
            f"tail of output:\n{out[-500:]}"
        )
        n = int(m.group(1))
        return n, n, 0

    not_e2e, total, _ = _collect("not e2e")
    return not_e2e, total


@pytest.mark.slow
def test_testing_strategy_count_marker_matches_live_collection() -> None:
    not_e2e, total, e2e_only = _committed_count_marker()
    assert e2e_only == total - not_e2e, (
        "docs/testing-strategy.md's test-count marker is internally "
        f"inconsistent: not_e2e={not_e2e} total={total} e2e_only={e2e_only} "
        f"but total - not_e2e = {total - not_e2e}"
    )
    live_not_e2e, live_total = _live_collected_counts()
    assert (not_e2e, total) == (live_not_e2e, live_total), (
        "docs/testing-strategy.md's committed test count has drifted from a "
        f"live `pytest --collect-only -q`: committed=(not_e2e={not_e2e}, "
        f"total={total}) live=(not_e2e={live_not_e2e}, total={live_total}). "
        "Update the '<!-- test-count: ... -->' comment AND the bolded numbers "
        "in the paragraph right after it, in docs/testing-strategy.md's TL;DR."
    )


def test_testing_strategy_count_prose_matches_marker() -> None:
    marker = _committed_count_marker()
    prose = _prose_count_restatement()
    assert marker == prose, (
        "docs/testing-strategy.md's test-count marker and its own prose "
        f"restatement disagree: marker={marker} prose={prose} — someone "
        "edited one without the other."
    )


# ---------------------------------------------------------------------------
# Version/release facts: pyproject.toml is canonical for the release version;
# the constitution's own footer is canonical for the constitution version.
# ---------------------------------------------------------------------------


def _pyproject_version() -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"', _read(PYPROJECT), re.MULTILINE)
    assert m, 'pyproject.toml has no top-level `version = "..."`'
    return m.group(1)


def _changelog_latest_version() -> str:
    for line in _read(CHANGELOG).splitlines():
        m = re.match(r"^## \[([^\]]+)\]", line)
        if m and m.group(1) != "Unreleased":
            return m.group(1)
    raise AssertionError("CHANGELOG.md has no released version heading")


def test_pyproject_version_matches_changelog_latest_entry() -> None:
    assert _pyproject_version() == _changelog_latest_version(), (
        f"pyproject.toml version ({_pyproject_version()}) doesn't match "
        f"CHANGELOG.md's most recent released heading "
        f"({_changelog_latest_version()})"
    )


def _constitution_version() -> str:
    m = re.search(r"\*\*Version\*\*:\s*([\d.]+)", _read(CONSTITUTION))
    assert m, ".specify/memory/constitution.md has no '**Version**: X' footer"
    return m.group(1)


def test_readme_constitution_citation_matches_constitution() -> None:
    m = re.search(r"constraints \(v([\d.]+)\)", _read(README))
    assert m, "README.md's constitution reference line changed shape"
    assert m.group(1) == _constitution_version(), (
        f"README.md cites constitution v{m.group(1)}, but "
        f".specify/memory/constitution.md's own footer says v{_constitution_version()}"
    )


def test_claude_md_constitution_citation_matches_constitution() -> None:
    m = re.search(r"principles \(v([\d.]+)\)", _read(CLAUDE_MD))
    assert m, "CLAUDE.md's constitution reference line changed shape"
    assert m.group(1) == _constitution_version(), (
        f"CLAUDE.md cites constitution v{m.group(1)}, but "
        f".specify/memory/constitution.md's own footer says v{_constitution_version()}"
    )
