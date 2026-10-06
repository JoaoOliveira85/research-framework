#!/usr/bin/env python3
"""Spec quality gate for ``research.spec.md`` files.

This is the gate the ``vault-spec`` skill runs after drafting a spec. It
loads the simple or detailed spec, expands it to a full ``SpecConfig``, and
reports:

- Hard errors — the spec will not survive ``rv generate``. Exit 1.
- Soft warnings — the spec will run but some defaults were applied that
  the user probably wants to know about (``owner`` defaulted from ``$USER``,
  plain-string sources auto-coerced, budget unset, etc.). Exit 0.

Usage::

    python scripts/validate_spec.py ./research.spec.md
    python scripts/validate_spec.py ./research.spec.md --json

The JSON mode is machine-readable so a skill can iterate programmatically:

    {"ok": false, "errors": [...], "warnings": [...]}

Exit codes:
  0 — spec is valid (warnings may still be present; print to stderr).
  1 — spec has hard validation errors.
  2 — spec file is missing or the script was invoked incorrectly.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Allow running this script both from the source checkout (where `src/` is on
# sys.path through the installed package) and from inside a generated vault
# where a sibling `.venv/` has `research_framework` installed.
_HERE = Path(__file__).resolve().parent
_REPO_SRC = _HERE.parent / "src"
if _REPO_SRC.exists() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

try:
    from research_framework.spec.parser import parse as parse_detailed
    from research_framework.spec.schema import SpecValidationError
    from research_framework.spec.simple import (
        GROWTH_DEFAULTS,
        _read_frontmatter,
        expand,
        is_simple,
        parse_simple,
    )
    from research_framework.spec.validator import validate as validate_detailed
except Exception as e:  # pragma: no cover - import-time failures are fatal
    print(f"[validate_spec] cannot import research_framework: {e}", file=sys.stderr)
    sys.exit(2)


def _load_raw_frontmatter(path: Path) -> dict:
    """Re-read raw frontmatter (pre-coercion) so we can detect auto-fixes."""
    text = path.read_text(encoding="utf-8")
    return _read_frontmatter(text, path)


def _warnings_from_raw(raw: dict, path: Path) -> list[str]:
    """Detect places where the parser had to apply a default on the user's
    behalf. These aren't hard errors but the skill should surface them so the
    user can course-correct before kicking off an expensive research run."""
    warnings: list[str] = []

    if not str(raw.get("owner", "") or "").strip():
        warnings.append(
            "owner was not set — defaulted to $USER "
            f"('{os.environ.get('USER', 'unknown')}'). "
            "Set 'owner:' explicitly if you want attribution in the vault."
        )

    sources = raw.get("sources") or []
    string_sources = [s for s in sources if isinstance(s, str)]
    if string_sources:
        warnings.append(
            f"{len(string_sources)} of {len(sources)} source(s) were plain "
            "strings and got auto-coerced to "
            "{name: <text>}. For richer routing, promote them to mappings "
            "with at least 'name', 'url', and 'role' (e.g. 'role: domain')."
        )

    # A source that has neither a URL in ``name`` nor a ``url`` field is a
    # description-only placeholder — useful while drafting but not usable by
    # the scout agent, which expects something it can fetch. The skill is the
    # place to harden this into concrete references.
    url_re = re.compile(r"^https?://", re.IGNORECASE)

    def _has_concrete_url(s: object) -> bool:
        if isinstance(s, str):
            return bool(url_re.match(s.strip()))
        if isinstance(s, dict):
            if any(url_re.match(str(s.get(k, "")).strip()) for k in ("url", "name")):
                return True
            access = str(s.get("access_method", "") or "")
            if url_re.match(access.strip()):
                return True
        return False

    if sources:
        placeholder_sources = [s for s in sources if not _has_concrete_url(s)]
        if placeholder_sources:
            warnings.append(
                f"{len(placeholder_sources)} of {len(sources)} source(s) are "
                "description-only with no fetchable URL. Scout agents cannot "
                "act on them — replace each with a concrete "
                "'{name, url, role}' entry, or delete them."
            )

    settings = raw.get("settings") if isinstance(raw.get("settings"), dict) else {}
    default_executor = (
        settings.get("default_executor") if isinstance(settings, dict) else None
    )

    # The model/budget/acceptance warnings apply to the simple spec format.
    # Detailed specs (with data_sources/coverage_targets) manage these through
    # their own schema (budget.max_usd, settings.default_executor.model).
    _is_simple_spec = is_simple(raw)

    has_explicit_model = raw.get("model") not in (None, "") or (
        isinstance(default_executor, dict) and default_executor.get("model")
    )
    if not has_explicit_model and _is_simple_spec:
        warnings.append(
            "no 'model' set — the default executor will use 'sonnet' for every "
            "stage. Set 'model: haiku|sonnet|opus' for a global override, or "
            "use 'settings.stages.<stage>.model' for per-stage control "
            "(see settings.yaml in the generated vault for the full list)."
        )

    growth_mode = raw.get("growth_mode", "incremental")
    budget = (settings.get("budget") or {}) if isinstance(settings, dict) else {}
    # Detailed specs use top-level `budget.max_usd`; simple specs use
    # `budget_usd` or `settings.budget.max_usd`.
    has_budget = (
        raw.get("budget_usd") is not None
        or (isinstance(budget, dict) and "max_usd" in budget)
        or (isinstance(raw.get("budget"), dict) and "max_usd" in raw["budget"])
    )
    if not has_budget and _is_simple_spec:
        default_budget = GROWTH_DEFAULTS.get(growth_mode)
        if default_budget is not None:
            warnings.append(
                f"no budget set — growth_mode '{growth_mode}' defaults to "
                f"${default_budget.budget_usd:.2f} (max {default_budget.max_cycles} "
                f"cycles). Set 'budget_usd:' or 'settings.budget.max_usd:' to "
                "override."
            )

    if not raw.get("acceptance") and _is_simple_spec:
        warnings.append(
            "no 'acceptance' criteria set — the orchestrator can't prove the "
            "vault met its goal without at least one concrete done-when line."
        )

    size = str(raw.get("size", "") or "").strip().lower()
    if size and size not in {"small", "medium", "large"}:
        warnings.append(
            f"size '{size}' is non-standard (expected small/medium/large); "
            "it will be ignored by the expander."
        )

    # Detect specs missing structural fields that produce anemic vaults.
    # The detailed format (with data_sources, coverage_targets, and ideally
    # note_types) is the recommended default. Simple specs that omit these
    # get expanded with minimal defaults — 2 note types, trivial coverage
    # targets — which leads to vaults with only 2 folder categories.
    if is_simple(raw):
        missing = []
        if "note_types" not in raw:
            missing.append("note_types")
        if "coverage_targets" not in raw:
            missing.append("coverage_targets")
        if "data_sources" not in raw:
            missing.append("data_sources")

        if missing:
            warnings.append(
                f"spec is missing structural fields: {', '.join(missing)}. "
                "The simple expander will fill in minimal defaults which "
                "produces an anemic vault (2 folder categories, trivial "
                "coverage targets). The detailed spec format is the "
                "recommended default — add explicit note_types, "
                "coverage_targets, and data_sources for proper vault "
                "structure. See examples/detailed-vault-spec.md for a reference example."
            )

    # Phase 2 (topic_propose) prerequisite. Phase 1 is unaffected; this
    # only surfaces as a warning so the user knows the tangent-proposer
    # will follow its `on_missing_out_of_scope` setting (default: skip)
    # instead of producing proposals against an empty fence.
    scope_block = raw.get("scope") if isinstance(raw.get("scope"), dict) else {}
    oos_raw = scope_block.get("out_of_scope") if isinstance(scope_block, dict) else None
    if not isinstance(oos_raw, list) or not [
        t for t in oos_raw if isinstance(t, str) and t.strip()
    ]:
        warnings.append(
            "scope.out_of_scope is missing or empty. Phase 1 is unaffected, "
            "but Phase 2 (stages.topic_propose) will follow "
            "`on_missing_out_of_scope` (default 'skip') instead of proposing "
            "tangents against an empty fence. Add a short list of terms that "
            "are explicitly NOT in scope to get semantic tangent proposals."
        )

    return warnings


def _summary_lines(spec_path: Path) -> list[str]:
    """Produce a short 3-line summary for the skill to echo back to the user."""
    raw = _load_raw_frontmatter(spec_path)
    name = raw.get("name", "?")
    growth = raw.get("growth_mode", "incremental")
    size = raw.get("size", "(size unset)")
    budget = raw.get("budget_usd")
    if budget is None:
        settings = raw.get("settings") or {}
        if isinstance(settings, dict):
            budget = (settings.get("budget") or {}).get("max_usd")
    budget_str = f"${budget}" if budget is not None else "default budget"
    acceptance = raw.get("acceptance") or []
    primary = str(acceptance[0]) if acceptance else "(no acceptance criterion)"
    return [
        f"{name} · {growth} · {size}",
        f"Primary acceptance: {primary}",
        f"Budget: {budget_str}",
    ]


def validate_spec(spec_path: Path) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Non-existent file is a hard error."""
    if not spec_path.exists():
        return ([f"spec file not found: {spec_path}"], [])

    # Read the raw frontmatter once so we can compute warnings even when the
    # spec is structurally valid.
    try:
        raw = _load_raw_frontmatter(spec_path)
    except SpecValidationError as e:
        return (list(e.messages), [])

    warnings = _warnings_from_raw(raw, spec_path)

    spec_config = None
    try:
        if is_simple(raw):
            simple = parse_simple(spec_path)
            # Expansion exercises the validator on the detailed SpecConfig
            # underneath, so structural bugs surface here.
            spec_config = expand(simple, location=spec_path.parent / simple.name)
        else:
            detailed = parse_detailed(spec_path)
            validate_detailed(detailed)
            spec_config = detailed
    except SpecValidationError as e:
        return (list(e.messages), warnings)
    except Exception as e:  # pragma: no cover - unexpected
        return ([f"{spec_path}: unexpected parse error: {e}"], warnings)

    # spec 069 FR1 (C2-b): warn — not fail — on declared sources that neither
    # trigger-match an installed module nor carry kind: strategy_hint. The
    # vault-spec skill surfaces this so the operator hardens the spec before the
    # generate gate (where the same rule is a hard error).
    if spec_config is not None:
        warnings.extend(_source_backing_warnings(spec_config, spec_path.parent))

    return ([], warnings)


def _source_backing_warnings(spec_config: object, vault_dir: Path) -> list[str]:
    try:
        from research_framework.spec.source_backing import (
            build_available_registry,
            credibility_binding,
            source_is_backed,
            unbacked_message,
            unbindable_credibility_message,
        )
    except Exception:  # pragma: no cover - defensive
        return []
    registry = build_available_registry(vault_dir)
    out: list[str] = []
    for ds in getattr(spec_config, "data_sources", []) or []:
        if source_is_backed(ds, registry) == "unbacked":
            out.append(unbacked_message(ds.name))
        # spec 070 FR2: a credibility claim with no key to bind it is inert,
        # and inert configuration is worse than rejected configuration.
        if credibility_binding(ds, registry) == "unbindable":
            out.append(unbindable_credibility_message(ds.name))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Validate a research.spec.md file. Used by the vault-spec skill "
            "as a quality gate before handing the spec to the user."
        )
    )
    ap.add_argument("spec_path", type=Path, help="path to research.spec.md")
    ap.add_argument(
        "--json",
        action="store_true",
        help="emit JSON instead of human-readable output (for agents)",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help=(
            "treat warnings as errors. Use in CI / automated pipelines where "
            "you want to force every auto-default to be explicit."
        ),
    )
    args = ap.parse_args(argv)

    spec_path = args.spec_path
    errors, warnings = validate_spec(spec_path)
    ok = not errors and (not args.strict or not warnings)

    if args.json:
        out = {
            "ok": ok,
            "errors": errors,
            "warnings": warnings,
            "summary": _summary_lines(spec_path) if not errors else [],
        }
        print(json.dumps(out, indent=2))
        return 0 if ok else 1

    if errors:
        print(f"SPEC INVALID — {spec_path}", file=sys.stderr)
        for msg in errors:
            # Strip the path prefix the parser adds; we already printed it.
            msg = re.sub(rf"^{re.escape(str(spec_path))}:\s*", "", msg)
            print(f"  - {msg}", file=sys.stderr)
        print(
            f"\nFix these and re-run: python scripts/validate_spec.py {spec_path}",
            file=sys.stderr,
        )
        return 1

    print(f"SPEC OK — {spec_path}")
    for line in _summary_lines(spec_path):
        print(f"  {line}")

    if warnings:
        print(
            "\nWarnings (non-fatal — review before kicking off a run):", file=sys.stderr
        )
        for msg in warnings:
            print(f"  ! {msg}", file=sys.stderr)
        if args.strict:
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
