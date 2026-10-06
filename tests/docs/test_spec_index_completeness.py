"""Spec-index completeness guard (issue #274).

Before `specs/README.md` there was no index of the spec corpus at all — 82
folders, no table of contents, and no way to tell an active spec from a
history-only one without opening each `spec.md` and reading its Status
header. The consolidation that created `specs/_archive/` makes that worse
before it makes it better: a reader now has to know that two directories
exist and which one a given number lives in.

An index only helps if it is true. A hand-maintained table of 80+ rows goes
stale on the first PR that adds a spec and forgets it, and a stale index is
worse than none — it is a document that positively asserts a folder does not
exist. This guard is what makes the index load-bearing: it derives the two
sets from the filesystem and requires the two tables to match them exactly,
in both directions.

Deliberately narrow. It checks *which* folders are listed and in which
table — nothing about the Title or Status columns. Those are a convenience
copy of the spec's own H1 and canonical header, and
``tests/docs/test_spec_status_headers.py`` already owns the header. Pinning
the copies here would make one fact enforceable in two places, which is the
duplication issue #281 was filed about.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPECS_DIR = REPO_ROOT / "specs"
ARCHIVE_DIR = SPECS_DIR / "_archive"
INDEX = SPECS_DIR / "README.md"

_ACTIVE_HEADING = "## Active corpus"
_ARCHIVED_HEADING = "## Archived corpus"
_READERS_HEADING = "## What reads this file"

# A row links its folder: `| [`NNN-name`](NNN-name/spec.md) | title | status |`
_ROW_LINK = re.compile(r"^\|\s*\[`([^`]+)`\]\(([^)]+)\)\s*\|", re.MULTILINE)


def _section(text: str, start_heading: str, end_heading: str) -> str:
    start = text.index(start_heading)
    end = text.index(end_heading, start)
    return text[start:end]


def _listed_folders(section: str) -> list[str]:
    return [match.group(1) for match in _ROW_LINK.finditer(section)]


def _index_text() -> str:
    assert INDEX.is_file(), f"{INDEX.relative_to(REPO_ROOT)} must exist"
    return INDEX.read_text(encoding="utf-8")


def _spec_dirs(root: Path) -> set[str]:
    """Folders holding a spec.md, directly under *root* (never recursive)."""
    return {
        child.name
        for child in root.iterdir()
        if child.is_dir() and child.name != "_archive" and (child / "spec.md").is_file()
    }


def _active_listed() -> list[str]:
    text = _index_text()
    return _listed_folders(_section(text, _ACTIVE_HEADING, _ARCHIVED_HEADING))


def _archived_listed() -> list[str]:
    text = _index_text()
    return _listed_folders(_section(text, _ARCHIVED_HEADING, _READERS_HEADING))


def test_active_table_lists_every_active_spec() -> None:
    on_disk = _spec_dirs(SPECS_DIR)
    listed = set(_active_listed())
    missing = sorted(on_disk - listed)
    extra = sorted(listed - on_disk)
    assert not missing, "specs/README.md's Active table is missing:\n" + "\n".join(
        f"  - {name}" for name in missing
    )
    assert not extra, (
        "specs/README.md's Active table lists folders that do not exist "
        "(or that moved to _archive/):\n" + "\n".join(f"  - {name}" for name in extra)
    )


def test_archived_table_lists_every_archived_spec() -> None:
    on_disk = _spec_dirs(ARCHIVE_DIR)
    listed = set(_archived_listed())
    missing = sorted(on_disk - listed)
    extra = sorted(listed - on_disk)
    assert not missing, "specs/README.md's Archived table is missing:\n" + "\n".join(
        f"  - {name}" for name in missing
    )
    assert not extra, (
        "specs/README.md's Archived table lists folders that are not in "
        "specs/_archive/:\n" + "\n".join(f"  - {name}" for name in extra)
    )


def test_no_spec_is_listed_in_both_tables() -> None:
    both = sorted(set(_active_listed()) & set(_archived_listed()))
    assert not both, "listed as both active and archived:\n" + "\n".join(
        f"  - {name}" for name in both
    )


def test_every_row_links_to_the_file_it_names() -> None:
    """A row whose link text and href disagree sends the reader to the wrong
    spec — the specific rot a copy-pasted table acquires first."""
    text = _index_text()
    active = _section(text, _ACTIVE_HEADING, _ARCHIVED_HEADING)
    archived = _section(text, _ARCHIVED_HEADING, _READERS_HEADING)
    broken: list[str] = []
    for section, prefix in ((active, ""), (archived, "_archive/")):
        for match in _ROW_LINK.finditer(section):
            name, href = match.group(1), match.group(2)
            expected = f"{prefix}{name}/spec.md"
            if href != expected:
                broken.append(f"{name}: links to {href!r}, expected {expected!r}")
            if not (SPECS_DIR / href).is_file():
                broken.append(f"{name}: {href} does not exist")
    assert not broken, "broken index rows:\n" + "\n".join(f"  - {b}" for b in broken)


def test_the_archive_is_not_empty() -> None:
    """Keeps the split honest: an empty archive means the consolidation was
    reverted and this whole index/guard pair should go with it."""
    assert ARCHIVE_DIR.is_dir(), "specs/_archive/ must exist (issue #274)"
    assert _spec_dirs(ARCHIVE_DIR), "specs/_archive/ holds no specs"


def test_the_index_documents_its_own_readers() -> None:
    """The index claims which guards read it; if this section is dropped, the
    next person to add a table has no way to know one exists."""
    text = _index_text()
    assert _READERS_HEADING in text
    assert "test_spec_index_completeness.py" in text


def _names_the_archive(value: str) -> bool:
    """A string that is an archive *path*, not a word containing the segment.

    ``specs/_archive/...`` is the written-out form; a bare ``"_archive"`` is
    the ``Path.joinpath`` component form the schema test used. Neither
    ``notes_archived`` nor ``_archive_applied_directive`` is a path, and the
    first draft of this guard failed on all three.
    """
    return "specs/_archive" in value or value == "_archive"


def _archive_path_literals(path: Path) -> list[tuple[int, str]]:
    """String literals naming the archive — not comments or docstrings.

    A file may *describe* the rule (this module does, and so does the schema
    test that used to break it). What the rule forbids is *opening* something
    in there, and a path arrives in code as a string literal.
    """
    body = path.read_text(encoding="utf-8")
    if "_archive" not in body:
        return []
    if path.suffix != ".py":
        return [
            (n, line.strip()[:90])
            for n, line in enumerate(body.splitlines(), start=1)
            if "specs/_archive" in line and not line.lstrip().startswith("#")
        ]
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return []
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    return [
        (node.lineno, node.value[:90])
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _names_the_archive(node.value)
        and id(node) not in docstrings
    ]


def test_no_tracked_file_outside_specs_opens_a_file_in_the_archive() -> None:
    """The archive rule, enforced (#295).

    ``specs/_archive/README.md`` states the rule that puts a folder here:
    tombstoned, pre-format, a 015x draft, a vault-instance plan or a refactor
    diary — **and** no tracked file outside ``specs/`` opens a file inside it.
    The second half is what keeps the archive history rather than
    infrastructure, and it was prose only: ``tests/contracts/`` reached into
    ``specs/_archive/015g-pipeline-orchestrator-command/contracts/`` for a live
    schema for as long as the folder had been archived, and nothing said so.

    Scanning the tracked tree rather than the working tree is deliberate — an
    untracked scratch file that reads the archive is nobody's contract.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\0")

    offenders: list[str] = []
    for rel in tracked:
        if not rel or rel.startswith("specs/"):
            continue
        path = REPO_ROOT / rel
        if path.suffix not in {".py", ".sh", ".toml", ".cfg", ".yaml", ".yml"}:
            continue
        try:
            hits = _archive_path_literals(path)
        except (OSError, UnicodeDecodeError):
            continue
        offenders.extend(f"{rel}:{lineno}  {text}" for lineno, text in hits)

    # The three guards that name the directory in order to SKIP it. Each holds
    # the bare segment ``_archive`` as a comparison value, never a path it opens.
    allowed_prefixes = (
        "tests/spec/test_acceptance_coverage_guard.py",
        "tests/docs/test_spec_index_completeness.py",
        "tests/docs/test_specify_templates_are_ours.py",
    )
    unexpected = [o for o in offenders if not o.startswith(allowed_prefixes)]
    assert unexpected == [], (
        "a tracked file outside specs/ names specs/_archive/ — the archive rule "
        "(specs/_archive/README.md) says nothing outside specs/ may open a file "
        "inside it. Move the file it needs into the active corpus (see #295):\n"
        + "\n".join(f"  {o}" for o in unexpected)
    )


def test_the_archive_rule_guard_detects_a_real_reference(tmp_path: Path) -> None:
    """A guard that reports zero because it looks for nothing is the failure
    mode the battery exists to avoid (#283). These are the two spellings the
    schema test actually used before #295 moved the file."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        '"""A docstring naming specs/_archive/ is prose, not a path."""\n'
        "# a comment naming specs/_archive/ is prose too\n"
        'p = REPO_ROOT / "specs/_archive/015g/contracts/x.json"\n'
        'q = REPO_ROOT.joinpath("specs", "_archive", "015g")\n'
        'r = {"notes_archived": 1}\n',
        encoding="utf-8",
    )
    assert [line for line, _ in _archive_path_literals(sample)] == [3, 4]
