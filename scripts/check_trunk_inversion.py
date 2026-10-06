#!/usr/bin/env python3
"""Trunk-inversion gate — spec 053 FR-007 (Gate 4).

Deterministic bad-faith / path-of-least-resistance detector. Reads the
spec-048-v2 per-source ledger (`cycle-NNN-source-ledger.json`) and the spec's
derived trunk, and FAILs when the trunk source was avoided while a
lower-authority branch was used:

    the derived-trunk source MUST resolve to ledger verdict USED — OR an
    *explained* ACCESS_FAIL. FAIL if the trunk is NOT_REACHED / SKIPPED_RELEVANCE
    (or an unexplained ACCESS_FAIL / drop) while ANY branch source is USED.

Exit codes:
  0 — trunk used (or explained), or nothing was used, or no derivable trunk
  1 — trunk inverted: avoided while a branch was used
  2 — usage / filesystem / parse error

⚠️ Depends on spec 048 v2 (the Source-Consideration Ledger). The ledger entry
shape this gate reads — a list of ``{source, role, verdict[, reason]}`` — is the
documented 053 contract (`contracts/gates.contract.md`, `data-model.md`); the
gate's wire-in into the cycle gate-runner is held until 048 v2 ships the real
artifact.

Usage:
    python scripts/check_trunk_inversion.py <vault_dir> [--ledger PATH] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _latest_ledger(cycles_dir: Path) -> Path | None:
    """Return the highest-numbered cycle-NNN-source-ledger.json, or None."""
    candidates: list[tuple[int, Path]] = []
    for p in cycles_dir.glob("cycle-*-source-ledger.json"):
        stem = p.name.removeprefix("cycle-").removesuffix("-source-ledger.json")
        try:
            candidates.append((int(stem), p))
        except ValueError:
            continue
    if not candidates:
        return None
    return max(candidates, key=lambda t: t[0])[1]


def _derive_trunk(spec: dict) -> dict | None:
    """Derive the trunk from spec-parse.json. Reuses the shared dict helper when
    research_framework is importable; falls back to an inline mirror otherwise."""
    data_sources = spec.get("data_sources") if isinstance(spec, dict) else None
    if not isinstance(data_sources, list):
        return None
    try:
        from research_framework.pipeline.source_authority import derive_trunk_dict

        return derive_trunk_dict(data_sources)
    except Exception:
        sources = [d for d in data_sources if isinstance(d, dict)]
        if not sources:
            return None
        min_p = min(d.get("priority", 2) for d in sources)
        at_min = [d for d in sources if d.get("priority", 2) == min_p]
        return at_min[0] if len(at_min) == 1 else None


def _match_entry(trunk: dict, ledger: list[dict]) -> dict | None:
    """Find the ledger entry for the trunk source — by ``source`` name first,
    then by ``role`` (case-insensitive)."""
    name = str(trunk.get("name", "")).strip().lower()
    role = str(trunk.get("role", "")).strip().lower()
    if name:
        for e in ledger:
            if isinstance(e, dict) and str(e.get("source", "")).strip().lower() == name:
                return e
    if role:
        role_matches = [
            e
            for e in ledger
            if isinstance(e, dict) and str(e.get("role", "")).strip().lower() == role
        ]
        if len(role_matches) == 1:
            return role_matches[0]
    return None


def evaluate(spec: dict, ledger: list[dict]) -> tuple[int, str]:
    """Return (exit_code, message)."""
    trunk = _derive_trunk(spec)
    if trunk is None:
        return 0, "no derivable trunk (tie or pure-domain) — inversion N/A; PASS"

    trunk_name = trunk.get("name", "?")
    entry = _match_entry(trunk, ledger)
    verdict = str(entry.get("verdict", "")) if entry else "NOT_REACHED"
    reason = str(entry.get("reason", "")).strip() if entry else ""

    trunk_ok = verdict == "USED" or (verdict == "ACCESS_FAIL" and bool(reason))
    branches_used = [
        e
        for e in ledger
        if isinstance(e, dict)
        and e is not entry
        and str(e.get("verdict", "")) == "USED"
    ]

    if trunk_ok:
        return 0, f"trunk {trunk_name!r} verdict={verdict} — PASS"
    if not branches_used:
        return 0, (
            f"trunk {trunk_name!r} verdict={verdict} but no branch was USED — "
            "no inversion; PASS"
        )
    branch_names = ", ".join(str(e.get("source", "?")) for e in branches_used)
    return 1, (
        f"TRUNK INVERSION: trunk {trunk_name!r} verdict={verdict} while branch "
        f"source(s) USED: {branch_names}. The authoritative trunk must be USED "
        "(or carry an explained ACCESS_FAIL) — this looks like path-of-least-"
        "resistance seeding (spec 053 FR-007)."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="spec 053 trunk-inversion gate")
    parser.add_argument("vault", help="vault directory")
    parser.add_argument("--ledger", help="explicit ledger path (default: latest cycle)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    vault = Path(args.vault)
    spec_path = vault / "_pipeline" / "spec-parse.json"
    if not spec_path.exists():
        print(
            f"check_trunk_inversion: spec-parse.json not found: {spec_path}",
            file=sys.stderr,
        )
        return 2
    spec = _load_json(spec_path)
    if not isinstance(spec, dict):
        print(
            "check_trunk_inversion: spec-parse.json is not a mapping", file=sys.stderr
        )
        return 2

    ledger_path = (
        Path(args.ledger)
        if args.ledger
        else _latest_ledger(vault / "_pipeline" / "cycles")
    )
    if ledger_path is None or not ledger_path.exists():
        print(
            "check_trunk_inversion: no cycle-NNN-source-ledger.json found "
            "(spec 048 v2 artifact); nothing to check",
            file=sys.stderr,
        )
        return 2
    ledger = _load_json(ledger_path)
    if not isinstance(ledger, list):
        print(
            f"check_trunk_inversion: ledger is not a list: {ledger_path}",
            file=sys.stderr,
        )
        return 2

    code, message = evaluate(spec, ledger)
    if args.json:
        print(json.dumps({"ok": code == 0, "exit_code": code, "message": message}))
    else:
        status = "PASS" if code == 0 else "FAIL"
        print(f"check_trunk_inversion: {status}")
        print(f"  {message}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
