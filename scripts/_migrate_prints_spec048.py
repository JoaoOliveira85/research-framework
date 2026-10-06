"""One-shot migration: replace `print()` with `_LOG.<level>()` in hot-path files.

Spec 048 / T021-T027. After this script runs, the
`test_no_net_new_print_in_hot_path_files` parametrized test passes for all
seven files.

Conversion rules (line-by-line, regex-based — multi-line `print(...)` calls
are handled because only the OPENING line contains `print(`):

1. If line contains `file=sys.stderr` → strip that kwarg + map to `.error()`
   (ERROR/critical) or `.warning()` (per content heuristics).
2. If line contains `ERROR`/`Error:` substring → `.error()`.
3. If line contains `WARN`/`⚠` substring → `.warning()`.
4. Otherwise → `.info()`.

The script also ensures each file has the canonical logger setup
(`import logging` + `_LOG = logging.getLogger(__name__)`) at module top.

Idempotent: running twice is a no-op (the regex no longer matches `print(`
after the first pass; logger-import insertion is guarded by a presence
check).

This script is committed for auditability of the migration but is NOT
intended for routine re-execution.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

HOT_PATH_FILES: tuple[str, ...] = (
    "src/research_framework/pipeline/cycle_runner.py",
    "src/research_framework/pipeline/orchestrator.py",
    "src/research_framework/pipeline/runner.py",
    "src/research_framework/pipeline/steps/scout.py",
    "src/research_framework/pipeline/steps/research.py",
    "src/research_framework/pipeline/steps/postprocess.py",
    "src/research_framework/pipeline/source_bridge/orchestrator.py",
)

# Per-file logger variable name (some files use _LOG, one uses `logger`).
LOGGER_VAR: dict[str, str] = {
    "src/research_framework/pipeline/cycle_runner.py": "_LOG",
    "src/research_framework/pipeline/orchestrator.py": "_LOG",
    "src/research_framework/pipeline/runner.py": "_LOG",
    "src/research_framework/pipeline/steps/scout.py": "_LOG",
    "src/research_framework/pipeline/steps/research.py": "_LOG",
    "src/research_framework/pipeline/steps/postprocess.py": "_LOG",
    "src/research_framework/pipeline/source_bridge/orchestrator.py": "logger",
}


def _classify_print(line: str) -> str:
    """Return the logger method to call: 'error', 'warning', or 'info'."""
    upper = line.upper()
    if "FILE=SYS.STDERR" in upper.replace(" ", ""):
        if "ERROR" in upper or "FATAL" in upper:
            return "error"
        return "warning"
    if "ERROR:" in upper or "FATAL:" in upper or "❌" in line:
        return "error"
    if "WARN" in upper or "⚠" in line:
        return "warning"
    return "info"


def _strip_stderr_kwarg(line: str) -> str:
    """Remove `, file=sys.stderr` from a print() call line."""
    return re.sub(r",\s*file\s*=\s*sys\.stderr", "", line)


def _ensure_logger_setup(content: str, logger_var: str) -> str:
    """Insert `import logging` + `_LOG = logging.getLogger(__name__)` if absent.

    Insertion points:
    - `import logging` goes alphabetically into the stdlib import block
      (after the last `import X` of stdlib, before any `from X import Y`).
      For simplicity: insert it right after `from __future__` (if present)
      OR at the top of the file (after the docstring).
    - The logger assignment goes after the LAST top-level import.
    """
    lines = content.splitlines(keepends=True)

    has_import_logging = bool(re.search(r"^import logging\b", content, re.MULTILINE))
    has_logger_assign = bool(
        re.search(
            rf"^{re.escape(logger_var)}\s*=\s*logging\.getLogger", content, re.MULTILINE
        )
    )

    if has_import_logging and has_logger_assign:
        return content

    # Find last top-level import line index.
    last_import_idx = -1
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(("import ", "from ")) and not line.startswith(
            (" ", "\t")
        ):
            last_import_idx = i

    if last_import_idx == -1:
        # No imports at all — abnormal; fall back to top after docstring.
        last_import_idx = 0

    new_lines = lines[:]

    if not has_import_logging:
        # Insert `import logging` right after the first existing import block
        # (or at the very top if no imports).
        insert_at = 0
        for i, line in enumerate(lines):
            if line.startswith(("import ", "from ")):
                insert_at = i
                break
        new_lines.insert(insert_at, "import logging\n")
        last_import_idx += 1  # account for insertion

    if not has_logger_assign:
        # Insert logger assignment after the last import line.
        new_lines.insert(
            last_import_idx + 1,
            f"\n{logger_var} = logging.getLogger(__name__)\n",
        )

    return "".join(new_lines)


def _migrate_file(path: Path, logger_var: str) -> tuple[int, int]:
    """Migrate `print(` → `<logger_var>.<level>(` in the given file.

    Returns (substitutions_made, prints_remaining).
    """
    original = path.read_text(encoding="utf-8")
    content = _ensure_logger_setup(original, logger_var)
    lines = content.splitlines(keepends=True)

    substitutions = 0
    new_lines: list[str] = []
    print_call_open_pattern = re.compile(r"^(\s*)print\(")

    for line in lines:
        match = print_call_open_pattern.match(line)
        if match:
            indent = match.group(1)
            level = _classify_print(line)
            cleaned = _strip_stderr_kwarg(line)
            new_line = print_call_open_pattern.sub(
                f"{indent}{logger_var}.{level}(",
                cleaned,
                count=1,
            )
            new_lines.append(new_line)
            substitutions += 1
        else:
            new_lines.append(line)

    new_content = "".join(new_lines)

    # Count remaining `print(` occurrences (should be zero in normal Python code).
    remaining = len(re.findall(r"^\s*print\(", new_content, re.MULTILINE))

    if new_content != original:
        path.write_text(new_content, encoding="utf-8")

    return substitutions, remaining


def main() -> int:
    total_substituted = 0
    failures: list[str] = []

    for relpath in HOT_PATH_FILES:
        path = REPO_ROOT / relpath
        if not path.exists():
            print(f"SKIP (missing): {relpath}", file=sys.stderr)
            continue
        logger_var = LOGGER_VAR[relpath]
        substitutions, remaining = _migrate_file(path, logger_var)
        total_substituted += substitutions
        marker = "OK" if remaining == 0 else "FAIL"
        msg = f"{marker} {relpath}: -{substitutions} prints (remaining: {remaining})"
        print(msg, file=sys.stderr)
        if remaining > 0:
            failures.append(relpath)

    print(f"\nTotal substitutions: {total_substituted}", file=sys.stderr)
    if failures:
        print(f"\nFAILED files: {failures}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
