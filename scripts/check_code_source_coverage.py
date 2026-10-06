#!/usr/bin/env python3
"""Enforce code-source citation on hard-type notes.

For every note whose `type` frontmatter maps to a `NoteTypeConfig` with
`source_policy: hard` (defaults: service, flow, concept, decision), at least
one `source_urls` entry MUST be classified as `code` (GitHub / file URL).

Exit codes:
  0 — all hard-type notes have at least one code source URL
  1 — one or more hard-type notes lack a code source URL
  2 — usage / filesystem / parse error

See contracts/check_code_source_coverage.cli.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

HARD_DEFAULTS = {"service", "flow", "concept", "decision"}

# Generic fall-backs used when the spec does not list `code_source_url_patterns`.
# Matches any public forge plus local `file://` URLs. Vault owners are expected
# to narrow these to their own orgs via the spec.
DEFAULT_CODE_URL_PATTERNS: list[str] = [
    r"^https?://github\.com/",
    r"^https?://gitlab\.com/",
    r"^https?://bitbucket\.org/",
    r"^file://",
]
INTENT_URL_RE = re.compile(
    r"^(https?://[^/]*atlassian\.net/|https?://[^/]*\.slack\.com/|slack://)",
    re.IGNORECASE,
)


@dataclass
class Violation:
    path: str
    type: str
    sources_present: list[str]
    sources_required: list[str]


def _compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for pat in patterns:
        try:
            compiled.append(re.compile(pat, re.IGNORECASE))
        except re.error:
            # Skip malformed patterns rather than crash the whole run; the
            # spec validator is the right place to reject them upstream.
            continue
    return compiled


def classify_url(url: str, code_patterns: list[re.Pattern[str]] | None = None) -> str:
    patterns = code_patterns or _compile_patterns(DEFAULT_CODE_URL_PATTERNS)
    for pat in patterns:
        if pat.match(url):
            return "code"
    if INTENT_URL_RE.match(url):
        return "intent"
    return "domain"


def _parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    # The closing delimiter is a `---` LINE, as the framework's canonical parser
    # (``vault/frontmatter.py``, not importable from this standalone script)
    # reads it. A `---` inside a value (a slug URL such as `kafka---a-guide`)
    # is not one: splitting on the first substring cut the frontmatter there.
    lines = text.split("\n")
    close = next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None)
    if close is None:
        return {}
    try:
        fm = yaml.safe_load("\n".join(lines[1:close])) or {}
    except yaml.YAMLError:
        return {}
    return fm if isinstance(fm, dict) else {}


def _load_spec(vault_dir: Path) -> dict | None:
    spec_path = vault_dir / "_pipeline" / "spec-parse.json"
    if not spec_path.exists():
        return None
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return spec if isinstance(spec, dict) else None


def _hard_types_from_spec(vault_dir: Path) -> set[str]:
    """Read spec-parse.json (if present) to find hard note types.

    Behaviour:

    - spec absent or unreadable  → fall back to HARD_DEFAULTS (legacy vaults)
    - spec lists note_types      → trust it verbatim; an empty hard set means
                                   the vault is non-code-first by design
                                   (e.g. simple recipe/photography vault) and
                                   no note needs a code URL
    - spec has no note_types key → fall back to HARD_DEFAULTS (same as
                                   "spec absent" — there's no authoritative
                                   statement)
    """
    spec = _load_spec(vault_dir)
    if spec is None:
        return set(HARD_DEFAULTS)
    declared = spec.get("note_types")
    if not declared:
        return set(HARD_DEFAULTS)
    hard: set[str] = set()
    for nt in declared:
        if not isinstance(nt, dict):
            continue
        name = nt.get("name")
        if not name:
            continue
        policy = nt.get("source_policy") or ""
        # When the spec declares note_types explicitly, only 'hard' is 'hard' —
        # the name-based fallback to HARD_DEFAULTS would re-enable the
        # code-source rule for non-code-first vaults that deliberately set
        # concept=soft (v0.2.5/0.2.6 bug).
        if policy == "hard":
            hard.add(name)
    return hard


def _code_patterns_from_spec(vault_dir: Path) -> list[re.Pattern[str]]:
    """Return compiled code-URL patterns from the spec, or library defaults.

    The vault's spec-parse.json may include a `code_source_url_patterns` list
    of regex strings. This keeps org-specific URL shapes out of the script and
    under the user's control. When no patterns are supplied the function
    returns the broad `DEFAULT_CODE_URL_PATTERNS` (any github/gitlab/bitbucket
    + file://) — always something rather than nothing.
    """
    spec = _load_spec(vault_dir)
    patterns: list[str] = []
    if spec is not None:
        raw = spec.get("code_source_url_patterns") or []
        if isinstance(raw, list):
            patterns = [str(p) for p in raw if isinstance(p, str) and p]
    if not patterns:
        patterns = DEFAULT_CODE_URL_PATTERNS
    return _compile_patterns(patterns)


def _source_urls(fm: dict) -> list[str]:
    urls: list[str] = []
    for entry in fm.get("source_urls") or []:
        if isinstance(entry, str):
            urls.append(entry)
        elif isinstance(entry, dict) and entry.get("url"):
            urls.append(str(entry["url"]))
    return urls


def _authoritative_roles_from_spec(vault_dir: Path) -> dict[str, str]:
    """Map ``note_type name → authoritative_role`` for types that declare one.

    spec 053 FR-004: note_types carrying an authoritative role are grounded via
    `citation → source_id → data_source → role` resolution; types without one
    keep the legacy `classify_url` "needs a code source" check (back-compat).
    """
    spec = _load_spec(vault_dir)
    out: dict[str, str] = {}
    if spec is None:
        return out
    for nt in spec.get("note_types") or []:
        if isinstance(nt, dict) and nt.get("name") and nt.get("authoritative_role"):
            out[str(nt["name"])] = str(nt["authoritative_role"])
    return out


def _build_role_index(vault_dir: Path):
    """Reconstruct the `source_id → role` index from spec-parse.json.

    Returns None when research_framework can't be imported (the gate then keeps
    the legacy regex path for every note).
    """
    try:
        from research_framework.pipeline.source_authority import (
            build_source_role_index,
        )
        from research_framework.spec.schema import DataSourceConfig
    except Exception:
        return None
    spec = _load_spec(vault_dir)
    if spec is None:
        return None
    data_sources = [
        DataSourceConfig.from_dict(d)
        for d in (spec.get("data_sources") or [])
        if isinstance(d, dict)
    ]

    class _SpecView:
        pass

    view = _SpecView()
    view.data_sources = data_sources
    return build_source_role_index(view, vault_dir)


def scan(vault_dir: Path) -> tuple[list[Violation], dict[str, int]]:
    hard_types = _hard_types_from_spec(vault_dir)
    code_patterns = _code_patterns_from_spec(vault_dir)
    authoritative_roles = _authoritative_roles_from_spec(vault_dir)
    # Build the role index only when the authority model is in use.
    role_index = _build_role_index(vault_dir) if authoritative_roles else None
    if role_index is None:
        authoritative_roles = {}  # no resolver → fall back to legacy everywhere
    scanned_by_type: dict[str, int] = {t: 0 for t in hard_types}
    violations: list[Violation] = []

    root = vault_dir / "data_vault"
    if not root.exists():
        root = vault_dir
    if not root.exists():
        return violations, scanned_by_type

    # Only needed on the authority path; role_index is None when unavailable.
    if authoritative_roles:
        from research_framework.pipeline.source_authority import resolve_role

    for path in sorted(root.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = _parse_frontmatter(text)
        ntype = str(fm.get("type", ""))
        if ntype not in hard_types:
            continue
        scanned_by_type[ntype] = scanned_by_type.get(ntype, 0) + 1
        urls = _source_urls(fm)

        if ntype in authoritative_roles:
            # spec 053 path: require >=1 citation resolving to the
            # note_type's authoritative role.
            required_role = authoritative_roles[ntype]
            resolved = [resolve_role(u, role_index) for u in urls]
            if required_role not in resolved:
                present = sorted({r for r in resolved if r}) if resolved else []
                violations.append(
                    Violation(
                        path=str(path.relative_to(vault_dir)),
                        type=ntype,
                        sources_present=present,
                        sources_required=[required_role],
                    )
                )
            continue

        # Legacy path: classify_url regex; hard types need a code source.
        classifications = [classify_url(u, code_patterns) for u in urls]
        if "code" not in classifications:
            sources_present = sorted(set(classifications)) if classifications else []
            violations.append(
                Violation(
                    path=str(path.relative_to(vault_dir)),
                    type=ntype,
                    sources_present=sources_present,
                    sources_required=["code"],
                )
            )
    return violations, scanned_by_type


def _print_human(violations: list[Violation], stats: dict[str, int]) -> None:
    for v in violations:
        print(f"{v.path}: MISSING CODE SOURCE")
        print(f"  type: {v.type}")
        if v.sources_present:
            print(f"  source_urls: {v.sources_present} (no code URL)")
        else:
            print("  source_urls: [] (empty)")
        print(
            "  action: add a source_urls entry pointing at the repo "
            "(README, application.yml, or main code file)"
        )
    summary = ", ".join(f"{t}={n}" for t, n in sorted(stats.items()))
    total = sum(stats.values())
    print(f"check_code_source_coverage: scanned {total} hard-type note(s) ({summary})")
    if violations:
        print(f"check_code_source_coverage: {len(violations)} violation(s)")
        print("check_code_source_coverage: FAIL")
    else:
        print("check_code_source_coverage: all have at least one code source URL")
        print("check_code_source_coverage: PASS")


def _emit_json(violations: list[Violation], stats: dict[str, int]) -> None:
    print(
        json.dumps(
            {
                "scanned_by_type": stats,
                "violations": [
                    {
                        "path": v.path,
                        "type": v.type,
                        "sources_present": v.sources_present,
                        "sources_required": v.sources_required,
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
    parser.add_argument("--json", action="store_true", dest="emit_json")
    args = parser.parse_args()

    if not args.vault_dir.exists():
        print(f"ERROR: vault_dir not found: {args.vault_dir}", file=sys.stderr)
        return 2

    violations, stats = scan(args.vault_dir)
    if args.emit_json:
        _emit_json(violations, stats)
    else:
        _print_human(violations, stats)

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
