"""Spec 084 T008 (converter half): legacy Markdown backlog to store entries."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest

from research_framework.pipeline import backlog, state_layout
from research_framework.pipeline.backlog_conversion import (
    ConversionResult,
    convert_legacy,
    write_converted,
)

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "backlog" / "legacy-shapes.md"
)
TODAY = "2026-11-23"


def _fixture_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _convert(text: str | None = None) -> ConversionResult:
    return convert_legacy(_fixture_text() if text is None else text, today=TODAY)


def _by_id(result: ConversionResult) -> dict[str, dict]:
    return {e["id"]: e for e in result.entries}


# -- Test 1 and Test 5 ----------------------------------------------------


def test_every_line_is_typed_carried_verbatim_or_counted_as_derived() -> None:
    text = _fixture_text()
    result = _convert(text)
    nonblank = [line for line in text.splitlines() if line.strip()]

    assert result.nonblank_lines == len(nonblank)
    assert result.accounted_lines == len(nonblank)
    # Carried verbatim: each migrated entry is one input line, in file order,
    # and no boilerplate or derived line leaked into them.
    migrated = [e["detail"] for e in result.entries if e["origin"] == "migrated"]
    assert result.migrated_lines == len(migrated)
    positions = [nonblank.index(line) for line in migrated]
    assert positions == sorted(positions)
    assert all(line in nonblank for line in migrated)
    assert [e["id"] for e in result.entries if e["origin"] == "migrated"] == [
        f"migrated:{n:04d}" for n in range(1, len(migrated) + 1)
    ]
    for line in migrated:
        assert not line.startswith("<!--")
        assert not re.match(r"- `[^`]+` \[", line)
        assert line != "Topics deferred from scout passes."
    # The hand-written and table shapes are carried, not typed.
    assert "- [[Sourdough Starter]]  *(cited by 24 note(s))*" in migrated
    assert "| Lamination | 2026-03-01 |" in migrated
    # Coverage-gap snapshot lines are counted, not carried.
    gaps = [line for line in nonblank if re.match(r"- `[^`]+` \[", line)]
    assert result.derived_lines_dropped == len(gaps) == 4


def test_info_line_counts_each_origin_and_the_derived_lines() -> None:
    result = _convert()
    assert result.entries_by_origin == {
        "harvest": 2,
        "researcher": 2,
        "proposal": 2,
        "quarantine": 2,
        "operator": 2,
        "migrated": 12,
    }
    line = result.info_line("_pipeline/state/research-backlog.pre-migration.md")
    for origin, count in result.entries_by_origin.items():
        assert f"{origin}={count}" in line
    assert "4 coverage-gap line(s) not carried" in line
    assert "_pipeline/state/research-backlog.pre-migration.md" in line


# -- Shapes ---------------------------------------------------------------


def test_a_wrapped_title_and_its_case_variant_are_one_entry() -> None:
    entries = _by_id(_convert())
    key = "topic:danish kaffemote coffee meeting networking norm"
    entry = entries[key]
    assert entry["title"] == "Danish Kaffemote Coffee Meeting Networking Norm"
    assert entry["origin"] == "harvest"
    assert (entry["first_seen_cycle"], entry["last_seen_cycle"]) == (1, 3)
    assert entry["seen_cycles"] == 2
    assert [e for e in entries.values() if "kaffemote" in e["title"].lower()] == [entry]


def test_a_title_wrapped_over_four_lines_is_not_joined() -> None:
    text = "- **One\ntwo\nthree\nfour\nfive** — cited by 2 note(s): `a`\n"
    result = _convert(text)
    assert result.entries_by_origin["migrated"] == 5
    assert result.accounted_lines == result.nonblank_lines == 5


def test_a_carried_over_orphan_is_one_entry_with_the_latest_citations() -> None:
    text = (
        "<!-- topic-harvest:cycle=001 -->\n"
        "- **Orphan** — cited by 2 note(s): `a.md`, `b.md`\n"
        "<!-- /topic-harvest:cycle=001 -->\n"
        "<!-- topic-harvest:cycle=003 -->\n"
        "- **Orphan** — cited by 5 note(s): `c.md` (+4 more)\n"
        "<!-- /topic-harvest:cycle=003 -->\n"
    )
    (entry,) = _convert(text).entries
    assert (entry["first_seen_cycle"], entry["last_seen_cycle"]) == (1, 3)
    assert entry["seen_cycles"] == 2
    assert (entry["citation_count"], entry["cited_from"]) == (5, ["c.md"])
    assert (entry["origin"], entry["status"], entry["status_by"]) == (
        "harvest",
        "open",
        "migration",
    )
    assert entry["status_written"] == "open"
    assert entry["added"] == entry["updated"] == TODAY


def test_an_operator_shaped_bullet_keeps_its_citations() -> None:
    entry = _by_id(_convert())["topic:sourdough discard recipes"]
    assert entry["origin"] == "operator"
    assert entry["citation_count"] == 4
    assert entry["cited_from"] == ["n/starter.md"]
    assert entry["first_seen_cycle"] is None
    assert entry["seen_cycles"] == 0


def test_an_operator_sighting_wins_the_origin_but_blocks_supply_the_cycles() -> None:
    entry = _by_id(_convert())["topic:tartine method"]
    assert entry["origin"] == "operator"
    assert entry["title"] == "tartine method"
    assert (entry["first_seen_cycle"], entry["last_seen_cycle"]) == (1, 3)
    assert entry["seen_cycles"] == 3
    assert entry["citation_count"] == 5  # the latest block, not the bare bullet's 7


def test_researcher_flags_and_proposals_are_typed() -> None:
    entries = _by_id(_convert())
    flag = entries["topic:dutch oven baking"]
    assert (flag["origin"], flag["seen_cycles"]) == ("researcher", 2)
    gas = entries["topic:gas oven"]
    assert (gas["origin"], gas["relation"], gas["parent_note"]) == (
        "proposal",
        "variant",
        "Oven",
    )
    assert gas["scope_warn"] is True
    assert gas["detail"].startswith("Recipes don't separate")
    assert entries["topic:steam injection"]["scope_warn"] is False


def test_a_proposal_shape_outside_a_propose_block_is_carried_verbatim() -> None:
    line = "- **Gas Oven** (variant of [[Oven]]) — a reason"
    (entry,) = _convert(line + "\n").entries
    assert (entry["origin"], entry["detail"]) == ("migrated", line)


def test_pointers_dedupe_by_stem_and_the_last_occurrence_wins() -> None:
    entries = _by_id(_convert())
    bad = entries["quarantine:bad-one"]
    assert (bad["kind"], bad["detail"]) == ("rewrite", "missing citation")
    flip = entries["quarantine:flip-note"]
    assert (flip["kind"], flip["detail"]) == ("retry", "fabricated claim")
    assert [e["stem"] for e in entries.values() if e["origin"] == "quarantine"] == [
        "bad-one",
        "flip-note",
    ]
    # Reverse the order: the later (retry) line now loses to a later rewrite.
    text = (
        "- [ ] retry refresh of x — previous content restored, rejected draft "
        "quarantined (verifier_status: rejected — first)\n"
        "- [ ] rewrite quarantined note: x (verifier_status: rejected — second)\n"
    )
    (only,) = _convert(text).entries
    assert (only["kind"], only["detail"]) == ("rewrite", "second")


def test_a_pointer_without_the_stem_tag_uses_the_stem_in_the_text() -> None:
    text = "- [ ] rewrite quarantined note: old-note (verifier_status: rejected — why (really))\n"
    (entry,) = _convert(text).entries
    assert (entry["id"], entry["stem"], entry["detail"]) == (
        "quarantine:old-note",
        "old-note",
        "why (really)",
    )


# -- The store the converter produces ------------------------------------


def test_the_entries_pass_the_modules_own_validation() -> None:
    result = _convert()
    data = {"schema_version": backlog.SCHEMA_VERSION, "entries": result.entries}
    assert backlog._validate_store(data) == (None, False)
    # JSON-serialisable and free of scratch keys.
    assert not any(k.startswith("_") for e in result.entries for k in e)
    json.dumps(data)


_OLD_PLANNER_RE = re.compile(
    r"^\s*-\s+\*\*([^*]+)\*\*\s+—\s+cited by\s+(\d+)\s+note", re.MULTILINE
)


def _install(tmp_path: Path) -> tuple[Path, bytes, ConversionResult]:
    vault = tmp_path / "vault"
    original = FIXTURE.read_bytes()
    view = backlog.view_path(vault)
    view.parent.mkdir(parents=True)
    view.write_bytes(original)
    result = _convert()
    assert backlog.is_unconverted(vault)
    assert write_converted(vault, result, original=original) is True
    return vault, original, result


def test_the_planner_queues_what_the_old_planner_would_have_queued(
    tmp_path: Path,
) -> None:
    old = {
        " ".join(m.group(1).split()).casefold()
        for m in _OLD_PLANNER_RE.finditer(_fixture_text())
        if int(m.group(2)) >= 1
    }
    vault, _, _ = _install(tmp_path)
    queued = {t.key: t for t in backlog.planner_topics(vault)}
    assert set(queued) == old
    assert queued["tartine method"].citation_count == 5  # latest, not the oldest (F9)
    assert queued["danish kaffemote coffee meeting networking norm"].citation_count == 3


# -- Test 2 (archive half) ------------------------------------------------


def test_the_archive_is_byte_equal_and_a_second_run_is_a_no_op(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    vault = tmp_path / "vault"
    original = FIXTURE.read_bytes()
    view = backlog.view_path(vault)
    view.parent.mkdir(parents=True)
    view.write_bytes(original)
    with caplog.at_level(logging.INFO):
        assert write_converted(vault, _convert(), original=original) is True
    archive = state_layout.research_backlog_archive_path(vault)
    assert archive.read_bytes() == original
    assert "research backlog converted" in caplog.text
    assert "legacy backlog" not in caplog.text and "overwritten" not in caplog.text
    # The legacy file is now the rendered view; no hand-edit copy was made.
    assert backlog.view_path(vault).read_bytes() != original
    assert "Generated from" in backlog.view_path(vault).read_text(encoding="utf-8")
    assert not backlog.overwritten_path(vault).exists()
    assert not backlog.is_unconverted(vault)
    store_before = state_layout.research_backlog_path(vault).read_bytes()

    assert write_converted(vault, _convert(), original=original) is False
    assert state_layout.research_backlog_path(vault).read_bytes() == store_before
    assert archive.read_bytes() == original
    # Writers work on the converted vault again.
    assert backlog.update(vault, "harvest", lambda tx: None) is True


def test_install_refuses_without_a_byte_equal_archive(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    view = backlog.view_path(vault)
    view.parent.mkdir(parents=True)
    view.write_text("legacy\n", encoding="utf-8")
    archive = state_layout.research_backlog_archive_path(vault)
    with pytest.raises(ValueError):
        backlog.install_store(vault, [], archive=archive)
    archive.parent.mkdir(parents=True)
    archive.write_text("different\n", encoding="utf-8")
    with pytest.raises(ValueError):
        backlog.install_store(vault, [], archive=archive)
    assert not state_layout.research_backlog_path(vault).exists()
    assert view.read_text(encoding="utf-8") == "legacy\n"


def test_a_vault_with_no_legacy_file_is_converted_from_nothing(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    result = convert_legacy("", today=TODAY)
    assert write_converted(vault, result, original=b"") is True
    assert backlog.planner_topics(vault) == []
