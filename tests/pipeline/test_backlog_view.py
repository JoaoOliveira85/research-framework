"""Spec 084 T003: the rendered view, hand-edit detection, no parsing."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

import pytest

from research_framework.pipeline import backlog, state_layout

LOGGER = "research_framework.pipeline.backlog"
ROOT = Path(__file__).resolve().parents[2]


def _entry(entry_id: str, title: str, origin: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": entry_id,
        "title": title,
        "origin": origin,
        "status": "open",
        "status_by": "operator" if origin == "operator" else origin,
        "status_written": "open",
        **extra,
    }


def _seed(vault: Path, entries: list[dict[str, Any]]) -> None:
    path = state_layout.research_backlog_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": "1.0", "entries": entries}, indent=2) + "\n",
        encoding="utf-8",
    )


def _targets(vault: Path, categories: list[dict[str, Any]]) -> None:
    path = state_layout.coverage_targets_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"last_updated": "", "cycle_number": 1, "categories": categories}),
        encoding="utf-8",
    )


def _render(vault: Path) -> str:
    backlog.update(vault, "harvest", lambda tx: None)
    return backlog.view_path(vault).read_text(encoding="utf-8")


def _full_store() -> list[dict[str, Any]]:
    return [
        _entry(
            "topic:late",
            "Late",
            "harvest",
            citation_count=5,
            cited_from=["a.md", "b.md", "c.md", "d.md", "e.md"],
            first_seen_cycle=3,
            last_seen_cycle=3,
            seen_cycles=1,
        ),
        _entry(
            "topic:early",
            "Early",
            "harvest",
            citation_count=1,
            cited_from=["z.md"],
            first_seen_cycle=1,
            last_seen_cycle=3,
            seen_cycles=2,
        ),
        _entry(
            "topic:flagged",
            "Flagged",
            "researcher",
            detail="Needs a source",
            first_seen_cycle=2,
        ),
        _entry(
            "topic:merged",
            "Merged",
            "researcher",
            citation_count=2,
            cited_from=["m.md"],
            first_seen_cycle=2,
            last_seen_cycle=2,
            seen_cycles=1,
        ),
        _entry(
            "quarantine:deseq",
            "deseq",
            "quarantine",
            stem="deseq",
            kind="rewrite",
            detail="thin",
        ),
        _entry(
            "quarantine:qc",
            "qc",
            "quarantine",
            stem="qc",
            kind="retry",
            detail="timeout",
        ),
        _entry(
            "topic:mine",
            "Mine",
            "operator",
            detail="look at this",
            first_seen_cycle=None,
        ),
        _entry(
            "topic:tangent",
            "Tangent",
            "proposal",
            relation="adjacent",
            parent_note="Parent",
            scope_warn=True,
            detail="because",
            first_seen_cycle=2,
        ),
        _entry(
            "migrated:0001", "| Pending | x |", "migrated", detail="| Pending | x |"
        ),
        {
            **_entry("topic:done", "Done", "harvest"),
            "status": "resolved",
            "status_written": "resolved",
        },
        {
            **_entry("topic:nope", "Nope", "operator"),
            "status": "dropped",
            "status_written": "dropped",
        },
    ]


def test_view_matches_the_contract_layout(tmp_path: Path) -> None:
    _seed(tmp_path, _full_store())
    _targets(
        tmp_path,
        [
            {
                "name": "Concepts",
                "note_type": "concept",
                "target_count": 10,
                "met_count": 4,
                "required": True,
            },
            {
                "name": "Done",
                "note_type": "flow",
                "target_count": 2,
                "met_count": 2,
                "required": True,
            },
        ],
    )
    text = _render(tmp_path)
    body, footer = text.rsplit("<!-- research-backlog-view", 1)
    expected = """\
# Research Backlog

> Generated from `_pipeline/state/research-backlog.json` — edit that file,
> not this one. A change made here is overwritten on the next write; the
> overwritten text is kept once at `_pipeline/research-backlog.md.overwritten`.

## Follow-on topics (harvest)

- **Early** — cited by 1 note(s): `z.md` · first seen cycle 1, last seen cycle 3 (2 cycles)
- **Merged** — cited by 2 note(s): `m.md` · first seen cycle 2, last seen cycle 2 (1 cycle)
- **Late** — cited by 5 note(s): `a.md`, `b.md`, `c.md` (+2 more) · first seen cycle 3, last seen cycle 3 (1 cycle)

## Flagged by the researcher

- **Flagged** — Needs a source · first seen cycle 2

## Quarantined notes

- **deseq** — rewrite the quarantined note (thin)
- **qc** — retry the refresh; previous content restored (timeout)

## Added by the operator

- **Mine** — look at this

## Proposed tangents (advisory)

- **Tangent** ⚠️ (adjacent of [[Parent]]) — because

## Carried over from the old backlog

- | Pending | x |

## Unmet coverage categories

- `Concepts` [concept] — 4/10 (required)

_1 resolved and 1 dropped entries are kept in the JSON file._

"""
    assert body == expected
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert footer == f" sha256={digest} -->\n"
    assert text.endswith("-->\n") and not text.endswith("\n\n")


def test_empty_sections_are_omitted_but_header_summary_and_footer_stay(
    tmp_path: Path,
) -> None:
    text = _render(tmp_path)
    assert "# Research Backlog" in text
    assert "## " not in text
    assert "_0 resolved and 0 dropped entries are kept in the JSON file._" in text
    assert re.search(r"<!-- research-backlog-view sha256=[0-9a-f]{64} -->\n\Z", text)


def test_coverage_section_is_read_live_and_never_stored(tmp_path: Path) -> None:
    backlog.update(tmp_path, "harvest", lambda tx: None)
    _targets(
        tmp_path,
        [
            {
                "name": "Flows",
                "note_type": "flow",
                "target_count": 3,
                "met_count": 0,
                "required": False,
            }
        ],
    )
    text = _render(tmp_path)
    assert "- `Flows` [flow] — 0/3 (optional)" in text
    store = state_layout.research_backlog_path(tmp_path).read_text(encoding="utf-8")
    assert "Flows" not in store
    state_layout.coverage_targets_path(tmp_path).write_text("{broken", encoding="utf-8")
    assert "Unmet coverage" not in _render(tmp_path)


def test_hand_edit_is_kept_once_and_warned_about(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _seed(tmp_path, [_entry("topic:a", "A", "operator")])
    _render(tmp_path)
    view = backlog.view_path(tmp_path)
    copy = backlog.overwritten_path(tmp_path)
    assert not copy.exists()

    first = view.read_text(encoding="utf-8").replace("**A**", "**A edited**")
    view.write_text(first, encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        _render(tmp_path)
    assert copy.read_text(encoding="utf-8") == first
    assert "A edited" not in view.read_text(encoding="utf-8")
    [record] = [r for r in caplog.records if r.levelno == logging.WARNING]
    message = record.getMessage()
    assert "_pipeline/state/research-backlog.json" in message
    assert str(copy) in message

    caplog.clear()
    second = "totally different\n"
    view.write_text(second, encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        _render(tmp_path)
    assert copy.read_text(encoding="utf-8") == second  # replaced, not accumulated
    assert sorted(p.name for p in copy.parent.glob("research-backlog.md*")) == [
        "research-backlog.md",
        "research-backlog.md.overwritten",
    ]
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_a_legacy_script_write_is_treated_as_a_hand_edit(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _seed(tmp_path, [])
    view = backlog.view_path(tmp_path)
    view.parent.mkdir(parents=True, exist_ok=True)
    view.write_text("# Research Backlog\n\n<!-- topic-harvest:cycle=001 -->\n")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        _render(tmp_path)
    assert backlog.overwritten_path(tmp_path).read_text().startswith("# Research")
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_a_change_in_the_store_rerenders_without_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _seed(tmp_path, [_entry("topic:a", "A", "operator")])
    _render(tmp_path)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        backlog.observe_topic(
            tmp_path, "harvest", cycle=1, title="B", origin="harvest", citation_count=1
        )
    assert "**B**" in backlog.view_path(tmp_path).read_text(encoding="utf-8")
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not backlog.overwritten_path(tmp_path).exists()


def test_identical_render_writes_nothing(tmp_path: Path) -> None:
    _seed(tmp_path, [_entry("topic:a", "A", "operator")])
    _render(tmp_path)
    view = backlog.view_path(tmp_path)
    store = state_layout.research_backlog_path(tmp_path)
    before = (view.stat().st_mtime_ns, view.read_bytes(), store.stat().st_mtime_ns)
    assert backlog.update(tmp_path, "harvest", lambda tx: None) is True
    assert backlog.ensure_view(tmp_path) == view
    assert (
        view.stat().st_mtime_ns,
        view.read_bytes(),
        store.stat().st_mtime_ns,
    ) == before
    assert not backlog.overwritten_path(tmp_path).exists()


def test_missing_view_is_rendered_before_a_read(tmp_path: Path) -> None:
    _seed(tmp_path, [_entry("topic:a", "A", "operator", detail="d")])
    view = backlog.view_path(tmp_path)
    assert not view.exists()
    assert backlog.ensure_view(tmp_path) == view
    assert "- **A** — d" in view.read_text(encoding="utf-8")


def test_ensure_view_leaves_an_unusable_store_alone(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = state_layout.research_backlog_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{nope")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert backlog.ensure_view(tmp_path) is None
    assert not backlog.view_path(tmp_path).exists()
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    # and a vault with no store at all gets no view invented
    assert backlog.ensure_view(tmp_path / "other") is None


def test_a_skipped_write_does_not_touch_the_view(tmp_path: Path) -> None:
    _seed(tmp_path, [])
    _render(tmp_path)
    view = backlog.view_path(tmp_path)
    before = view.read_bytes()
    state_layout.research_backlog_path(tmp_path).write_text("{broken")
    assert backlog.update(tmp_path, "harvest", lambda tx: None) is False
    assert view.read_bytes() == before


# Files that still read or write the Markdown backlog directly. Each is moved
# onto ``pipeline/backlog.py`` by a later task of spec 084 and DELETES ITS OWN
# ENTRY here when it lands (T004 harvest, T005 propose, T006 orchestrator
# quarantine sweep, T007 planner, T008 re-grade, T009 scaffold). The list must
# end empty; ``test_the_allowlist_has_no_stale_entries`` fails on a leftover.
_NOT_YET_MIGRATED: set[str] = set()
# These only *name* the path (a registry row, a control-file list, a manifest
# pattern); none opens it. Their wording changes are scaffold/layout work.
_NAMES_THE_PATH_ONLY = {
    "src/research_framework/pipeline/state_layout.py",
    "scripts/build_scaffold_manifest.py",
    # The state-paths guard (spec 083) names it in its exemption list.
    "scripts/guards/state_paths.py",
}
_VIEW_NAME = "research-backlog" + ".md"


def _files_naming_the_view() -> set[str]:
    found: set[str] = set()
    for base in ("src", "scripts"):
        for path in (ROOT / base).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if rel == "src/research_framework/pipeline/backlog.py":
                continue
            if _VIEW_NAME in path.read_text(encoding="utf-8"):
                found.add(rel)
    return found


def test_nothing_under_src_or_scripts_parses_the_view() -> None:
    unexpected = _files_naming_the_view() - _NOT_YET_MIGRATED - _NAMES_THE_PATH_ONLY
    assert not unexpected, (
        "only pipeline/backlog.py may read or write the backlog view; "
        f"found: {sorted(unexpected)}"
    )


def test_the_allowlist_has_no_stale_entries() -> None:
    stale = (_NOT_YET_MIGRATED | _NAMES_THE_PATH_ONLY) - _files_naming_the_view()
    assert not stale, f"remove migrated files from the allowlist: {sorted(stale)}"


def test_view_lists_notes_to_update(tmp_path: Path) -> None:
    """Spec 087 T003: a section after 'Follow-on topics', one line per note."""
    _seed(
        tmp_path,
        [
            _entry(
                "topic:late",
                "Late",
                "harvest",
                citation_count=1,
                cited_from=["a.md"],
                first_seen_cycle=1,
            ),
            _entry(
                "update:old-review",
                "old-review",
                "update",
                stem="old-review",
                reason="review_due",
                as_of="2025-01-01",
                prompted_by=[],
            ),
            _entry(
                "update:fresh",
                "fresh",
                "update",
                stem="fresh",
                reason="new_material",
                as_of="2026-02-02",
                prompted_by=["https://a.example", "https://b.example"],
            ),
            _entry(
                "update:unstamped",
                "unstamped",
                "update",
                stem="unstamped",
                reason="review_due",
            ),
            {
                **_entry(
                    "update:done", "done", "update", stem="done", reason="review_due"
                ),
                "status": "resolved",
                "status_written": "resolved",
            },
            _entry("topic:flagged", "Flagged", "researcher", detail="d"),
        ],
    )

    text = _render(tmp_path)

    assert text.index("## Follow-on topics") < text.index("## Notes to update")
    assert text.index("## Notes to update") < text.index("## Flagged by the researcher")
    section = text.split("## Notes to update\n\n")[1].split("\n\n")[0].splitlines()
    assert section == [
        "- **fresh** — new_material · as of 2026-02-02 · 2 prompting sources",
        "- **old-review** — review_due · as of 2025-01-01 · 0 prompting sources",
        "- **unstamped** — review_due · as of unknown · 0 prompting sources",
    ]
    assert "done" not in section
