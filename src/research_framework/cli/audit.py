from __future__ import annotations

import argparse
import subprocess
import sys


def _cmd_coverage(args: argparse.Namespace) -> int:
    try:
        from ..pipeline.coverage import (
            all_targets_met,
            load_targets,
            unmet_expected_filenames,
        )
    except ImportError:
        print("coverage module not available in this build", file=sys.stderr)
        return 2
    if not args.vault.exists():
        print(f"ERROR: vault directory not found: {args.vault}", file=sys.stderr)
        return 2
    try:
        targets = load_targets(args.vault)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(f"Coverage Targets — {args.vault}")
    print("─" * 60)
    print(f"{'Category':<25} {'Target':>6} {'Met':>5} Status")
    for cat in targets.categories:
        status = "✓ MET" if cat.is_met else f"✗ UNMET (gap: {cat.gap})"
        print(f"{cat.name:<25} {cat.target_count:>6} {cat.met_count:>5} {status}")

    # Feature 002: print expected filenames for unmet categories when
    # repo-scan.json has populated them. Enables focused resume runs.
    missing = unmet_expected_filenames(args.vault)
    if missing:
        print("\nUnmet expected filenames (from repo-scan):")
        for cat_name, filenames in missing.items():
            print(f"\n  {cat_name} ({len(filenames)} missing):")
            for fname in filenames[:20]:
                print(f"    - {fname}")
            if len(filenames) > 20:
                print(f"    … and {len(filenames) - 20} more")

    met = all_targets_met(args.vault)
    print(f"\nPhase 3 gate: {'OPEN' if met else 'CLOSED'}")
    if met:
        return 0
    # Spec 077 FR-017: rc=1 says why on stderr. The table above is the
    # report; stdout is the stream an unattended run redirects away.
    print("coverage targets unmet (Phase 3 gate CLOSED):", file=sys.stderr)
    for cat in targets.categories:
        if not cat.is_met:
            print(
                f"  - {cat.name}: {cat.met_count}/{cat.target_count}", file=sys.stderr
            )
    return 1


def _cmd_validate(args: argparse.Namespace) -> int:
    from .._assets import asset_path

    if not args.vault.is_dir():
        print(f"ERROR: vault directory not found: {args.vault}", file=sys.stderr)
        return 2
    try:
        scripts_dir = asset_path("scripts")
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    checks = [
        ("vault", scripts_dir / "validate_vault.py"),
        ("template", scripts_dir / "check_template_compliance.py"),
        ("acronym", scripts_dir / "check_acronym_links.py"),
        # Feature 002 — code-first validators (skipped silently if absent,
        # for back-compat with v0.1 vaults).
        ("intent-drift", scripts_dir / "check_intent_drift.py"),
        ("code-source-coverage", scripts_dir / "check_code_source_coverage.py"),
    ]
    worst = 0
    ran = 0
    failed: list[str] = []
    for name, path in checks:
        if not path.exists():
            continue
        print(f"[{name}] running {path.name}")
        rc = subprocess.run([sys.executable, str(path), str(args.vault)]).returncode
        ran += 1
        if rc != 0:
            # A negative rc is a signal-killed validator: a failure, not a pass.
            worst = max(worst, rc if rc > 0 else 2)
            failed.append(f"{name} (exit {rc})")
    if ran == 0:
        print(f"ERROR: no validator scripts found under {scripts_dir}", file=sys.stderr)
        return 2
    if failed:
        print(f"validate: failing checks: {', '.join(failed)}", file=sys.stderr)
    return worst


def _cmd_check_skills(args: argparse.Namespace) -> int:
    """``research-framework check-skills`` — validate (and auto-restore) SKILL.md files.

    Convenience wrapper around :func:`pipeline.skill_check.validate_and_repair_skills`
    so users can run the preflight manually after a suspected external-tool
    rewrite, without having to start a cycle. Mirrors the cycle-runner's
    preflight: exit 0 when every skill parses (possibly after auto-restore),
    exit 2 when any file is unrecoverable.
    """
    from ..pipeline.skill_check import validate_and_repair_skills

    result = validate_and_repair_skills(args.vault)
    if result.repaired:
        print(
            f"auto-restored {len(result.repaired)} SKILL.md file(s) "
            f"from the bundled copies:"
        )
        for issue in result.repaired:
            print(f"  - {issue.path}: was {issue.error!r}")
    if result.unrecoverable:
        print("UNRECOVERABLE SKILL.md files:", file=sys.stderr)
        for issue in result.unrecoverable:
            print(f"  - {issue.path}: {issue.error}", file=sys.stderr)
        return 2
    if not result.repaired:
        print(f"OK: {result.scanned} skill file(s) parsed cleanly")
    return 0
