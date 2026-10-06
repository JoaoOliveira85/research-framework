"""`.specify/templates` compliance guard (issue #282).

The written process is model-grade; the templates it runs on were stock
spec-kit. So the project's own required sections were known only by
imitation — you learned that a spec needs an `## Acceptance coverage` table
by opening a spec that happened to have one. The measurable consequence:
20 of the 38 spec folders with a `tasks.md` carry no `### Testing
Requirements` block, and the acceptance-coverage guard's own required
section appeared nowhere in the template that produces the file it grades.

The templates now carry both. This guard is what keeps them carrying them,
and — the part that matters — it checks the templates against the *real
parsers*, not against a regex of what the parser is believed to want:

* the tasks template's sample block is parsed by
  ``scripts/foreman.verify_test_coverage.parse_tasks_md``, the same function
  the foreman runs, so a sample that the verifier would silently skip fails
  here instead;
* the spec template's coverage table is discovered and validated by
  ``tests/spec/test_acceptance_coverage_guard``'s own helpers, so a template
  whose section heading or row shape has drifted from the guard fails here.

A template that produces a file its own guard rejects is worse than no
template — it teaches the wrong shape with authority.
"""

from __future__ import annotations

from pathlib import Path

from scripts.foreman.verify_test_coverage import parse_tasks_md
from tests.spec.test_acceptance_coverage_guard import (
    _SECTION_HEADING,
    _TABLE_ROW,
    _USER_STORY_HEADING,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = REPO_ROOT / ".specify" / "templates"
SPEC_TEMPLATE = TEMPLATES / "spec-template.md"
TASKS_TEMPLATE = TEMPLATES / "tasks-template.md"
PLAN_TEMPLATE = TEMPLATES / "plan-template.md"


def _spec_text() -> str:
    return SPEC_TEMPLATE.read_text(encoding="utf-8")


def _tasks_text() -> str:
    return TASKS_TEMPLATE.read_text(encoding="utf-8")


# --- The tasks template must produce a file the foreman can verify --------


def test_tasks_template_declares_the_block_as_mandatory() -> None:
    """`SHOULD` is what bought 20 blockless tasks.md files."""
    text = _tasks_text()
    assert "**MUST** carry a `### Testing Requirements` block" in text, (
        "the tasks template must require the block, not suggest it — "
        "a suggested block is the one nobody writes"
    )


def test_tasks_template_sample_carries_a_real_block() -> None:
    """The sample is the specification: a `/speckit.tasks` run copies the
    shape it sees, so a blockless sample produces blockless output however
    emphatic the prose above it."""
    tasks = parse_tasks_md(_tasks_text())
    with_requirements = [t for t in tasks if t.required_tests]
    assert with_requirements, (
        "the foreman's own parser found no task with a Testing Requirements "
        "block in the tasks template — the sample teaches the wrong shape"
    )


def test_the_sample_block_is_attached_to_an_implementation_task() -> None:
    """A block on a documentation or setup task would parse but would not
    demonstrate the rule, which is about tasks with executable behaviour."""
    tasks = {t.task_id: t for t in parse_tasks_md(_tasks_text())}
    sample = tasks.get("T014")
    assert sample is not None, "the tasks template lost its T014 sample task"
    assert sample.required_tests, "T014 (an implementation task) has no block"
    assert sample.tdd_required, (
        "T014's block must declare TDD discipline — the block's whole point "
        "is that the test predates the implementation"
    )


def test_the_sample_block_declares_a_repo_relative_test_path() -> None:
    """`parse_tasks_md` rejects absolute paths and `..` traversal. A sample
    that only parses because the parser was lenient would mislead."""
    tasks = {t.task_id: t for t in parse_tasks_md(_tasks_text())}
    for required in tasks["T014"].required_tests:
        assert required.path.startswith("tests/"), (
            f"sample test path {required.path!r} is not under tests/"
        )
        assert required.function, "the sample must name a test function"


def test_the_sample_block_survives_tolerant_mode_too() -> None:
    """Spec 057 added a tolerant matching mode; the sample must be valid
    under both, or the template is only correct for one caller."""
    tasks = parse_tasks_md(_tasks_text(), matching_mode="tolerant")
    assert any(t.required_tests for t in tasks)


# --- The spec template must produce a file the coverage guard accepts -----


def test_spec_template_has_the_acceptance_coverage_section() -> None:
    """The heading the acceptance-coverage guard searches for, matched with
    the guard's own regex rather than a copy of it."""
    assert _SECTION_HEADING.search(_spec_text()), (
        "spec-template.md has no `## Acceptance coverage` section — the "
        "guard requires one on every spec with G/W/T scenarios, and the "
        "template that produces those specs never mentioned it"
    )


def test_spec_template_coverage_table_rows_match_the_guard() -> None:
    """A row the guard cannot parse is a row the guard cannot check."""
    tail = _spec_text().split("## Acceptance coverage", 1)[1]
    rows = [line for line in tail.splitlines() if _TABLE_ROW.match(line)]
    assert len(rows) >= 2, (
        "the coverage table's sample rows are not in the `| USn — ... |` "
        "shape the guard matches"
    )


def test_spec_template_has_a_row_per_sample_user_story() -> None:
    """The guard requires one row per declared story; the template must
    demonstrate that, not a single specimen row."""
    text = _spec_text()
    stories = {int(m.group(1)) for m in _USER_STORY_HEADING.finditer(text)}
    tail = text.split("## Acceptance coverage", 1)[1]
    rows = {
        int(_TABLE_ROW.match(line).group(1)[2:])  # type: ignore[union-attr]
        for line in tail.splitlines()
        if _TABLE_ROW.match(line)
    }
    assert stories <= rows, (
        f"the template declares User Stories {sorted(stories)} but its "
        f"coverage table only has rows for {sorted(rows)}"
    )


def test_spec_template_documents_the_evidence_forms() -> None:
    """The three accepted evidence forms are the part of the convention that
    is genuinely non-obvious; the template is where an author meets them."""
    text = _spec_text()
    for form in ("_(historical —", "_(deferred to tasks.md"):
        assert form in text, (
            f"the template does not document the {form!r} evidence form"
        )


def test_spec_template_warns_against_deleting_the_section() -> None:
    """The cheapest way to silence the guard is to delete the section; the
    template has to say that out loud, because nothing else will."""
    assert "Do not delete this section" in _spec_text()


# --- The plan template's Constitution Check is real, not boilerplate ------


def test_plan_template_constitution_check_names_the_current_version() -> None:
    """Stock spec-kit ships a placeholder Constitution Check. This one must
    cite the constitution it actually checks against."""
    text = PLAN_TEMPLATE.read_text(encoding="utf-8")
    constitution = (REPO_ROOT / ".specify" / "memory" / "constitution.md").read_text(
        encoding="utf-8"
    )
    assert "## Constitution Check" in text
    assert "`.specify/memory/constitution.md`" in text
    version = next(
        (
            line.split("**v")[1].split("**")[0]
            for line in text.splitlines()
            if "constitution.md` **v" in line
        ),
        None,
    )
    assert version, "the plan template does not name a constitution version"
    assert f"Version**: {version}" in constitution or f"v{version}" in constitution, (
        f"plan-template.md checks against constitution v{version}, which is "
        "not the version the constitution declares"
    )


def test_plan_template_gate_rows_are_answerable() -> None:
    """A gate table whose rows are `[placeholder]` is the boilerplate #282
    was filed about."""
    text = PLAN_TEMPLATE.read_text(encoding="utf-8")
    section = text.split("## Constitution Check", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| ")]
    numbered = [row for row in rows if row.startswith("| I") or row.startswith("| V")]
    assert len(numbered) >= 3, (
        "the Constitution Check has fewer than three principle rows — it "
        "looks like the stock placeholder, not a real gate"
    )
    assert "[NEEDS" not in section and "[PLACEHOLDER" not in section.upper()


# --- The backfill ratchet -------------------------------------------------
#
# 20 active specs carry a `tasks.md` with no Testing Requirements block.
# Every one is `shipped(...)` or a compound-claim header of the same vintage:
# the block convention arrived with the foreman (spec 057, 2026-07-01), and
# its own text says it is "authored by the test-design agent BEFORE
# implementation starts". Retro-fitting it onto work that shipped months
# earlier would produce a block that is false on its face — the same reason
# #279 converted shipped task boxes to a plain ledger rather than inventing
# citations for them.
#
# So the debt is named rather than laundered, and this list may only shrink:
# a spec that is not on it must carry a block. It shrinks the way this repo's
# other exception lists do — one entry at a time, in a PR that does the work.

SPECS_WITHOUT_TESTING_REQUIREMENTS: frozenset[str] = frozenset(
    {
        "001-speckit-implementation",
        "009-linux-support",
        "017-vault-quality-fix",
        "018-testing-strategy",
        "019-pipeline-architecture",
        "022-e2e-quality-harness",
        "024-testing-infrastructure-v2",
        "026-fixture-isolation",
        "028-dispatch-telemetry",
        "029-source-manager-correctness",
        "040-vault-reports-delivery",
        "053-source-authority-strategy",
        "055-source-credibility-model",
        "058-vault-spec-health-warning",
        "060-source-modules-tier2",
        "066-credibility-model-calibration",
        "068-coverage-counting-correctness",
        "069-source-relevance-tuning",
        "070-strategy-hint-credibility-and-silent-resume",
    }
)

_BLOCK_HEADING = "### Testing Requirements"


def _specs_with_tasks() -> dict[str, Path]:
    specs = REPO_ROOT / "specs"
    return {
        child.name: child / "tasks.md"
        for child in sorted(specs.iterdir())
        if child.is_dir()
        and child.name != "_archive"
        and (child / "tasks.md").is_file()
    }


def test_no_new_spec_ships_a_blockless_tasks_file() -> None:
    """The ratchet. A spec added after #282 must carry the block the template
    now makes mandatory; the pre-convention 20 are named above."""
    offenders = sorted(
        name
        for name, tasks_md in _specs_with_tasks().items()
        if name not in SPECS_WITHOUT_TESTING_REQUIREMENTS
        and _BLOCK_HEADING not in tasks_md.read_text(encoding="utf-8")
    )
    assert not offenders, (
        "spec(s) with a tasks.md and no `### Testing Requirements` block:\n"
        + "\n".join(f"  - {name}" for name in offenders)
        + "\n\nAdd the block (see .specify/templates/tasks-template.md). If the "
        "spec genuinely predates the convention, that is a decision for a "
        "human to record by name in SPECS_WITHOUT_TESTING_REQUIREMENTS."
    )


def test_the_exception_list_only_shrinks() -> None:
    """Guards the list from rotting: an entry whose spec has since gained a
    block, or been archived, must be deleted rather than left standing."""
    with_tasks = _specs_with_tasks()
    stale: list[str] = []
    for name in sorted(SPECS_WITHOUT_TESTING_REQUIREMENTS):
        tasks_md = with_tasks.get(name)
        if tasks_md is None:
            stale.append(f"{name}: no longer an active spec with a tasks.md")
        elif _BLOCK_HEADING in tasks_md.read_text(encoding="utf-8"):
            stale.append(f"{name}: has a block now — remove it from the list")
    assert not stale, "stale exception entries:\n" + "\n".join(
        f"  - {entry}" for entry in stale
    )


def test_every_trunk_spec_written_for_282_carries_a_block() -> None:
    """The backfill that *can* be honest: the five trunk specs (#275) were
    authored with the block, before the follow-up work it declares."""
    trunk = [
        "075-pipeline-runner",
        "076-settings-schema",
        "077-cli-contract",
        "078-dispatch-surface",
        "079-note-format",
    ]
    with_tasks = _specs_with_tasks()
    missing = [
        name
        for name in trunk
        if name not in with_tasks
        or _BLOCK_HEADING not in with_tasks[name].read_text(encoding="utf-8")
    ]
    assert not missing, "trunk specs with no Testing Requirements block: " + ", ".join(
        missing
    )


def test_the_trunk_blocks_parse_with_the_foremans_own_grammar() -> None:
    """A block the foreman cannot parse is a block the foreman skips, which
    is indistinguishable from having written none."""
    with_tasks = _specs_with_tasks()
    for name in ("075-pipeline-runner", "079-note-format"):
        tasks = parse_tasks_md(with_tasks[name].read_text(encoding="utf-8"))
        assert any(t.required_tests for t in tasks), (
            f"{name}/tasks.md declares a block the foreman parser does not see"
        )
