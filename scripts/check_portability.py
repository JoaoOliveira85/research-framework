#!/usr/bin/env python3
"""Cross-platform portability guard (spec 009).

Deterministic, **stdlib-only** scan that fails when *shipped* shell scripts or
*executable* code reintroduce a macOS-ism that would break Linux (or a future
non-Homebrew macOS). The 2026-06-03 audit found the shipped tree already
portable; this guard converts that one-time audit into a permanent invariant
so a future macOS-ism can never silently break the primary target.

Rules (mirrored 1:1 in ``docs/PORTABILITY.md`` — see :data:`RULE_KEYWORDS`):

================  ===========================================  ====================
Rule              Forbidden                                    Scope
================  ===========================================  ====================
BSD in-place sed  ``sed -i ''`` / ``sed -i ""``                shipped ``.sh``
bash-4 construct  ``${v^^}`` ``${v,,}`` ``declare -A``          shipped ``.sh``
                  ``mapfile`` ``readarray`` ``&>>``
hardcoded path    ``~/Library`` ``/opt/homebrew``              code (``.py``/``.sh``);
                  ``/usr/local/bin`` ``/Applications/``        ``*.md`` exempt
================  ===========================================  ====================

Scopes:
  * shipped ``.sh``  = ``build.sh`` + ``install.sh`` + ``generate_vault.sh``
                       + ``templates/vault-script.sh.j2`` + ``dist-templates/*.sh``
                       + ``scripts/**/*.sh``
  * code (path rule) = ``src/research_framework/**/*.py`` + ``scripts/**/*.{py,sh}``
                       + ``dist-templates/*.sh`` + ``build.sh`` + ``install.sh``
                       + ``generate_vault.sh`` + ``templates/vault-script.sh.j2``

Excluded:
  * ``.specify/**`` — vendored spec-kit tooling (2 known ``${word^^}`` hits, D3).
  * this guard's own file — it necessarily contains the forbidden literals as
    rule definitions; scanning it would self-trip the clean-tree lock.

**Exit codes**: ``0`` clean · ``1`` on any finding · ``2`` structural error.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Human-facing rule tokens. docs/PORTABILITY.md MUST mention each of these
# verbatim; tests/scripts/test_portability_guard.py + the doc-drift test pin
# the guard↔doc agreement (SC-005).
RULE_KEYWORDS: tuple[str, ...] = (
    "sed -i ''",
    "${v^^}",
    "${v,,}",
    "declare -A",
    "mapfile",
    "readarray",
    "&>>",
    "~/Library",
    "/opt/homebrew",
    "/usr/local/bin",
    "/Applications/",
)


@dataclass(frozen=True)
class Finding:
    """One portability violation. ``path`` is repo-relative, forward-slashed."""

    path: str
    line: int
    rule: str
    snippet: str
    hint: str


# --- Rule 1: BSD in-place sed (empty-extension form only) ------------------
# `sed -i ''` / `sed -i ""` is BSD-only; GNU sed wants `sed -i` (no arg) and
# the portable cross-platform form is `sed -i.bak … && rm …`. Match `-i`
# followed by whitespace then an empty quote pair on a line containing `sed`.
_BSD_SED_RE = re.compile(r"sed\b[^\n]*?-i\s+(?:''|\"\")")
_BSD_SED_HINT = "use a python rewrite or `sed -i.bak … && rm …` (portable on BSD + GNU)"

# --- Rule 2: bash-4 constructs (shipped .sh; bash-3.2 is the macOS floor) ---
# Each entry: (human keyword for the report, compiled detector).
_BASH4_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # `^`/`^^` (upper) and `,`/`,,` (lower) parameter-case expansion.
    ("${v^^}", re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\^")),
    ("${v,,}", re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*,")),
    ("declare -A", re.compile(r"\bdeclare\s+-A\b")),
    ("mapfile", re.compile(r"\bmapfile\b")),
    ("readarray", re.compile(r"\breadarray\b")),
    ("&>>", re.compile(r"&>>")),
)
_BASH4_HINT = (
    "keep shipped scripts bash-3.2 compatible: `tr` for case, indexed arrays, "
    "`>> f 2>&1` for append-both"
)

# --- Rule 3: hardcoded macOS paths (code only; *.md exempt) ----------------
_MACOS_PATH_TOKENS: tuple[str, ...] = (
    "~/Library",
    "/opt/homebrew",
    "/usr/local/bin",
    "/Applications/",
)
_MACOS_PATH_HINT = (
    "don't hardcode a macOS path: use $(brew --prefix), `command -v`, $HOME, or "
    "an env var (docs may *describe* platform steps; code must not hardcode them)"
)

_SPECIFY_SEGMENT = ".specify"
_SELF_REL = "scripts/check_portability.py"


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_excluded(rel: str) -> bool:
    if rel == _SELF_REL:
        return True
    return _SPECIFY_SEGMENT in rel.split("/")


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _root_shell_entry_points(root: Path) -> list[Path]:
    """`build.sh` + the two other root-level shell entry points end users
    actually run (issue #288): `install.sh` and `generate_vault.sh`. Neither
    was ever in scope — a coverage gap, not a known live violation."""
    files: list[Path] = []
    for name in ("build.sh", "install.sh", "generate_vault.sh"):
        candidate = root / name
        if candidate.is_file():
            files.append(candidate)
    return files


def _vault_shim_template(root: Path) -> list[Path]:
    """`templates/vault-script.sh.j2` (issue #288) — rendered into EVERY
    generated vault as its `./vault` shim (`scaffold.py`'s scaffold step).
    Jinja `{{ }}`/`{% %}` markup doesn't collide with any of this guard's
    regexes (plain substring/regex line scans), so the template scans
    exactly like a shipped `.sh` file — the one that ships to the most
    machines this project doesn't control."""
    files: list[Path] = []
    candidate = root / "templates" / "vault-script.sh.j2"
    if candidate.is_file():
        files.append(candidate)
    return files


def _shipped_sh_files(root: Path) -> list[Path]:
    """`build.sh` + `install.sh` + `generate_vault.sh` +
    `templates/vault-script.sh.j2` + `dist-templates/*.sh` +
    `scripts/**/*.sh` (the scripts that reach end users or run in the
    project's own automation)."""
    files: list[Path] = [*_root_shell_entry_points(root), *_vault_shim_template(root)]
    dist = root / "dist-templates"
    if dist.is_dir():
        files.extend(sorted(dist.glob("*.sh")))
    scripts = root / "scripts"
    if scripts.is_dir():
        files.extend(sorted(scripts.rglob("*.sh")))
    return [f for f in files if not _is_excluded(_rel(f, root))]


def _macos_scan_files(root: Path) -> list[Path]:
    """Code surfaces the macOS-path rule scans (D2): src python, scripts
    python+shell, dist-template shell, build.sh + install.sh +
    generate_vault.sh + the vault shim template. `*.md` is never collected."""
    files: list[Path] = [*_root_shell_entry_points(root), *_vault_shim_template(root)]
    src = root / "src" / "research_framework"
    if src.is_dir():
        files.extend(sorted(src.rglob("*.py")))
    scripts = root / "scripts"
    if scripts.is_dir():
        files.extend(sorted(scripts.rglob("*.py")))
        files.extend(sorted(scripts.rglob("*.sh")))
    dist = root / "dist-templates"
    if dist.is_dir():
        files.extend(sorted(dist.glob("*.sh")))
    return [f for f in files if not _is_excluded(_rel(f, root))]


def scan(root: Path | str) -> list[Finding]:
    """Scan ``root`` and return all portability findings, sorted by path/line."""
    root = Path(root)
    findings: list[Finding] = []

    for path in _shipped_sh_files(root):
        rel = _rel(path, root)
        for lineno, line in enumerate(_read_lines(path), start=1):
            if _BSD_SED_RE.search(line):
                findings.append(
                    Finding(
                        rel, lineno, "bsd-sed-in-place", line.strip(), _BSD_SED_HINT
                    )
                )
            for keyword, detector in _BASH4_RULES:
                if detector.search(line):
                    findings.append(
                        Finding(
                            rel,
                            lineno,
                            f"bash4-construct ({keyword})",
                            line.strip(),
                            _BASH4_HINT,
                        )
                    )
                    break  # one bash-4 finding per line is enough to act on

    for path in _macos_scan_files(root):
        rel = _rel(path, root)
        for lineno, line in enumerate(_read_lines(path), start=1):
            for token in _MACOS_PATH_TOKENS:
                if token in line:
                    findings.append(
                        Finding(
                            rel,
                            lineno,
                            f"macos-path ({token})",
                            line.strip(),
                            _MACOS_PATH_HINT,
                        )
                    )
                    break  # first hardcoded path per line is enough

    findings.sort(key=lambda f: (f.path, f.line, f.rule))
    return findings


def format_report(findings: list[Finding]) -> str:
    if not findings:
        return ""
    out = ["Portability guard FAILED — macOS-ism(s) in shipped code/scripts:", ""]
    for f in findings:
        out.append(f"  {f.path}:{f.line}: [{f.rule}] {f.snippet}")
        out.append(f"      → {f.hint}")
    out.append("")
    out.append("See docs/PORTABILITY.md for the full rule set + portable alternatives.")
    return "\n".join(out)


def _default_root() -> Path:
    # Repo root = the dir holding this script's parent (scripts/..). Robust to
    # the caller's cwd so `python scripts/check_portability.py` works anywhere.
    return Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Fail on macOS-isms in shipped scripts/code (spec 009)."
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repo root to scan (default: inferred from this script's location).",
    )
    args = ap.parse_args(argv)
    root = args.root if args.root is not None else _default_root()
    if not root.is_dir():
        print(f"[check_portability] root not found: {root}", file=sys.stderr)
        return 2

    findings = scan(root)
    if not findings:
        return 0
    print(format_report(findings))
    return 1


if __name__ == "__main__":
    sys.exit(main())
