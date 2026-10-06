#!/usr/bin/env python3
"""Detect code/intent drift in service and flow notes.

Parses `## Current Behaviour` and `## Stated Intent` sections, extracts
structured facts (exact numeric claims, named owners/teams, enum values,
explicit booleans), and flags notes where the two sections disagree WITHOUT
the `intent_implementation_drift: true` frontmatter flag set.

Exit codes:
  0 — all targeted notes either agree OR correctly flag + document drift
  1 — one or more notes have unflagged drift
  2 — usage / filesystem / parse error

See contracts/check_intent_drift.cli.md for detection heuristics.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)

# Fact extraction patterns (conservative v1). Capture label + value.
NUMERIC_RE = re.compile(
    r"\b([a-zA-Z][\w\-]{2,30})\s*[:=]\s*(\d+(?:\.\d+)?)\s*(ms|s|%|seconds?|minutes?|hours?)?\b",
    re.IGNORECASE,
)
OWNER_RE = re.compile(
    r"\b(owner|team|maintainer)\s*[:=]\s*([A-Z][A-Za-z0-9 &/\-]+?)(?=[\.,;\n]|$)",
    re.IGNORECASE,
)
ENUM_RE = re.compile(
    r"\b(policy|strategy|mode|delivery)\s*[:=]\s*([a-z\-]+(?:-[a-z]+)+)\b",
    re.IGNORECASE,
)
BOOL_RE = re.compile(
    r"\b(\w*(?:enabled|required|allowed))\s*[:=]\s*(true|false|yes|no)\b",
    re.IGNORECASE,
)


@dataclass
class Fact:
    kind: str  # numeric | owner | enum | bool
    label: str
    value: str


@dataclass
class Violation:
    path: str
    fact: str
    code_value: str
    intent_value: str


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        fm = {}
    return fm if isinstance(fm, dict) else {}, parts[2]


def _extract_section(body: str, heading: str) -> str:
    """Return the body of a `## {heading}` section up to the next `## ` heading."""
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$(.+?)(?=^##\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(body)
    return m.group(1).strip() if m else ""


def _extract_facts(section_text: str) -> list[Fact]:
    facts: list[Fact] = []
    for m in NUMERIC_RE.finditer(section_text):
        label, value, unit = m.group(1).lower(), m.group(2), (m.group(3) or "").lower()
        # Skip markdown list markers or trivial "1." accidents
        if label in ("line", "item", "the", "a", "an"):
            continue
        normalized_value = f"{value}{unit}" if unit else value
        facts.append(Fact("numeric", label, normalized_value))
    for m in OWNER_RE.finditer(section_text):
        facts.append(Fact("owner", m.group(1).lower(), m.group(2).strip()))
    for m in ENUM_RE.finditer(section_text):
        facts.append(Fact("enum", m.group(1).lower(), m.group(2).lower()))
    for m in BOOL_RE.finditer(section_text):
        val = m.group(2).lower()
        normalized = "true" if val in ("true", "yes") else "false"
        facts.append(Fact("bool", m.group(1).lower(), normalized))
    return facts


def _dedupe_facts(facts: Iterable[Fact]) -> dict[tuple[str, str], str]:
    """Map (kind, label) → value. Later entries win (last-write wins)."""
    out: dict[tuple[str, str], str] = {}
    for f in facts:
        out[(f.kind, f.label)] = f.value
    return out


def detect_drift(code_section: str, intent_section: str) -> list[tuple[str, str, str]]:
    """Return list of (fact_label, code_value, intent_value) disagreements."""
    code_facts = _dedupe_facts(_extract_facts(code_section))
    intent_facts = _dedupe_facts(_extract_facts(intent_section))
    disagreements: list[tuple[str, str, str]] = []
    for key, cv in code_facts.items():
        if key in intent_facts:
            iv = intent_facts[key]
            if cv != iv:
                disagreements.append((f"{key[0]}:{key[1]}", cv, iv))
    return disagreements


def scan_vault(
    vault_dir: Path, note_types: Iterable[str] = ("service", "flow")
) -> tuple[list[Violation], dict[str, int]]:
    """Walk vault_dir for notes of the given types; return (violations, stats)."""
    stats = {
        "scanned": 0,
        "flagged_correctly": 0,
        "skipped_pending": 0,
        "skipped_none_applicable": 0,
    }
    violations: list[Violation] = []
    targets = set(note_types)

    # Look under data_vault/ if present; else scan tree directly
    root = vault_dir / "data_vault"
    if not root.exists():
        root = vault_dir
    if not root.exists():
        return violations, stats

    for path in sorted(root.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, body = _parse_frontmatter(text)
        ntype = str(fm.get("type", ""))
        if ntype not in targets:
            continue
        stats["scanned"] += 1

        intent_status = str(fm.get("intent_status", "captured"))
        if intent_status == "pending":
            stats["skipped_pending"] += 1
            continue
        if intent_status == "none-applicable":
            stats["skipped_none_applicable"] += 1
            continue

        code_section = _extract_section(body, "Current Behaviour")
        intent_section = _extract_section(body, "Stated Intent")
        if not code_section or not intent_section:
            continue

        disagreements = detect_drift(code_section, intent_section)
        if not disagreements:
            continue

        flag = bool(fm.get("intent_implementation_drift", False))
        drift_notes = fm.get("drift_notes") or []
        if flag and drift_notes:
            stats["flagged_correctly"] += 1
            continue

        for fact, cv, iv in disagreements:
            violations.append(
                Violation(
                    path=str(path.relative_to(vault_dir)),
                    fact=fact,
                    code_value=cv,
                    intent_value=iv,
                )
            )

    return violations, stats


def _print_human(violations: list[Violation], stats: dict[str, int]) -> None:
    for v in violations:
        print(f"{v.path}: DRIFT UNFLAGGED")
        print(f"  fact: {v.fact}")
        print(f'  code_value: "{v.code_value}"   (from ## Current Behaviour)')
        print(f'  intent_value: "{v.intent_value}" (from ## Stated Intent)')
        print(
            "  action: set `intent_implementation_drift: true` and add an entry to `drift_notes`"
        )
    status = "FAIL" if violations else "PASS"
    n = stats.get("scanned", 0)
    print(
        f"check_intent_drift: scanned {n} note(s); "
        f"flagged_correctly={stats.get('flagged_correctly', 0)}; "
        f"skipped_pending={stats.get('skipped_pending', 0)}; "
        f"skipped_none_applicable={stats.get('skipped_none_applicable', 0)}"
    )
    if violations:
        print(f"check_intent_drift: {len(violations)} violation(s)")
    print(f"check_intent_drift: {status}")


def _emit_json(violations: list[Violation], stats: dict[str, int]) -> None:
    print(
        json.dumps(
            {
                "scanned": stats["scanned"],
                "flagged_correctly": stats["flagged_correctly"],
                "violations": [
                    {
                        "path": v.path,
                        "fact": v.fact,
                        "code_value": v.code_value,
                        "intent_value": v.intent_value,
                    }
                    for v in violations
                ],
            },
            indent=2,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("vault_dir", type=Path)
    parser.add_argument(
        "--type",
        default="service,flow",
        help="Comma-separated note types to check (default: service,flow)",
    )
    parser.add_argument("--json", action="store_true", dest="emit_json")
    args = parser.parse_args()

    if not args.vault_dir.exists():
        print(f"ERROR: vault_dir not found: {args.vault_dir}", file=sys.stderr)
        return 2

    types = tuple(t.strip() for t in args.type.split(",") if t.strip())
    violations, stats = scan_vault(args.vault_dir, types)

    if args.emit_json:
        _emit_json(violations, stats)
    else:
        _print_human(violations, stats)

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
