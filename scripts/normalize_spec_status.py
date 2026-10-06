#!/usr/bin/env python3
"""Normalize every ``specs/NNN-*/spec.md`` Status header (issue #279).

Before this script, ``**Status:**`` (and, on 15 "simple spec" files, a
sibling YAML frontmatter ``status:`` tag) was free-form prose in 25+
distinct forms — SHIPPED/Draft/SUBSUMED/TOMBSTONED/Active/Clarified/... —
validated by nothing, so nothing could tell "shipped" from "draft" without
reading the prose. ``tests/docs/test_spec_status_headers.py`` is the
resulting gate: every header must open with one of five vocabulary tokens
(``planned``, ``in-progress``, ``shipped(<date>, <ref>)``,
``superseded(by <ref>)``, ``archived`` — see CONTRIBUTING.md § 2).

This script performs the one-time migration: it inserts the matching token
as a *prefix* on the existing header line — ``**Status**: <token> — <the
original text, untouched>`` — so nothing a spec asserted is lost, only a
machine-checkable token is added. ``NORMALIZED_STATUS`` is a hand-verified
map (spec dir -> token); building it required reading every header, because
a generic classifier cannot tell "SHIPPED 0.2.31 (2026-05-18) — partial."
from a clean ship without guessing what "partial" leaves undone. Headers
that make such a compound claim are left untouched and listed in
``AMBIGUOUS_STATUS`` instead of guessing (issue #279's own instruction).

Idempotent: a header that already opens with a valid token is left alone,
so re-running after a partial apply (or after future specs adopt the
vocabulary directly) is a no-op.

Usage::

    python scripts/normalize_spec_status.py            # apply
    python scripts/normalize_spec_status.py --dry-run   # report only

Exit codes: 0 always — this is a one-time migration aid, not a CI gate
(``tests/docs/test_spec_status_headers.py`` is the gate).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPECS_DIR = REPO_ROOT / "specs"

# --------------------------------------------------------------------------
# Canonical vocabulary (issue #279 / CONTRIBUTING.md § 2)
# --------------------------------------------------------------------------

_REF = r"(?:PR #\d+|commit [0-9a-f]{7,40}|version \d+\.\d+\.\d+(?:rc\d+)?)"
CANONICAL_STATUS_RE = re.compile(
    rf"^(?:planned\b|in-progress\b|archived\b"
    rf"|shipped\(\d{{4}}-\d{{2}}-\d{{2}}, {_REF}\)"
    rf"|superseded\(by [^)]+\))"
)


def is_canonical(value: str) -> bool:
    """True if *value* opens with one of the five vocabulary tokens."""
    return bool(CANONICAL_STATUS_RE.match(value.strip()))


# --------------------------------------------------------------------------
# Header location — the bold markdown field wins wherever it appears in the
# header zone; a bare YAML frontmatter ``status:`` field is the fallback for
# the one spec with no bold field at all (013-vault-migrator).
# --------------------------------------------------------------------------

_BOLD_LINE = re.compile(r"^(\*\*Status\*\*:\s*|\*\*Status:\*\*\s*)(.*)$")
_FRONTMATTER_LINE = re.compile(r"^(status:\s*)(.*)$")
_HEADER_ZONE = 80
_FRONTMATTER_ZONE = 40


@dataclass(frozen=True)
class StatusHeader:
    """A spec's Status header: which line it's on, and its current value."""

    line_index: int
    prefix: str  # the field label as written, e.g. "**Status**: "
    value: str


def find_status_header(text: str) -> StatusHeader | None:
    lines = text.splitlines()
    bold = _first_match(lines[:_HEADER_ZONE], _BOLD_LINE)
    return bold if bold is not None else _frontmatter_header(lines)


def _first_match(
    lines: list[str], pattern: re.Pattern[str], offset: int = 0
) -> StatusHeader | None:
    for i, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            return StatusHeader(i + offset, match.group(1), match.group(2).strip())
    return None


def _frontmatter_header(lines: list[str]) -> StatusHeader | None:
    if not lines or lines[0].strip() != "---":
        return None
    body = lines[1:_FRONTMATTER_ZONE]
    for i, line in enumerate(body):
        if line.strip() == "---":
            return None
        match = _FRONTMATTER_LINE.match(line)
        if match:
            return StatusHeader(i + 1, match.group(1), match.group(2).strip())
    return None


# --------------------------------------------------------------------------
# Rewriting
# --------------------------------------------------------------------------


def apply_token(text: str, header: StatusHeader, token: str) -> str:
    """Prefix *token* onto the header line; the original value survives
    verbatim after an em dash, so nothing the header asserted is lost."""
    lines = text.splitlines(keepends=True)
    line = lines[header.line_index]
    newline = "\n" if line.endswith("\n") else ""
    separator = " — " if header.value else ""
    lines[header.line_index] = (
        f"{header.prefix}{token}{separator}{header.value}{newline}"
    )
    return "".join(lines)


def insert_missing_header(text: str, token: str) -> str:
    """Insert a fresh ``**Status**:`` line for a spec with no header field
    at all (010/011/012 — retired via a blockquote banner, never given the
    field the template puts on every other spec)."""
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith("# "):
            lines[i + 1 : i + 1] = ["\n", f"**Status**: {token}\n"]
            return "".join(lines)
    raise ValueError("no H1 title line to anchor the new Status header")


# --------------------------------------------------------------------------
# The migration map. Every spec not listed here either already carries a
# canonical header or makes a compound claim (see AMBIGUOUS_STATUS) that a
# script must not resolve by guessing.
# --------------------------------------------------------------------------

NORMALIZED_STATUS: dict[str, str] = {
    "003-topic-harvest-stage": "shipped(2026-05-04, commit a3ef8dd)",
    "004-python-pipeline": "shipped(2026-05-12, commit 604d192)",
    "005-adaptive-sources": "shipped(2026-05-13, commit 9d6f626)",
    "006-vault-audit": "shipped(2026-05-13, commit 3fd97a7)",
    "007-autonomous-vault-settings": "shipped(2026-05-13, commit 102bdb5)",
    "008-vault-script": "shipped(2026-05-13, commit 86339fe)",
    "009-linux-support": "shipped(2026-06-04, PR #113)",
    "010-flow-separation": "superseded(by spec 023)",
    "011-llm-routing": "superseded(by spec 025, spec 028, spec 033)",
    "012-multi-vault": "superseded(by spec 023)",
    "013-vault-migrator": "superseded(by ./vault update)",
    "014-reusable-collectors": "superseded(by ADR-0009, spec 020)",
    "015-pipeline-consolidation": "superseded(by ADR-0009, spec 020)",
    "015a-corpus-folder-name": "planned",
    "015b-vault-inventory": "planned",
    "015c-vault-onboarding": "planned",
    "015d-note-types-first-class": "planned",
    "015e-agent-definitions-as-templates": "planned",
    "015f-processors-in-framework": "shipped(2026-05-21, commit e73b6de)",
    "015g-pipeline-orchestrator-command": "superseded(by ADR-0009, spec 020, spec 023)",
    "015h-retire-vault-local-scripts": "shipped(2026-05-21, commit e73b6de)",
    "018-testing-strategy": "shipped(2026-05-17, version 0.2.23)",
    "020-code-bridge": "shipped(2026-05-27, PR #32)",
    "021-spec-driven-coverage": "planned",
    "024-testing-infrastructure-v2": "shipped(2026-05-21, version 0.3.0)",
    "025-simplify-pass": "shipped(2026-05-22, version 0.3.1)",
    "026-fixture-isolation": "shipped(2026-06-04, PR #107)",
    "027-vault-update-hardening": "shipped(2026-06-03, PR #99)",
    "028-dispatch-telemetry": "shipped(2026-05-27, PR #28)",
    "029-source-manager-correctness": "shipped(2026-06-04, PR #108)",
    "030-quality-harness-v3": "planned",
    "031-git-boundary": "superseded(by spec 050)",
    "032-pipeline-reliability": "shipped(2026-06-03, PR #100)",
    "033-cost-enforcement": "shipped(2026-05-27, PR #31)",
    "034-runtime-consolidation": "superseded(by ADR-0009, spec 020)",
    "035-cross-cycle-digest": "shipped(2026-06-04, PR #117)",
    "036-assistant-framework-integration": "planned",
    "037-consensus-abstraction": "planned",
    "038-source-module-resilience": "shipped(2026-06-03, PR #101)",
    "039-installer-hardening": "shipped(2026-06-04, PR #109)",
    "040-vault-reports-delivery": "shipped(2026-06-04, PR #118)",
    "041-release-infrastructure-v2": "planned",
    "042-autonomous-mode-backend-defaults": "planned",
    "043-obsidian-canvas-autogen": "planned",
    "044-vault-mirror": "planned",
    "045-cost-efficiency-v2": "planned",
    "046-vault-specialities-plugin-model": "superseded(by spec 053)",
    "047-backend-agnostic-agent-layer": "superseded(by spec 064)",
    "048-observability-v1": "shipped(2026-05-29, version 0.5.0)",
    "049-cycle-helpers-split": "shipped(2026-06-03, PR #97)",
    "050-vault-auto-commit": "shipped(2026-06-01, version 0.7.0)",
    "051-post-revival-hardening": "shipped(2026-06-02, PR #91)",
    "052-cursor-cli-executor": "shipped(2026-06-08, PR #131)",
    "054-mcp-managed-access": "planned",
    "055-source-credibility-model": "shipped(2026-06-04, PR #112)",
    "056-executor-benchmark": "shipped(2026-06-08, PR #139)",
    "058-vault-spec-health-warning": "shipped(2026-07-01, PR #183)",
    "059-movable-data-vault": "planned",
    "061-cycle-budget-config": "shipped(2026-06-06, PR #126)",
    "062-vault-output-integrity": "shipped(2026-06-06, PR #126)",
    "063-acceptance-harness": "shipped(2026-06-06, PR #126)",
    "064-opencode-executor": "shipped(2026-06-13, PR #146)",
    "065-local-model-agentic-fit": "planned",
    "066-credibility-model-calibration": "shipped(2026-06-15, PR #175)",
    "067-acronym-wikilink-disambiguation": "shipped(2026-06-15, PR #172)",
    "068-coverage-counting-correctness": "shipped(2026-06-15, PR #171)",
    "070-strategy-hint-credibility-and-silent-resume": "shipped(2026-08-27, PR #194)",
    "071-archived-vaults": "shipped(2026-08-27, PR #195)",
    "072-auto-merge-research-branch": "shipped(2026-08-29, PR #204)",
    "073-query-driven-spec-append": "shipped(2026-08-30, PR #201)",
    "074-cycle-target-topics-discarded": "shipped(2026-08-30, PR #202)",
}

# Left unnormalized on purpose: each header asserts BOTH a completion state
# AND that some part of the same spec's own scope is still open, so no
# single vocabulary token represents it without dropping half the claim.
# See the PR body for the full list and reasoning.
AMBIGUOUS_STATUS: dict[str, str] = {
    "001-speckit-implementation": (
        '"Active" is not in the vocabulary and the header carries no ship '
        "evidence (no date/PR/commit) to resolve it either way."
    ),
    "017-vault-quality-fix": (
        'header calls its own ship "partial" and defers the rest to specs '
        "022/030 — compound claim."
    ),
    "019-pipeline-architecture": (
        'header calls its own ship "partial", continued under specs 024/025 '
        "— compound claim."
    ),
    "022-e2e-quality-harness": (
        "a 2026-09-06 fidelity correction says the shipped gate ran a third "
        'of the specified cycles and lists items that "remain open under '
        'epic #216" — compound claim.'
    ),
    "023-flow-separation": (
        'Phase 1 shipped but "Phase 2 remains deferred to post-Revival" — '
        "compound claim."
    ),
    "053-source-authority-strategy": (
        'header says US3 ledger wire-in + Polish tasks "remain follow-ups" '
        "— compound claim (one of the issue's own examples)."
    ),
    "057-foreman-retro-matcher": (
        'header says the SC-001 retro-rollout tasks "are not done" — '
        "compound claim (one of the issue's own examples)."
    ),
    "060-source-modules-tier2": (
        'Batch-1 shipped but the umbrella is "otherwise IMPLEMENT-READY" — '
        "compound claim (one of the issue's own examples)."
    ),
    "069-source-relevance-tuning": (
        'FR1/FR2/FR3/FR5 shipped but FR4 "split to a follow-up sub-spec" '
        "— compound claim (one of the issue's own examples)."
    ),
}


def _classify(name: str, header: StatusHeader | None) -> tuple[str, str] | None:
    """Return (action, token) for a spec, or None if nothing to do."""
    if name in NORMALIZED_STATUS:
        token = NORMALIZED_STATUS[name]
        action = "insert" if header is None else "prefix"
        return action, token
    if name in AMBIGUOUS_STATUS or header is None:
        return None
    if is_canonical(header.value):
        return None
    return "unhandled", header.value


def normalize_spec(path: Path) -> str | None:
    """Return a report line for *path*, or None if it needed no change."""
    text = path.read_text(encoding="utf-8")
    name = path.parent.name
    header = find_status_header(text)
    verdict = _classify(name, header)
    if verdict is None:
        return None
    action, token = verdict
    if action == "unhandled":
        return f"UNHANDLED  {name}: {token!r} is not canonical and not mapped"
    new_text = (
        insert_missing_header(text, token)
        if action == "insert"
        else apply_token(text, header, token)  # type: ignore[arg-type]
    )
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
    return f"{action.upper():8} {name}: {token}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="report only; do not write files"
    )
    args = parser.parse_args(argv)

    spec_paths = sorted(SPECS_DIR.glob("*/spec.md"))
    reports = []
    for spec_path in spec_paths:
        if args.dry_run:
            text = spec_path.read_text(encoding="utf-8")
            reports.append(_dry_run_report(spec_path, text))
        else:
            reports.append(normalize_spec(spec_path))
    for line in filter(None, reports):
        print(line)
    unhandled = sum(1 for r in reports if r and "UNHANDLED" in r)
    touched = sum(1 for r in reports if r) - unhandled
    print(
        f"\n{touched} normalized · {len(AMBIGUOUS_STATUS)} left ambiguous · "
        f"{unhandled} unhandled (should be 0) · {len(spec_paths)} specs total"
    )
    return 1 if unhandled else 0


def _dry_run_report(path: Path, text: str) -> str | None:
    name = path.parent.name
    header = find_status_header(text)
    verdict = _classify(name, header)
    if verdict is None:
        return None
    action, token = verdict
    return f"[dry-run] {action.upper():8} {name}: {token}"


if __name__ == "__main__":
    sys.exit(main())
