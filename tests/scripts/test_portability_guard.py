"""spec 009 / US1 — deterministic, stdlib-only portability guard.

The 2026-06-03 audit found the *shipped* tree already portable (no BSD
``sed -i ''``, no hardcoded macOS paths in code, no bash-4 constructs in
shipped scripts). This guard converts that one-time audit into a permanent
invariant: a contributor who reintroduces a macOS-ism in shipped code fails
the fast loop (``pytest -m "not e2e"``) and CI before it can merge.

These tests pin both directions:
  - the **current repo** scans clean (the regression-lock), and
  - each rule fires on an injected fixture under a throwaway ``tmp_path`` root.

The guard MUST be pure stdlib (no ``shellcheck`` / external tool dependency)
so it runs everywhere ``pytest`` does — asserted by ``test_guard_is_stdlib_only``.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from scripts.check_portability import (
    RULE_KEYWORDS,
    Finding,
    format_report,
    main,
    scan,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD_SCRIPT = REPO_ROOT / "scripts" / "check_portability.py"
PORTABILITY_DOC = REPO_ROOT / "docs" / "PORTABILITY.md"


# ---------------------------------------------------------------------------
# Tiny tmp-repo builder — each rule is exercised in isolation against a
# throwaway tree so the assertions don't depend on the real repo's contents.
# ---------------------------------------------------------------------------
def _write(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def _rules(findings: list[Finding]) -> set[str]:
    return {f.rule for f in findings}


def _paths(findings: list[Finding]) -> set[str]:
    return {f.path for f in findings}


# ---------------------------------------------------------------------------
# Regression-lock: the shipped tree is clean today and must stay clean.
# ---------------------------------------------------------------------------
def test_clean_tree_passes() -> None:
    findings = scan(REPO_ROOT)
    assert findings == [], (
        "shipped tree must scan clean (locks the 2026-06-03 audit). "
        "violations:\n" + format_report(findings)
    )


# ---------------------------------------------------------------------------
# Rule 1 — BSD in-place sed (`sed -i ''`) in a shipped .sh.
# ---------------------------------------------------------------------------
def test_bsd_sed_in_place_is_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "scripts/_probe.sh",
        "#!/usr/bin/env bash\nsed -i '' 's/x/y/' file.txt\n",
    )
    findings = scan(tmp_path)
    assert "scripts/_probe.sh" in _paths(findings)
    hit = next(f for f in findings if f.path == "scripts/_probe.sh")
    assert hit.line == 2
    assert "sed" in hit.rule.lower()
    # The message must name a portable alternative so the failure is actionable.
    assert hit.hint, "BSD-sed finding must carry a fix hint"


def test_portable_sed_with_backup_suffix_is_not_flagged(tmp_path: Path) -> None:
    """`sed -i.bak …` (a real extension) is portable across BSD + GNU — only the
    empty-extension `sed -i ''` form is BSD-only and must be the sole trigger."""
    _write(
        tmp_path,
        "scripts/ok.sh",
        "#!/usr/bin/env bash\nsed -i.bak 's/x/y/' f && rm -f f.bak\n",
    )
    assert scan(tmp_path) == []


# ---------------------------------------------------------------------------
# Rule 2 — hardcoded macOS path in CODE (.py / .sh), `*.md` exempt.
# ---------------------------------------------------------------------------
def test_hardcoded_macos_path_flagged_in_code(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/research_framework/foo.py",
        'BREW = "/opt/homebrew/bin/yt-dlp"\n',
    )
    findings = scan(tmp_path)
    assert "src/research_framework/foo.py" in _paths(findings)
    assert any("path" in r.lower() for r in _rules(findings))


def test_hardcoded_macos_path_flagged_in_scripts_py(tmp_path: Path) -> None:
    _write(tmp_path, "scripts/helper.py", 'P = "~/Library/Caches/thing"\n')
    assert "scripts/helper.py" in _paths(scan(tmp_path))


def test_macos_path_in_markdown_is_ignored(tmp_path: Path) -> None:
    """Docs legitimately *describe* platform-specific steps (e.g. the macOS
    keychain-cert instruction in dist-templates/README.md). Code must not
    *hardcode* them; docs are exempt (D2)."""
    _write(tmp_path, "docs/setup.md", "Install via /opt/homebrew on macOS.\n")
    _write(tmp_path, "dist-templates/README.md", "Run `/usr/local/bin/foo`.\n")
    assert scan(tmp_path) == []


# ---------------------------------------------------------------------------
# Rule 3 — bash-4 constructs in shipped .sh (bash-3.2 is the macOS floor, D6).
# ---------------------------------------------------------------------------
def test_bash4_uppercase_expansion_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "build.sh",
        "#!/usr/bin/env bash\nname=foo\necho ${name^^}\n",
    )
    findings = scan(tmp_path)
    assert "build.sh" in _paths(findings)
    assert any("bash" in r.lower() for r in _rules(findings))


def test_bash4_declare_assoc_array_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "dist-templates/install.sh",
        "#!/usr/bin/env bash\ndeclare -A seen\n",
    )
    assert "dist-templates/install.sh" in _paths(scan(tmp_path))


def test_bash4_mapfile_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "scripts/refresh_corpus.sh",
        "#!/usr/bin/env bash\nmapfile -t arr < list.txt\n",
    )
    assert "scripts/refresh_corpus.sh" in _paths(scan(tmp_path))


def test_bash4_construct_in_python_is_not_flagged(tmp_path: Path) -> None:
    """The bash-4 rule scopes to shipped *.sh only — a `${v^^}`-looking string
    in a .py file is not shell and must not trip it."""
    _write(tmp_path, "scripts/x.py", 'TEMPLATE = "${name^^}"  # jinja-ish\n')
    findings = scan(tmp_path)
    assert not any("bash" in r.lower() for r in _rules(findings))


# ---------------------------------------------------------------------------
# Exclusions — `.specify/**` vendored spec-kit tooling (D3).
# ---------------------------------------------------------------------------
def test_specify_dir_is_excluded(tmp_path: Path) -> None:
    _write(
        tmp_path,
        ".specify/scripts/bash/create-new-feature.sh",
        "#!/usr/bin/env bash\nBRANCH=${name^^}\n",
    )
    assert scan(tmp_path) == []


def test_root_shell_entry_points_and_vault_shim_template_are_in_scope(
    tmp_path: Path,
) -> None:
    """Issue #288: `install.sh`, `generate_vault.sh` (root-level) and
    `templates/vault-script.sh.j2` (the source `./vault` renders from in
    every generated vault) were never in the guard's scan scope — a
    coverage gap, not a known live violation. A macOS-ism in any of the
    three must now be caught exactly like one in `build.sh`."""
    _write(tmp_path, "install.sh", "#!/usr/bin/env bash\nsed -i '' s/a/b/ f\n")
    _write(tmp_path, "generate_vault.sh", "#!/usr/bin/env bash\necho ${v^^}\n")
    _write(
        tmp_path,
        "templates/vault-script.sh.j2",
        "#!/usr/bin/env bash\necho {{ candidate_name }}\ndeclare -A seen\n",
    )
    findings = scan(tmp_path)
    paths = _paths(findings)
    assert "install.sh" in paths
    assert "generate_vault.sh" in paths
    assert "templates/vault-script.sh.j2" in paths


def test_guard_excludes_its_own_source(tmp_path: Path) -> None:
    """The guard file necessarily contains the forbidden literals as rule
    definitions; it must exclude itself so the clean-tree lock holds."""
    body = GUARD_SCRIPT.read_text(encoding="utf-8")
    _write(tmp_path, "scripts/check_portability.py", body)
    assert scan(tmp_path) == []


# ---------------------------------------------------------------------------
# Multiple findings + ordering.
# ---------------------------------------------------------------------------
def test_multiple_findings_sorted_by_path_then_line(tmp_path: Path) -> None:
    _write(tmp_path, "build.sh", "#!/usr/bin/env bash\necho ${v^^}\n")
    _write(tmp_path, "scripts/a.sh", "#!/usr/bin/env bash\nsed -i '' s/a/b/ f\n")
    findings = scan(tmp_path)
    keys = [(f.path, f.line) for f in findings]
    assert keys == sorted(keys)
    assert len(findings) == 2


# ---------------------------------------------------------------------------
# CLI contract — exit 0 clean, exit 1 on finding, file:line in stdout.
# ---------------------------------------------------------------------------
def test_main_returns_zero_on_clean_tree(tmp_path: Path) -> None:
    _write(tmp_path, "scripts/ok.sh", "#!/usr/bin/env bash\necho hi\n")
    assert main(["--root", str(tmp_path)]) == 0


def test_main_returns_one_on_violation(tmp_path: Path) -> None:
    _write(tmp_path, "build.sh", "#!/usr/bin/env bash\necho ${v^^}\n")
    assert main(["--root", str(tmp_path)]) == 1


def test_cli_subprocess_reports_file_and_line(tmp_path: Path) -> None:
    _write(tmp_path, "scripts/_probe.sh", "#!/usr/bin/env bash\nsed -i '' s/a/b/ f\n")
    proc = subprocess.run(
        [sys.executable, str(GUARD_SCRIPT), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "scripts/_probe.sh:2" in proc.stdout


def test_cli_subprocess_clean_repo_exits_zero() -> None:
    """The real repo, scanned via the CLI as CI invokes it, exits 0."""
    proc = subprocess.run(
        [sys.executable, str(GUARD_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ---------------------------------------------------------------------------
# SC-004 / FR-007 — the guard must not depend on any external tool.
# ---------------------------------------------------------------------------
def test_guard_is_stdlib_only() -> None:
    """Parse the guard's imports and assert every top-level module is stdlib —
    so the fast-loop guard never silently grows a `shellcheck`/3rd-party dep."""
    tree = ast.parse(GUARD_SCRIPT.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    allowed = set(sys.stdlib_module_names)
    nonstdlib = imported - allowed
    assert nonstdlib == set(), f"guard must be stdlib-only; found: {sorted(nonstdlib)}"


# ---------------------------------------------------------------------------
# SC-005 — docs/PORTABILITY.md mirrors the guard 1:1 (no doc↔guard drift).
# ---------------------------------------------------------------------------
def test_portability_doc_matches_guard() -> None:
    doc = PORTABILITY_DOC.read_text(encoding="utf-8")
    missing = [kw for kw in RULE_KEYWORDS if kw not in doc]
    assert missing == [], (
        f"docs/PORTABILITY.md must document every guard rule keyword verbatim "
        f"(SC-005 drift-lock). Missing: {missing}"
    )
