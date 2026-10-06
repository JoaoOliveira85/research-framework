"""ADR-0008 CHANGELOG regression-link lint guard (spec 024 FR-007 / US5).

Enforces that every ``### Fixed`` bullet under a released-version block in
``CHANGELOG.md`` carries exactly one of ``(test: …)``, ``(regression test: …)``,
or ``(no test: <rationale>)``. ``## [Unreleased]`` blocks are skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"

_RELEASED_HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\]")
_UNRELEASED_HEADING = re.compile(r"^## \[Unreleased\]")
_FIXED_HEADING = re.compile(
    r"^### Fixed\s*$"
    r"|^### Fixed\s*\(.+?\)\s*$"
    r"|^### Fixed\s+—\s+.+$"
)
_ANNOTATION_TEST = re.compile(r"\(test: ([^)]+)\)")
# ``regression test(s)`` (either number) and an optional ``issue #NNN; ``
# lead-in are both real, already-shipped spellings in this CHANGELOG (e.g.
# "(regression tests: ...)" and "(issue #292; regression tests: ...)") —
# not a wrapping artifact, so the regex accepts both rather than the guard
# false-failing on real content.
_ANNOTATION_REGRESSION = re.compile(
    r"\((?:issue #\d+;\s*)?regression tests?: ([^)]+)\)"
)
_ANNOTATION_NO_TEST = re.compile(r"\(no test: ([^)]*)\)")
_NESTED_LIST_MARKER = re.compile(r"^(?:[-*]|\d+\.)\s")


@dataclass(frozen=True)
class Bullet:
    """A leading ``- `` line under a released ``### Fixed`` sub-block."""

    line_number: int
    text: str
    version: str
    block_is_unreleased: bool = False


def parse_changelog_fixed_bullets(path: Path) -> list[Bullet]:
    """State-machine parse of CHANGELOG ``### Fixed`` bullets.

    A bullet's body is not just its leading ``- `` line: CHANGELOG entries
    wrap onto indented continuation lines (including the ``(test: ...)``
    annotation itself), and a bullet runs until the next ``- `` at the same
    (zero) indent or a blank line. Continuation lines are folded into the
    bullet's ``text`` (space-joined) so annotation regexes see the whole
    body regardless of which physical line the annotation landed on.

    A top-level bullet's body may itself contain a NESTED list (a ``  - ``
    or ``  1. `` sub-item, indented past the top-level continuation). Nested
    items are sub-detail, not part of the parent's compliance annotation —
    real history has top-level bullets whose nested items each carry their
    own ``(regression test: ...)`` mention (e.g. the 0.6.1 "feeds-vault revival
    post-mortem fixes" entry), which would false-positive a "more than one
    annotation" failure on the parent if folded in. Nested items and their
    own continuation lines (indented deeper than the nested marker) are
    therefore skipped rather than folded; a line that returns to the
    nested marker's indent or shallower resumes normal handling.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    bullets: list[Bullet] = []
    current_version = ""
    in_unreleased = False
    in_scoped_version = False
    in_fixed = False

    pending_parts: list[str] = []
    pending_line_number: int | None = None
    pending_version = ""
    pending_unreleased = False
    skip_until_indent_lte: int | None = None

    def flush_pending() -> None:
        nonlocal pending_parts, pending_line_number, skip_until_indent_lte
        if pending_line_number is not None:
            bullets.append(
                Bullet(
                    line_number=pending_line_number,
                    text=" ".join(pending_parts),
                    version=pending_version,
                    block_is_unreleased=pending_unreleased,
                )
            )
        pending_parts = []
        pending_line_number = None
        skip_until_indent_lte = None

    for line_number, line in enumerate(lines, start=1):
        if line.startswith("## "):
            flush_pending()
            in_fixed = False
            if _UNRELEASED_HEADING.match(line):
                in_unreleased = True
                in_scoped_version = True
                current_version = "Unreleased"
            elif match := _RELEASED_HEADING.match(line):
                in_unreleased = False
                in_scoped_version = True
                current_version = match.group(1)
            else:
                in_unreleased = False
                in_scoped_version = False
                current_version = ""
            continue

        if in_scoped_version and _FIXED_HEADING.match(line):
            flush_pending()
            in_fixed = True
            continue

        if (
            in_scoped_version
            and line.startswith("### ")
            and not _FIXED_HEADING.match(line)
        ):
            flush_pending()
            in_fixed = False
            continue

        if in_fixed and line.startswith("- "):
            flush_pending()
            pending_parts = [line]
            pending_line_number = line_number
            pending_version = current_version
            pending_unreleased = in_unreleased
            continue

        if in_fixed and pending_line_number is not None:
            if not line.strip():
                flush_pending()
                continue

            indent = len(line) - len(line.lstrip(" "))
            content = line.lstrip(" ")

            if skip_until_indent_lte is not None:
                if indent > skip_until_indent_lte:
                    continue
                skip_until_indent_lte = None

            if _NESTED_LIST_MARKER.match(content):
                skip_until_indent_lte = indent
                continue

            pending_parts.append(content.strip())
            continue

    flush_pending()
    return bullets


def _split_test_ref(ref: str) -> tuple[str, str | None]:
    """Split ``path::name``; path-only refs are allowed."""
    if "::" in ref:
        path_part, name_part = ref.split("::", 1)
        return path_part.strip(), name_part.strip() or None
    return ref.strip(), None


def _path_exists(path_part: str) -> bool:
    return (REPO_ROOT / path_part).is_file()


def _validate_ref(ref: str) -> list[str]:
    """Validate a (possibly multi-part, comma-separated) test reference.

    A single annotation may cite more than one test, e.g. ``(test: a.py,
    b.py::test_x)``, may append plain prose after the first path (``a.py,
    parametrized over every committed ...``), or may continue a prior path
    with a bare ``::test_name`` shorthand (``a.py::test_x, `::test_y```).
    Every comma-separated segment that names a path is checked; segments
    that are shorthand continuations (``::...``) or pure prose (no ``/``)
    are not paths and are skipped rather than misreported as missing files.
    """
    segments = [part.strip() for part in ref.split(",") if part.strip()]
    if not segments:
        return ["test reference does not exist in the tree"]

    saw_path = False
    problems: list[str] = []
    for segment in segments:
        stripped = segment.strip("`")
        if stripped.startswith("::"):
            continue  # shorthand continuation of the previously named file
        if "/" not in stripped:
            continue  # descriptive prose, not a second file reference
        saw_path = True
        path_part, _ = _split_test_ref(stripped)
        if not _path_exists(path_part):
            problems.append(f"test reference does not exist in the tree: {path_part}")

    if not saw_path:
        problems.append("test reference does not exist in the tree")
    return problems


# A long bullet's body may legitimately mention its test path(s) twice: once
# as the compliance tag right after the bold lead, and again much later as a
# granular breakdown in supplementary prose (e.g. the 0.6.2 "Subprocess
# timeouts" and "raw_capture.py" entries — a single leading `(regression
# test: ...)` followed, hundreds of characters later, by a `(regression
# tests: a, b, c, d)` list). That is elaboration, not a second, conflicting
# classification, and only the FIRST (earliest) annotation is the actual
# compliance tag. Two annotations crammed back-to-back right after each
# other (e.g. `(test: x) (no test: y)`) are still rejected as ambiguous.
_ADJACENT_ANNOTATION_GAP = 10


def validate_annotation(bullet: Bullet) -> list[str]:
    """Return human-readable problems for *bullet* (empty if valid)."""
    text = bullet.text
    hits = sorted(
        [("test", m) for m in _ANNOTATION_TEST.finditer(text)]
        + [("regression", m) for m in _ANNOTATION_REGRESSION.finditer(text)]
        + [("no_test", m) for m in _ANNOTATION_NO_TEST.finditer(text)],
        key=lambda pair: pair[1].start(),
    )

    if not hits:
        return [
            "missing annotation. Add `(test: ...)`, `(regression test: ...)`, "
            "or `(no test: <rationale>)`."
        ]

    kind, first = hits[0]
    for _, other in hits[1:]:
        if other.start() - first.end() <= _ADJACENT_ANNOTATION_GAP:
            return ["exactly one annotation required"]

    if kind == "no_test":
        rationale = first.group(1).strip()
        if not rationale:
            return ["rationale required"]
        return []

    return _validate_ref(first.group(1).strip())


def format_failures(
    failures: list[tuple[Bullet, list[str]]],
    changelog_path: Path = CHANGELOG_PATH,
) -> str:
    rel = changelog_path.relative_to(REPO_ROOT)
    parts = ["changelog-regression-link guard failed:", ""]
    for bullet, problems in failures:
        parts.append(f"{rel}:{bullet.line_number}  ## [{bullet.version}]")
        parts.append("                  ### Fixed")
        excerpt = bullet.text.removeprefix("- ").strip()
        if len(excerpt) > 120:
            excerpt = excerpt[:117] + "..."
        parts.append(f'                  line {bullet.line_number}: "{excerpt}"')
        for problem in problems:
            parts.append(f"                  - {problem}")
        parts.append("")
    return "\n".join(parts).rstrip()


def test_every_changelog_fixed_bullet_has_test_annotation() -> None:
    bullets = parse_changelog_fixed_bullets(CHANGELOG_PATH)
    failures: list[tuple[Bullet, list[str]]] = []
    for bullet in bullets:
        if bullet.block_is_unreleased:
            continue
        problems = validate_annotation(bullet)
        if problems:
            failures.append((bullet, problems))
    assert failures == [], format_failures(failures)


# --- inline mini-suite (synthetic CHANGELOG fixtures) ---


def _parse_fixture(markdown: str) -> list[Bullet]:
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tmp:
        tmp.write(markdown)
        tmp_path = Path(tmp.name)
    try:
        return parse_changelog_fixed_bullets(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def test_unreleased_fixed_bullets_skipped() -> None:
    fixture = """\
## [Unreleased]

### Fixed

- Bare bullet with no annotation.

## [1.0.0] - 2026-01-01

### Added

- Something else.
"""
    bullets = _parse_fixture(fixture)
    assert len(bullets) == 1
    assert bullets[0].block_is_unreleased is True
    assert bullets[0].version == "Unreleased"


def test_released_with_valid_test_annotation_passes() -> None:
    fixture = f"""\
## [1.0.0] - 2026-01-01

### Fixed

- Fixed something important. (test: {Path(__file__).relative_to(REPO_ROOT)}::test_unreleased_fixed_bullets_skipped)
"""
    bullet = _parse_fixture(fixture)[0]
    assert validate_annotation(bullet) == []


def test_released_missing_path_fails() -> None:
    fixture = """\
## [1.0.0] - 2026-01-01

### Fixed

- Fixed CLI exit code. (test: tests/path/that/does/not/exist.py::test_x)
"""
    bullet = _parse_fixture(fixture)[0]
    assert "does not exist" in validate_annotation(bullet)[0]


def test_released_bare_bullet_fails() -> None:
    fixture = """\
## [1.0.0] - 2026-01-01

### Fixed

- Fixed scout-validation race condition on slow disks.
"""
    bullet = _parse_fixture(fixture)[0]
    assert "missing annotation" in validate_annotation(bullet)[0]


def test_released_empty_no_test_rationale_fails() -> None:
    fixture = """\
## [1.0.0] - 2026-01-01

### Fixed

- Documentation-only tweak. (no test: )
"""
    bullet = _parse_fixture(fixture)[0]
    assert "rationale required" in validate_annotation(bullet)[0]


def test_released_two_annotations_fails() -> None:
    fixture = f"""\
## [1.0.0] - 2026-01-01

### Fixed

- Double-tagged. (test: {Path(__file__).relative_to(REPO_ROOT)}::test_unreleased_fixed_bullets_skipped) (no test: leftover)
"""
    bullet = _parse_fixture(fixture)[0]
    assert "exactly one" in validate_annotation(bullet)[0]


def test_multiline_bullet_annotation_on_leading_line_passes() -> None:
    fixture = f"""\
## [1.0.0] - 2026-01-01

### Fixed

- Leading line carries the tag. (test: {Path(__file__).relative_to(REPO_ROOT)}::test_multiline_bullet_annotation_on_leading_line_passes)
  - Nested detail without its own annotation.
"""
    bullets = _parse_fixture(fixture)
    assert len(bullets) == 1
    assert validate_annotation(bullets[0]) == []


def test_unreleased_block_bullets_not_in_integration_scan() -> None:
    """Unreleased ### Fixed bullets are parsed but skipped by the guard."""
    fixture = """\
## [Unreleased]

### Fixed

- In-flight fix without annotation yet.

## [1.0.0] - 2026-01-01

### Fixed

- Shipped fix. (no test: manual verification only)
"""
    parsed = _parse_fixture(fixture)
    failures = []
    for b in parsed:
        if b.block_is_unreleased:
            continue
        problems = validate_annotation(b)
        if problems:
            failures.append((b, problems))
    assert len(parsed) == 2
    assert len(failures) == 0


# --- #322 regression: the guard used to read only a bullet's first line ---


def test_released_wrapped_test_annotation_passes() -> None:
    """The exact shape of the [1.1.1] regression: the annotation itself

    wraps onto the bullet's second physical line. Before #322 the guard
    read only the leading ``- `` line, saw no ``(test: ...)`` on it at all,
    and reported "missing annotation" even though the bullet is fully
    compliant once its wrapped body is read.
    """
    fixture = f"""\
## [1.0.0] - 2026-01-01

### Fixed

- **Something broke.** (test:
  {Path(__file__).relative_to(REPO_ROOT)}::test_released_wrapped_test_annotation_passes)
  Explanatory prose that continues on further wrapped lines describing
  the fix in more detail.
"""
    bullets = _parse_fixture(fixture)
    assert len(bullets) == 1
    assert validate_annotation(bullets[0]) == []


def test_released_wrapped_regression_tests_plural_passes() -> None:
    """``(regression tests: ...)`` (plural) is a real, shipped spelling —

    not a wrapping artifact — and an optional ``issue #NNN; `` lead-in
    precedes it in several released bullets. Both must be recognised once
    the guard reads the whole (wrapped) body.
    """
    fixture = f"""\
## [1.0.0] - 2026-01-01

### Fixed

- **Something else broke.** (issue #999; regression tests:
  {Path(__file__).relative_to(REPO_ROOT)}::test_released_wrapped_regression_tests_plural_passes)
  More prose.
"""
    bullets = _parse_fixture(fixture)
    assert len(bullets) == 1
    assert validate_annotation(bullets[0]) == []


def test_multi_path_annotation_with_trailing_prose_passes() -> None:
    """A single ``(test: ...)`` may cite more than one path, or append

    plain prose after the first path (e.g. "parametrized over ..."). Only
    the comma-separated segments that look like a real path are checked.
    """
    this_test = f"{Path(__file__).relative_to(REPO_ROOT)}::test_multi_path_annotation_with_trailing_prose_passes"
    fixture = f"""\
## [1.0.0] - 2026-01-01

### Fixed

- Fixed two things at once. (test: {this_test}, parametrized over every case)
"""
    bullets = _parse_fixture(fixture)
    assert len(bullets) == 1
    assert validate_annotation(bullets[0]) == []


def test_nested_sub_bullet_with_its_own_annotation_does_not_double_count() -> None:
    """A top-level bullet's nested sub-list may carry its own compliance

    annotations (real example: the 0.6.1 "feeds-vault revival post-mortem
    fixes" entry, five nested items each with their own ``(regression
    test: ...)``). Those belong to the nested items, not the parent, and
    must not make the parent bullet fail "exactly one annotation required".
    """
    fixture = f"""\
## [1.0.0] - 2026-01-01

### Fixed

- **Parent fix.** (regression test: {Path(__file__).relative_to(REPO_ROOT)}::test_nested_sub_bullet_with_its_own_annotation_does_not_double_count)
  - Nested detail one. (regression test: tests/spec/test_schema.py)
  - Nested detail two. (regression test: tests/spec/test_schema.py)
"""
    bullets = _parse_fixture(fixture)
    assert len(bullets) == 1
    assert validate_annotation(bullets[0]) == []


def test_supplementary_annotation_far_later_in_body_does_not_double_count() -> None:
    """A long bullet may restate its test list, in more granular form,

    much later in its own prose (real example: the 0.6.2 "Subprocess
    timeouts" and "raw_capture.py" entries). That is elaboration, not a
    second, conflicting classification — only a back-to-back double-tag
    right after the lead sentence is rejected.
    """
    this_test = f"{Path(__file__).relative_to(REPO_ROOT)}::test_supplementary_annotation_far_later_in_body_does_not_double_count"
    filler = " ".join(["Explanatory prose."] * 40)
    fixture = f"""\
## [1.0.0] - 2026-01-01

### Fixed

- **Something fixed.** (regression test: {this_test}) {filler}
  (regression tests: {this_test}, tests/spec/test_schema.py)
"""
    bullets = _parse_fixture(fixture)
    assert len(bullets) == 1
    assert validate_annotation(bullets[0]) == []


def test_back_to_back_double_tag_still_rejected() -> None:
    """Two annotations crammed right next to each other (no elaboration in

    between) stay rejected as ambiguous — the adjacency check that lets
    far-apart elaboration through must not swallow this case.
    """
    ref = f"{Path(__file__).relative_to(REPO_ROOT)}::test_back_to_back_double_tag_still_rejected"
    fixture = f"""\
## [1.0.0] - 2026-01-01

### Fixed

- Double-tagged. (regression test: {ref}) (regression tests: {ref})
"""
    bullet = _parse_fixture(fixture)[0]
    assert "exactly one" in validate_annotation(bullet)[0]
