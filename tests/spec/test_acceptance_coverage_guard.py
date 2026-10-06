"""Tier-2 lint guard: specs with G/W/T scenarios must have acceptance coverage.

Authority: ``specs/024-testing-infrastructure-v2/contracts/acceptance-coverage-guard.contract.md``
ADR-0008 § Spec acceptance coverage convention.

Issue #283 fixed two independent discovery defects that had left the guard
enforcing nothing against most of the 061+ spec corpus: the numbered G/W/T
regex was single-line (missed scenarios that wrap ``**When**``/``**Then**``
onto following lines) and the guard never checked that a cited test
actually exists. Both are fixed here. The newer flat ``## Acceptance``
bullet format (070+, no per-scenario numbering) is documented as a known
gap in ``docs/adr/0012-acceptance-bullet-format-not-guarded.md`` rather than
retrofitted sight-unseen — see that ADR for why and what closing it needs.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
SPECS_DIR = _REPO_ROOT / "specs"

# Numbered G/W/T scenarios routinely wrap **When**/**Then** onto following
# lines (specs 001, 002, 019, 020, 021, 024). DOTALL lets the middle `.*?`
# cross newlines; the negative lookahead bounds the match to the current
# numbered item so it can't run on into the next one.
_GWT_LINE_NUMBERED = re.compile(
    r"^\d+\.\s+\*\*Given\*\*(?:(?!^\d+\.\s).)*?\*\*When\*\*(?:(?!^\d+\.\s).)*?\*\*Then\*\*",
    re.MULTILINE | re.DOTALL,
)
_GWT_LINE_BARE = re.compile(
    r"^\*\*Given\*\*.*?\*\*When\*\*.*?\*\*Then\*\*",
    re.MULTILINE,
)

# testing-strategy.md § Spec acceptance coverage § Rollout: "Non-retroactive.
# Existing specs (001-019, 021) are annotated only when the spec is next
# touched for substantive work." These four are the only specs that
# convention actually grandfathers AND that any known G/W/T pattern (fixed
# or not) matches today; 003-018 (other than 015a/017/018, already
# backfilled by FR-013) and 020 don't carry G/W/T content, and 020 is
# explicitly NOT grandfathered ("New specs starting with 020-code-bridge
# ... MUST include the section") so it's backfilled instead, in this PR.
# Shrinks the same way the LLM dispatch allowlist does: by backfilling one
# of these specs in a dedicated PR and deleting its entry here.
_ROLLOUT_GRANDFATHERED_SPEC_DIRS = frozenset(
    {
        "001-speckit-implementation",
        "019-pipeline-architecture",
        "021-spec-driven-coverage",
    }
)

# Multi-line bare G/W/T (e.g. 015a-corpus-folder-name user scenarios).
_GWT_GIVEN_LINE = re.compile(r"^\*\*Given\*\*", re.MULTILINE)
_GWT_WHEN_LINE = re.compile(r"^\*\*When\*\*", re.MULTILINE)
_GWT_THEN_LINE = re.compile(r"^\*\*Then\*\*", re.MULTILINE)

_SECTION_HEADING = re.compile(r"^## Acceptance coverage\s*$", re.MULTILINE)
_USER_STORY_HEADING = re.compile(
    r"^### User Story (\d+)(?:\s*[-—]\s*|\s+)",
    re.MULTILINE,
)
_STORY_HEADING = re.compile(r"^### Story (\d+)\s*[-—]\s*", re.MULTILINE)

_TOMBSTONE_MARKER = "# tombstoned"

# Folder under specs/ that holds the archived corpus (issue #274). Specs move
# here by `git mv`, so their history survives; the guard stops grading them.
_ARCHIVE_DIR_NAME = "_archive"

# Evidence cell forms (Entity 3 / contract § Required structure).
_EVIDENCE_TEST_PATH = re.compile(r"`[^`]+\.py(?:::[^`]+)?`")
_EVIDENCE_HISTORICAL = re.compile(r"_\(historical — .+?\)_")
_EVIDENCE_DEFERRED = re.compile(r"_\(deferred to tasks\.md.*?\)_")
_EVIDENCE_MULTIPLE_HINT = re.compile(r"\+\s*`|\band\b.*`|\b,\s*`", re.IGNORECASE)
# Bare pytest paths (sibling draft rows without backticks).
_EVIDENCE_BARE_TEST_PATH = re.compile(r"\btests/\S+\.py(?:::\S+)?\b")
# Populated sections from parallel 022/025 drafts (T036: not in RED failure set).
_EVIDENCE_SIBLING_DRAFT_PROSE = re.compile(
    r"section itself|test_acceptance_coverage_guard|"
    r"test_llm_dispatch_guard|llm_dispatch_allowlist|LLM dispatch guard",
    re.IGNORECASE,
)

_TABLE_ROW = re.compile(r"^\|\s*(US\d+)\s*[-—]")


@dataclass(frozen=True)
class Problem:
    message: str


def _is_tombstoned(text: str) -> bool:
    return _TOMBSTONE_MARKER in text


def _is_rollout_grandfathered(spec_path: Path) -> bool:
    return spec_path.parent.name in _ROLLOUT_GRANDFATHERED_SPEC_DIRS


def _is_archived(spec_path: Path, specs_dir: Path) -> bool:
    """True for a spec under ``specs/_archive/`` (issue #274).

    The archive holds folders that are history, not a live description of the
    system: tombstoned/superseded specs, the pre-format prose problem
    statements, the 015x consolidation drafts ADR-0009 subsumed, and the
    refactor diaries. Grading them against a convention written years later
    would demand edits to frozen records — the archive exists precisely so
    that nothing has to. ``specs/README.md`` is the index; the archive's own
    README states the rule.

    Deliberately keyed on the ``_archive`` path segment rather than a folder
    allowlist: a guard that had to be told each new archived name would
    fail open the first time someone forgot, which is the #283 failure mode.
    """
    try:
        relative = spec_path.relative_to(specs_dir)
    except ValueError:  # pragma: no cover - callers always pass an ancestor
        return False
    return _ARCHIVE_DIR_NAME in relative.parts


def _has_gwt_scenarios(text: str) -> bool:
    if _GWT_LINE_NUMBERED.search(text) or _GWT_LINE_BARE.search(text):
        return True
    return (
        _GWT_GIVEN_LINE.search(text) is not None
        and _GWT_WHEN_LINE.search(text) is not None
        and _GWT_THEN_LINE.search(text) is not None
    )


def discover_specs_with_gwt(specs_dir: Path) -> list[Path]:
    """Return in-scope spec.md paths (G/W/T declared, not tombstoned)."""
    found: list[Path] = []
    for spec_path in sorted(specs_dir.glob("**/spec.md")):
        if _is_archived(spec_path, specs_dir):
            continue
        if _is_rollout_grandfathered(spec_path):
            continue
        text = spec_path.read_text(encoding="utf-8")
        if _is_tombstoned(text):
            continue
        if _has_gwt_scenarios(text):
            found.append(spec_path)
    return found


def _declared_user_story_ids(text: str) -> set[int]:
    ids: set[int] = set()
    for match in _USER_STORY_HEADING.finditer(text):
        ids.add(int(match.group(1)))
    for match in _STORY_HEADING.finditer(text):
        ids.add(int(match.group(1)))
    return ids


def _extract_coverage_section(text: str) -> str | None:
    match = _SECTION_HEADING.search(text)
    if match is not None:
        return text[match.end() :]
    return None


def _table_us_ids_and_evidence(section_tail: str) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    for line in section_tail.splitlines():
        row_match = _TABLE_ROW.match(line)
        if not row_match:
            continue
        us_num = int(row_match.group(1)[2:])
        parts = line.split("|")
        evidence = parts[2].strip() if len(parts) >= 3 else ""
        rows.append((us_num, evidence))
    return rows


def _evidence_is_valid(cell: str) -> bool:
    if not cell.strip():
        return False
    if _EVIDENCE_HISTORICAL.search(cell) or _EVIDENCE_DEFERRED.search(cell):
        return True
    if _EVIDENCE_SIBLING_DRAFT_PROSE.search(cell):
        return True
    if _EVIDENCE_BARE_TEST_PATH.search(cell):
        return True
    paths = _EVIDENCE_TEST_PATH.findall(cell)
    if not paths:
        return False
    if len(paths) >= 2:
        return True
    if _EVIDENCE_MULTIPLE_HINT.search(cell):
        return True
    return len(paths) == 1


def _cites_test_paths(cell: str) -> bool:
    """True for the "test path" / "multiple test paths" evidence forms.

    Those are the only forms that name something checkable on disk;
    historical / deferred / sibling-draft cells are prose by design.
    """
    if _EVIDENCE_HISTORICAL.search(cell) or _EVIDENCE_DEFERRED.search(cell):
        return False
    if _EVIDENCE_SIBLING_DRAFT_PROSE.search(cell):
        return False
    return True


def _referenced_test_paths(cell: str) -> list[str]:
    backticked = (m.strip("`") for m in _EVIDENCE_TEST_PATH.findall(cell))
    bare = _EVIDENCE_BARE_TEST_PATH.findall(cell)
    return sorted(set(backticked) | set(bare))


def _symbol_defined(nodes: list[ast.stmt], names: list[str]) -> bool:
    """Walk nested def/class nodes for a dotted symbol path, e.g. Class::test."""
    if not names:
        return True
    target = names[0].split("[")[0]  # strip a parametrize id like test_foo[bar]
    def_types = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in nodes:
        if isinstance(node, def_types) and node.name == target:
            return _symbol_defined(node.body, names[1:])
    return False


def _symbol_defined_anywhere(tree: ast.AST, name: str) -> bool:
    """A def/class named `name` exists at any nesting depth in the module.

    Corpus convention routinely cites `path.py::test_method` for a method
    that actually lives inside a test class (`path.py::TestFoo::test_method`
    would be the exact pytest node id) — the class name is dropped as
    shorthand. Falling back to "exists anywhere" accepts that shorthand
    while still catching a genuinely renamed or deleted test.
    """
    def_types = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    return any(
        isinstance(node, def_types) and node.name == name for node in ast.walk(tree)
    )


def _test_reference_problem(ref: str, repo_root: Path) -> str | None:
    """None if `ref` (a `path.py` or `path.py::Symbol::...`) resolves; else why not."""
    path_part, *symbol_parts = ref.split("::")
    test_file = repo_root / path_part
    if not test_file.is_file():
        return f"`{ref}` — no such file"
    if not symbol_parts:
        return None
    tree = ast.parse(test_file.read_text(encoding="utf-8"), filename=str(test_file))
    target = symbol_parts[-1].split("[")[0]
    if _symbol_defined(tree.body, symbol_parts) or _symbol_defined_anywhere(
        tree, target
    ):
        return None
    return f"`{ref}` — file exists but defines no `{target}`"


def _evidence_reference_problems(cell: str, repo_root: Path) -> list[Problem]:
    if not _cites_test_paths(cell):
        return []
    problems: list[Problem] = []
    for ref in _referenced_test_paths(cell):
        issue = _test_reference_problem(ref, repo_root)
        if issue is not None:
            problems.append(
                Problem(message=f"Evidence cites a test that doesn't exist: {issue}")
            )
    return problems


def validate_acceptance_coverage(spec_path: Path) -> list[Problem]:
    # spec_path is always <repo_root>/specs/<NNN-name>/spec.md — walk up
    # three levels to the root evidence paths are cited relative to. Mini
    # tests below build the same shape under a tempdir, so this resolves
    # correctly for both.
    repo_root = spec_path.parents[2]
    text = spec_path.read_text(encoding="utf-8")
    problems: list[Problem] = []

    section_tail = _extract_coverage_section(text)
    if section_tail is None:
        problems.append(
            Problem(
                message=(
                    "Missing `## Acceptance coverage` section.\n"
                    "    Add one per ADR-0008 § Spec acceptance coverage convention."
                )
            )
        )
        return problems

    declared = _declared_user_story_ids(text)
    table_rows = _table_us_ids_and_evidence(section_tail)
    covered_ids = {us for us, _ in table_rows}

    for us_id in sorted(declared):
        if us_id not in covered_ids:
            problems.append(
                Problem(
                    message=(
                        f"User story US{us_id} is declared in the body but absent from\n"
                        "    the `## Acceptance coverage` table."
                    )
                )
            )

    for us_id, evidence in table_rows:
        if not evidence.strip():
            problems.append(
                Problem(
                    message=(
                        f"Row for US{us_id} has empty evidence cell.\n"
                        "    Use a test path, multiple test paths, _(historical — ...)_,\n"
                        "    or _(deferred to tasks.md...)_."
                    )
                )
            )
        elif not _evidence_is_valid(evidence):
            problems.append(
                Problem(
                    message=(
                        f"Row for US{us_id} evidence does not match an allowed form.\n"
                        "    Use a test path, multiple test paths, _(historical — ...)_,\n"
                        "    or _(deferred to tasks.md...)_."
                    )
                )
            )
        else:
            problems.extend(_evidence_reference_problems(evidence, repo_root))

    return problems


def format_failures(failures: list[tuple[Path, list[Problem]]]) -> str:
    lines = ["acceptance-coverage guard failed:", ""]
    for spec_path, problems in failures:
        try:
            rel = spec_path.relative_to(_REPO_ROOT)
        except ValueError:
            rel = spec_path
        lines.append(str(rel))
        for problem in problems:
            for part in problem.message.split("\n"):
                if part.startswith("    "):
                    lines.append(f"    {part[4:]}")
                else:
                    lines.append(f"  - {part}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def test_every_spec_with_gwt_has_acceptance_coverage() -> None:
    in_scope = discover_specs_with_gwt(SPECS_DIR)
    failures: list[tuple[Path, list[Problem]]] = []
    for spec_path in in_scope:
        problems = validate_acceptance_coverage(spec_path)
        if problems:
            failures.append((spec_path, problems))
    assert failures == [], format_failures(failures)


# --- Inline mini-suite (contract § Test behaviour) ---

_MINI_COMPLETE = """\
### User Story 1 — Example

1. **Given** x, **When** y, **Then** z.

## Acceptance coverage

| User Story | Evidence |
|------------|----------|
| US1 — Example | `tests/foo/test_bar.py` |
"""

_MINI_MISSING_SECTION = """\
### User Story 1 — Example

1. **Given** x, **When** y, **Then** z.
"""

_MINI_MISSING_US_ROW = """\
### User Story 1 — One
### User Story 2 — Two

1. **Given** x, **When** y, **Then** z.

## Acceptance coverage

| User Story | Evidence |
|------------|----------|
| US1 — One | `tests/foo/test_bar.py` |
"""

_MINI_EMPTY_EVIDENCE = """\
### User Story 1 — Example

1. **Given** x, **When** y, **Then** z.

## Acceptance coverage

| User Story | Evidence |
|------------|----------|
| US1 — Example | |
"""

_MINI_NO_GWT = """\
### User Story 1 — Example

No scenarios here.
"""


def _write_stub_test(tmp: str, relative: str) -> None:
    stub = Path(tmp) / relative
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text("def test_bar() -> None:\n    pass\n", encoding="utf-8")


def test_mini_complete_coverage_passes() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "specs" / "999" / "spec.md"
        spec.parent.mkdir(parents=True)
        spec.write_text(_MINI_COMPLETE, encoding="utf-8")
        _write_stub_test(tmp, "tests/foo/test_bar.py")
        assert discover_specs_with_gwt(Path(tmp) / "specs") == [spec]
        assert validate_acceptance_coverage(spec) == []


def test_mini_missing_section_fails() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "specs" / "999" / "spec.md"
        spec.parent.mkdir(parents=True)
        spec.write_text(_MINI_MISSING_SECTION, encoding="utf-8")
        problems = validate_acceptance_coverage(spec)
        assert len(problems) == 1
        assert "Missing" in problems[0].message


def test_mini_missing_us_row_fails() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "specs" / "999" / "spec.md"
        spec.parent.mkdir(parents=True)
        spec.write_text(_MINI_MISSING_US_ROW, encoding="utf-8")
        _write_stub_test(tmp, "tests/foo/test_bar.py")
        problems = validate_acceptance_coverage(spec)
        assert any("US2" in p.message for p in problems)


def test_mini_empty_evidence_fails() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "specs" / "999" / "spec.md"
        spec.parent.mkdir(parents=True)
        spec.write_text(_MINI_EMPTY_EVIDENCE, encoding="utf-8")
        problems = validate_acceptance_coverage(spec)
        assert any("empty evidence" in p.message for p in problems)


def test_mini_no_gwt_not_discovered() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "specs" / "999" / "spec.md"
        spec.parent.mkdir(parents=True)
        spec.write_text(_MINI_NO_GWT, encoding="utf-8")
        assert discover_specs_with_gwt(Path(tmp) / "specs") == []


# --- Issue #274: the archived corpus is out of scope ---


def test_archived_spec_is_not_discovered() -> None:
    """A spec that would otherwise be graded is skipped under `_archive/`."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        specs_dir = Path(tmp) / "specs"
        archived = specs_dir / "_archive" / "999-history" / "spec.md"
        archived.parent.mkdir(parents=True)
        archived.write_text(_MINI_MISSING_SECTION, encoding="utf-8")
        assert discover_specs_with_gwt(specs_dir) == []


def test_archiving_is_the_only_thing_that_exempts_that_spec() -> None:
    """The same bytes outside `_archive/` still fail — the exemption is the
    location, not something in the file that could be pasted anywhere."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        specs_dir = Path(tmp) / "specs"
        active = specs_dir / "999-history" / "spec.md"
        active.parent.mkdir(parents=True)
        active.write_text(_MINI_MISSING_SECTION, encoding="utf-8")
        assert discover_specs_with_gwt(specs_dir) == [active]
        assert validate_acceptance_coverage(active) != []


def test_a_folder_merely_named_like_the_archive_is_still_graded() -> None:
    """`_archive` is matched as a path segment, not a substring: a spec named
    `075-_archive-cleanup` is a live spec and stays in scope."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        specs_dir = Path(tmp) / "specs"
        spec = specs_dir / "075-_archive-cleanup" / "spec.md"
        spec.parent.mkdir(parents=True)
        spec.write_text(_MINI_MISSING_SECTION, encoding="utf-8")
        assert discover_specs_with_gwt(specs_dir) == [spec]


def test_the_repo_archive_actually_holds_specs() -> None:
    """Guards the exclusion from being vacuous: if the archive were empty (or
    renamed) this rule would be exempting nothing and should be deleted."""
    archive = SPECS_DIR / _ARCHIVE_DIR_NAME
    assert archive.is_dir(), "specs/_archive/ must exist (issue #274)"
    archived_specs = sorted(archive.glob("*/spec.md"))
    assert archived_specs, "specs/_archive/ holds no specs — drop the exclusion"


# --- Issue #283 regression coverage ---

_MINI_MULTILINE_NUMBERED_GWT = """\
### User Story 1 — Example

1. **Given** a long precondition that keeps going and going,
   **When** the wrapped action finally
   runs, **Then** the outcome is asserted here.
"""


def test_mini_multiline_numbered_gwt_is_discovered() -> None:
    """Numbered G/W/T wrapping **When**/**Then** onto later lines must be
    found — this is the exact shape specs 001, 002, 019, 020, 021 and 024
    use, and the pre-#283 single-line regex silently missed all of them."""
    assert _has_gwt_scenarios(_MINI_MULTILINE_NUMBERED_GWT)


def test_numbered_gwt_match_does_not_run_into_the_next_item() -> None:
    """The DOTALL fix must stay bounded to one numbered item, not swallow
    the whole rest of the list."""
    text = (
        "1. **Given** a, **When** b,\n"
        "   **Then** c.\n"
        "2. **Given** x, **When** y, **Then** z.\n"
    )
    match = _GWT_LINE_NUMBERED.search(text)
    assert match is not None
    assert "2. **Given**" not in match.group(0)


def test_rollout_grandfathered_specs_are_not_flagged() -> None:
    """testing-strategy.md § Rollout names 001/002/019/021 as non-retroactive.
    Fixing the DOTALL bug must not silently start failing specs the
    project's own docs say are exempt until next substantively touched."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        specs_root = Path(tmp) / "specs"
        for name in sorted(_ROLLOUT_GRANDFATHERED_SPEC_DIRS):
            spec = specs_root / name / "spec.md"
            spec.parent.mkdir(parents=True)
            spec.write_text(_MINI_MULTILINE_NUMBERED_GWT, encoding="utf-8")
        assert discover_specs_with_gwt(specs_root) == []


def test_discovery_is_not_vacuous() -> None:
    """Fail closed (#278): a guard whose discovery silently returns empty
    is worse than no guard. Assert discovery actually finds scenarios in
    the real corpus before the main test trusts that an empty failure list
    means "nothing to enforce" rather than "discovery is broken again"."""
    in_scope = discover_specs_with_gwt(SPECS_DIR)
    assert len(in_scope) >= 15, (
        f"only {len(in_scope)} spec(s) discovered with G/W/T scenarios — "
        "expected at least 15 in the current corpus. A regex change that "
        "makes discovery under-count should fail here, not silently pass "
        "test_every_spec_with_gwt_has_acceptance_coverage with zero failures."
    )


def test_mini_evidence_missing_test_file_fails() -> None:
    import tempfile

    mini = """\
### User Story 1 — Example

1. **Given** x, **When** y, **Then** z.

## Acceptance coverage

| User Story | Evidence |
|------------|----------|
| US1 — Example | `tests/foo/test_does_not_exist.py` |
"""
    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "specs" / "999" / "spec.md"
        spec.parent.mkdir(parents=True)
        spec.write_text(mini, encoding="utf-8")
        problems = validate_acceptance_coverage(spec)
        assert any("doesn't exist" in p.message for p in problems)


def test_mini_evidence_missing_test_symbol_fails() -> None:
    import tempfile

    mini = """\
### User Story 1 — Example

1. **Given** x, **When** y, **Then** z.

## Acceptance coverage

| User Story | Evidence |
|------------|----------|
| US1 — Example | `tests/foo/test_bar.py::test_not_defined` |
"""
    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "specs" / "999" / "spec.md"
        spec.parent.mkdir(parents=True)
        spec.write_text(mini, encoding="utf-8")
        _write_stub_test(tmp, "tests/foo/test_bar.py")
        problems = validate_acceptance_coverage(spec)
        assert any("doesn't exist" in p.message for p in problems)


def test_mini_evidence_existing_test_class_passes() -> None:
    """A `Class::method` reference (spec 029's real shape) must resolve
    through a nested class, not just a top-level `def`."""
    import tempfile

    mini = """\
### User Story 1 — Example

1. **Given** x, **When** y, **Then** z.

## Acceptance coverage

| User Story | Evidence |
|------------|----------|
| US1 — Example | `tests/foo/test_bar.py::TestThing::test_method` |
"""
    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "specs" / "999" / "spec.md"
        spec.parent.mkdir(parents=True)
        spec.write_text(mini, encoding="utf-8")
        stub = Path(tmp) / "tests" / "foo" / "test_bar.py"
        stub.parent.mkdir(parents=True)
        stub.write_text(
            "class TestThing:\n    def test_method(self) -> None:\n        pass\n",
            encoding="utf-8",
        )
        assert validate_acceptance_coverage(spec) == []


def test_mini_evidence_method_without_class_prefix_passes() -> None:
    """Corpus shorthand: `path.py::test_method` for a method that actually
    lives inside a test class (real shape: specs 025 US1/US2, `test_plan_
    narrator.py::test_dispatch_through_agent_call` nested in
    `TestPlanNarratorDispatchRouting`). The class name is dropped; the
    method must still resolve."""
    import tempfile

    mini = """\
### User Story 1 — Example

1. **Given** x, **When** y, **Then** z.

## Acceptance coverage

| User Story | Evidence |
|------------|----------|
| US1 — Example | `tests/foo/test_bar.py::test_method` |
"""
    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "specs" / "999" / "spec.md"
        spec.parent.mkdir(parents=True)
        spec.write_text(mini, encoding="utf-8")
        stub = Path(tmp) / "tests" / "foo" / "test_bar.py"
        stub.parent.mkdir(parents=True)
        stub.write_text(
            "class TestThing:\n    def test_method(self) -> None:\n        pass\n",
            encoding="utf-8",
        )
        assert validate_acceptance_coverage(spec) == []


def test_mini_historical_evidence_is_not_reference_checked() -> None:
    """A historical/deferred cell is prose by design; it must not be
    parsed for stray backticked `.py` mentions (spec 020's real shape:
    the historical note names a file it doesn't claim as a test)."""
    import tempfile

    mini = """\
### User Story 1 — Example

1. **Given** x, **When** y, **Then** z.

## Acceptance coverage

| User Story | Evidence |
|------------|----------|
| US1 — Example | _(historical — see `some/nonexistent/module.py`)_ |
"""
    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "specs" / "999" / "spec.md"
        spec.parent.mkdir(parents=True)
        spec.write_text(mini, encoding="utf-8")
        assert validate_acceptance_coverage(spec) == []
