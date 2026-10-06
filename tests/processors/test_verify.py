"""Tests for research_framework.processors.verify."""

from __future__ import annotations

from pathlib import Path

from research_framework.processors.verify import VerifyResult, verify
from research_framework.vault.frontmatter import parse_frontmatter_str

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_note(
    vault: Path,
    rel_path: str,
    body: str = "Note body.",
    frontmatter: dict | None = None,
) -> Path:
    path = vault / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = frontmatter or {}
    fm_lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            if not v:
                fm_lines.append(f"{k}: []")
            else:
                fm_lines.append(f"{k}:")
                for item in v:
                    fm_lines.append(f"  - {item}")
        else:
            fm_lines.append(f"{k}: {v}")
    fm_lines.append("---")
    text = "\n".join(fm_lines) + "\n\n" + body
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestVerifyFunction:
    def test_empty_vault_passes(self, tmp_path):
        result = verify(tmp_path, auto_fix=False)
        assert isinstance(result, VerifyResult)
        assert result.verdict == "PASS"
        assert result.notes_checked == 0

    def test_passes_clean_vault(self, tmp_path):
        # Two notes linking each other — no orphans, no broken links, no missing fields.
        make_note(
            tmp_path,
            "04 - Concepts/NoteA.md",
            frontmatter={"status": "evergreen", "related": [], "summary": "Note A."},
            body="See [[NoteB]] for more.",
        )
        make_note(
            tmp_path,
            "04 - Concepts/NoteB.md",
            frontmatter={"status": "evergreen", "related": [], "summary": "Note B."},
            body="See [[NoteA]] for more.",
        )
        result = verify(tmp_path, auto_fix=False)
        assert result.malformed_count == 0
        # With 2 notes and only missing_summary flags (which we provided), should PASS or WARN.
        assert result.verdict in ("PASS", "WARN")

    def test_flags_missing_status(self, tmp_path):
        make_note(
            tmp_path,
            "04 - Concepts/No Status.md",
            frontmatter={"related": [], "summary": "No status field."},
        )
        result = verify(tmp_path, auto_fix=False)
        checks = [r["check"] for r in result.report["results"]]
        assert "missing_status" in checks

    def test_auto_fix_adds_status(self, tmp_path):
        note = make_note(
            tmp_path,
            "04 - Concepts/No Status.md",
            frontmatter={"related": [], "summary": "No status."},
        )
        result = verify(tmp_path, auto_fix=True)
        assert result.auto_fixes_applied >= 1
        # Re-parse the file rather than trusting the counter — the counter was
        # incremented even when the write mangled the note.
        fm, _ = parse_frontmatter_str(note.read_text(encoding="utf-8"))
        assert fm["status"] == "draft"
        assert fm["summary"] == "No status."
        assert fm["related"] == []

    def test_flags_missing_related(self, tmp_path):
        make_note(
            tmp_path,
            "04 - Concepts/No Related.md",
            frontmatter={"status": "draft", "summary": "No related field."},
        )
        result = verify(tmp_path, auto_fix=False)
        checks = [r["check"] for r in result.report["results"]]
        assert "missing_related" in checks

    def test_flags_broken_wikilink(self, tmp_path):
        make_note(
            tmp_path,
            "04 - Concepts/Linker.md",
            frontmatter={
                "status": "draft",
                "related": [],
                "summary": "Links to nonexistent.",
            },
            body="See [[NonExistentNote]] for details.",
        )
        result = verify(tmp_path, auto_fix=False)
        checks = [r["check"] for r in result.report["results"]]
        assert "broken_wikilink" in checks

    def test_clean_note_no_broken_wikilinks(self, tmp_path):
        make_note(
            tmp_path,
            "04 - Concepts/NoteA.md",
            frontmatter={"status": "draft", "related": [], "summary": "Note A."},
            body="Self-contained note.",
        )
        make_note(
            tmp_path,
            "04 - Concepts/NoteB.md",
            frontmatter={"status": "draft", "related": [], "summary": "Links to A."},
            body="See [[NoteA]] for details.",
        )
        result = verify(tmp_path, auto_fix=False)
        broken = [
            r for r in result.report["results"] if r["check"] == "broken_wikilink"
        ]
        assert not broken

    def test_repeated_broken_link_in_one_note_is_one_flag_not_one_per_mention(
        self, tmp_path
    ):
        """Issue #287: `[[NonExistentNote]]` mentioned four times in a single
        note used to emit four `broken_wikilink` flags — one per raw
        occurrence — inflating `structural_flags` for one author habit, not
        four corroborating notes."""
        make_note(
            tmp_path,
            "04 - Concepts/Linker.md",
            frontmatter={"status": "draft", "related": [], "summary": "Links."},
            body=(
                "See [[NonExistentNote]] and again [[NonExistentNote]], plus "
                "[[NonExistentNote]] and once more [[NonExistentNote]]."
            ),
        )
        result = verify(tmp_path, auto_fix=False)
        broken = [
            r for r in result.report["results"] if r["check"] == "broken_wikilink"
        ]
        assert len(broken) == 1

    def test_repeated_broken_link_from_one_note_is_low_severity(self, tmp_path):
        """One citing note mentioning the same broken target four times must
        not read as "4 distinct notes cite this" (severity `critical`,
        `ref_count >= 4`) — it is one note, severity `low`."""
        make_note(
            tmp_path,
            "04 - Concepts/Linker.md",
            frontmatter={"status": "draft", "related": [], "summary": "Links."},
            body=(
                "[[NonExistentNote]] [[NonExistentNote]] [[NonExistentNote]] "
                "[[NonExistentNote]]"
            ),
        )
        result = verify(tmp_path, auto_fix=False)
        (broken,) = [
            r for r in result.report["results"] if r["check"] == "broken_wikilink"
        ]
        assert broken["severity"] == "low"

    def test_broken_link_severity_scales_with_distinct_citing_notes(self, tmp_path):
        """Four DIFFERENT notes each citing the same broken target once is
        the real `critical` case — distinct corroborating notes, not raw
        mention count."""
        for i in range(4):
            make_note(
                tmp_path,
                f"04 - Concepts/Citer{i}.md",
                frontmatter={"status": "draft", "related": [], "summary": "Links."},
                body="See [[NonExistentNote]].",
            )
        result = verify(tmp_path, auto_fix=False)
        broken = [
            r for r in result.report["results"] if r["check"] == "broken_wikilink"
        ]
        assert len(broken) == 4
        assert all(r["severity"] == "critical" for r in broken)

    def test_hub_notes_counts_distinct_citing_notes_not_mentions(self, tmp_path):
        """A single note linking to a target three times must not make that
        target a "hub" (`hub_notes`, threshold `count >= 3`) — three mentions
        from one note is not three notes converging on it."""
        make_note(
            tmp_path,
            "04 - Concepts/Target.md",
            frontmatter={"status": "draft", "related": [], "summary": "Target."},
            body="Target note.",
        )
        make_note(
            tmp_path,
            "04 - Concepts/Citer.md",
            frontmatter={"status": "draft", "related": [], "summary": "Cites."},
            body="[[Target]] [[Target]] [[Target]]",
        )
        result = verify(tmp_path, auto_fix=False)
        assert "Target" not in result.report["hub_notes"]

    def test_hub_notes_fires_for_three_distinct_citing_notes(self, tmp_path):
        make_note(
            tmp_path,
            "04 - Concepts/Target.md",
            frontmatter={"status": "draft", "related": [], "summary": "Target."},
            body="Target note.",
        )
        for i in range(3):
            make_note(
                tmp_path,
                f"04 - Concepts/Citer{i}.md",
                frontmatter={"status": "draft", "related": [], "summary": "Cites."},
                body="See [[Target]].",
            )
        result = verify(tmp_path, auto_fix=False)
        assert result.report["hub_notes"].get("Target") == 3

    def test_flags_orphan_note(self, tmp_path):
        make_note(
            tmp_path,
            "04 - Concepts/Orphan.md",
            frontmatter={
                "status": "draft",
                "related": [],
                "summary": "Nobody links here.",
            },
            body="Lonely note.",
        )
        result = verify(tmp_path, auto_fix=False)
        checks = [r["check"] for r in result.report["results"]]
        assert "orphan" in checks

    def test_fail_threshold_respected(self, tmp_path):
        """Many flagged notes relative to total should trigger FAIL verdict."""
        # Create notes missing many required fields — lots of flags.
        for i in range(10):
            make_note(
                tmp_path,
                f"04 - Concepts/Note{i}.md",
                frontmatter={},  # Missing status, related, summary
                body=f"Note {i} body.",
            )
        # Very low threshold — should FAIL.
        result = verify(tmp_path, auto_fix=False, fail_threshold=0.01)
        assert result.verdict == "FAIL"

    def test_pipeline_dir_excluded(self, tmp_path):
        """Notes under _pipeline/ are excluded from checks."""
        pipeline_note = tmp_path / "_pipeline" / "raw" / "web" / "item.md"
        pipeline_note.parent.mkdir(parents=True, exist_ok=True)
        pipeline_note.write_text(
            "---\ntitle: Pipeline note\n---\nBody.", encoding="utf-8"
        )
        result = verify(tmp_path, auto_fix=False)
        assert result.notes_checked == 0

    def test_verdict_in_result(self, tmp_path):
        result = verify(tmp_path, auto_fix=False)
        assert result.verdict in ("PASS", "WARN", "FAIL")

    def test_report_structure(self, tmp_path):
        result = verify(tmp_path, auto_fix=False)
        report = result.report
        assert "timestamp" in report
        assert "notes_checked" in report
        assert "verdict" in report
        assert "results" in report
        assert isinstance(report["results"], list)


# ---------------------------------------------------------------------------
# Auto-fix must not destroy frontmatter (regression)
# ---------------------------------------------------------------------------

RICH_NOTE = """---
title: "Retrieval: Augmented Generation"
note_type: concept
summary: A concept note.
tags: [rag, retrieval]
owns:
  - embeddings
  - chunking
reads:
  - vector-db
related:
  - "[[Vector Databases]]"
source_urls:
  - https://example.invalid/rag
provenance:
  - source: synthetic
    context: harvested during cycle 1
    title: Nested Title That Must Not Escape
---

Body referencing [[Vector Databases]].
"""


class TestAutoFixPreservesFrontmatter:
    """Regression: auto-fix used to read notes with ``_common``'s line-scalar
    parser — a parser whose own comment scopes it to ``_pipeline`` raw items —
    and write them back with a hand-rolled emitter.  Against a real note that
    emptied every list field, unquoted quoted scalars, hoisted a nested key to
    top level, turned ``tags: [a, b]`` into the string ``"[a, b]"`` and let a
    nested ``title:`` overwrite the note's real title.
    """

    def _fix_one(self, tmp_path: Path) -> tuple[Path, dict, str]:
        note = tmp_path / "04 - Concepts" / "Rich Note.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(RICH_NOTE, encoding="utf-8")
        before_fm, before_body = parse_frontmatter_str(RICH_NOTE)

        result = verify(tmp_path, auto_fix=True)
        assert result.auto_fixes_applied == 1  # only `status` was missing

        after_fm, after_body = parse_frontmatter_str(note.read_text(encoding="utf-8"))
        assert before_body == after_body  # body is byte-identical
        return note, before_fm, after_body

    def test_only_the_deliberate_key_is_added(self, tmp_path: Path) -> None:
        note, before_fm, _ = self._fix_one(tmp_path)
        after_fm, _ = parse_frontmatter_str(note.read_text(encoding="utf-8"))
        assert after_fm == {**before_fm, "status": "draft"}

    def test_list_fields_survive(self, tmp_path: Path) -> None:
        note, _, _ = self._fix_one(tmp_path)
        fm, _ = parse_frontmatter_str(note.read_text(encoding="utf-8"))
        assert fm["owns"] == ["embeddings", "chunking"]
        assert fm["reads"] == ["vector-db"]
        assert fm["related"] == ["[[Vector Databases]]"]
        assert fm["source_urls"] == ["https://example.invalid/rag"]
        assert fm["tags"] == ["rag", "retrieval"]  # not the string "[rag, retrieval]"

    def test_nested_mapping_is_not_hoisted(self, tmp_path: Path) -> None:
        note, _, _ = self._fix_one(tmp_path)
        fm, _ = parse_frontmatter_str(note.read_text(encoding="utf-8"))
        assert fm["provenance"] == [
            {
                "source": "synthetic",
                "context": "harvested during cycle 1",
                "title": "Nested Title That Must Not Escape",
            }
        ]
        assert "context" not in fm  # was hoisted to top level

    def test_nested_title_does_not_overwrite_the_real_one(self, tmp_path: Path) -> None:
        note, _, _ = self._fix_one(tmp_path)
        fm, _ = parse_frontmatter_str(note.read_text(encoding="utf-8"))
        assert fm["title"] == "Retrieval: Augmented Generation"

    def test_fixing_is_idempotent(self, tmp_path: Path) -> None:
        note, _, _ = self._fix_one(tmp_path)
        first = note.read_text(encoding="utf-8")
        verify(tmp_path, auto_fix=True)
        assert note.read_text(encoding="utf-8") == first

    def test_lines_the_fix_does_not_touch_are_kept_as_written(
        self, tmp_path: Path
    ) -> None:
        """Adding a key must not re-emit the rest of the frontmatter.

        The fix loaded the block and dumped it again, and a YAML round trip is
        not the identity: the comments went, ``0123`` came back as ``83``,
        ``no`` as ``false``, ``1.10`` as ``1.1`` and ``1:30`` as ``90``.
        """
        note = tmp_path / "04 - Concepts" / "Typed.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        frontmatter = (
            "---\n"
            "# reviewed by hand, do not reorder\n"
            'title: "Zip Codes: A Primer"\n'
            "summary: A concept note.\n"
            "zip: 0123  # the leading zero matters\n"
            "public: no\n"
            "version: 1.10\n"
            "duration: 1:30\n"
            "tags: [rag, retrieval]\n"
            "source_urls:\n"
            "  - https://example.invalid/zip\n"
        )
        note.write_text(frontmatter + "---\n\nBody.\n", encoding="utf-8")

        result = verify(tmp_path, auto_fix=True)

        assert result.auto_fixes_applied == 2  # `related` and `status`
        assert note.read_text(encoding="utf-8") == (
            frontmatter + "related: []\nstatus: draft\n---\n\nBody.\n"
        )

    def test_a_flow_style_block_still_gets_its_key(self, tmp_path: Path) -> None:
        """A line cannot be appended to a ``{...}`` mapping: re-emit it instead."""
        note = tmp_path / "04 - Concepts" / "Flow.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(
            "---\n{title: Flow, summary: s, related: []}\n---\n\nBody.\n",
            encoding="utf-8",
        )

        result = verify(tmp_path, auto_fix=True)

        assert result.auto_fixes_applied == 1
        fm, body = parse_frontmatter_str(note.read_text(encoding="utf-8"))
        assert fm == {"title": "Flow", "summary": "s", "related": [], "status": "draft"}
        assert body == "\nBody.\n"

    def test_malformed_yaml_is_flagged_not_rewritten(self, tmp_path: Path) -> None:
        note = tmp_path / "04 - Concepts" / "Broken.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        original = "---\ntitle: [unclosed\n---\n\nBody.\n"
        note.write_text(original, encoding="utf-8")

        result = verify(tmp_path, auto_fix=True)

        assert result.malformed_count == 1
        assert result.verdict == "FAIL"
        assert note.read_text(encoding="utf-8") == original

    def test_bom_note_gets_the_key_inside_its_own_frontmatter(
        self, tmp_path: Path
    ) -> None:
        """A UTF-8 BOM hid the frontmatter from ``_load_note``, so auto-fix
        prepended a second ``---`` block above the real one, pushing title and
        summary into the body where no parser sees them."""
        note = tmp_path / "04 - Concepts" / "Bom.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_bytes(
            b"\xef\xbb\xbf---\ntitle: Bom\nstatus: draft\nsummary: s\n---\n\nBody.\n"
        )

        verify(tmp_path, auto_fix=True)

        fm, body = parse_frontmatter_str(note.read_text(encoding="utf-8-sig"))
        assert fm == {"title": "Bom", "status": "draft", "summary": "s", "related": []}
        assert body == "\nBody.\n"

    def test_non_utf8_note_is_flagged_not_rewritten(self, tmp_path: Path) -> None:
        """``errors="replace"`` turned Latin-1 bytes into U+FFFD, and auto-fix
        then wrote the replacement characters back over the original."""
        note = tmp_path / "04 - Concepts" / "Latin.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        original = "---\ntitle: Caf\u00e9\n---\n\nNa\u00efve body.\n".encode("latin-1")
        note.write_bytes(original)

        result = verify(tmp_path, auto_fix=True)

        assert note.read_bytes() == original
        assert result.malformed_count == 1


# ---------------------------------------------------------------------------
# The walk must cover the corpus only (regression)
# ---------------------------------------------------------------------------


class TestWalkScope:
    """Regression: ``EXCLUDE_DIRS`` excluded only ``_pipeline``,
    ``_templates`` and ``.obsidian``, so ``.claude/commands/*.md``,
    ``CLAUDE.md``, ``README.md``, ``*.spec.md`` and ``.venv/**`` READMEs were
    walked as notes, mutated, and their flags pushed the flag/notes ratio past
    ``fail_threshold`` — the FAIL that hit 7 of 7 real vaults on 2026-09-01.
    """

    NON_NOTES = {
        ".claude/commands/ask.md": "---\ndescription: Ask\n---\n\nAsk it.\n",
        ".venv/lib/python3.12/site-packages/pkg/README.md": "# vendored\n",
        ".obsidian/plugins/x/README.md": "# plugin\n",
        "CLAUDE.md": "# agent context\n",
        "README.md": "# the vault\n",
        "AGENTS.md": "# agents\n",
        "CONTRIBUTING.md": "# contributing\n",
        "research.spec.md": "---\nname: v\n---\n\n# Spec\n",
        "scripts/README.md": "# scripts\n",
        "node_modules/dep/README.md": "# dep\n",
        "_templates/concept.md": "---\ntitle: T\n---\n\nTemplate.\n",
        "_pipeline/raw/web/item.md": "---\ntitle: raw\n---\n\nRaw.\n",
    }

    def _seed(self, tmp_path: Path) -> dict[str, str]:
        for rel, text in self.NON_NOTES.items():
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return dict(self.NON_NOTES)

    def test_non_notes_are_not_counted(self, tmp_path: Path) -> None:
        self._seed(tmp_path)
        make_note(
            tmp_path,
            "04 - Concepts/Real.md",
            frontmatter={"status": "draft", "related": [], "summary": "Real."},
        )
        result = verify(tmp_path, auto_fix=False)
        assert result.notes_checked == 1

    def test_non_notes_are_never_mutated(self, tmp_path: Path) -> None:
        seeded = self._seed(tmp_path)
        make_note(
            tmp_path,
            "04 - Concepts/Real.md",
            frontmatter={"status": "draft", "related": [], "summary": "Real."},
        )
        verify(tmp_path, auto_fix=True)
        for rel, text in seeded.items():
            assert (tmp_path / rel).read_text(encoding="utf-8") == text, rel

    def test_non_notes_do_not_drive_the_verdict(self, tmp_path: Path) -> None:
        """A vault of one clean note plus tooling must not FAIL."""
        self._seed(tmp_path)
        make_note(
            tmp_path,
            "04 - Concepts/Real.md",
            frontmatter={"status": "draft", "related": [], "summary": "Real."},
            body="Links [[Other]].",
        )
        make_note(
            tmp_path,
            "04 - Concepts/Other.md",
            frontmatter={"status": "draft", "related": [], "summary": "Other."},
            body="Links [[Real]].",
        )
        result = verify(tmp_path, auto_fix=False)
        assert result.verdict == "PASS"


# ---------------------------------------------------------------------------
# Option precedence: explicit arg > spec config > default (regression)
# ---------------------------------------------------------------------------


class TestOptionPrecedence:
    """Regression: ``cfg.get(key, param)`` always found the key in
    ``PROCESSOR_DEFAULTS``, so both parameters were dead and the CLI's
    ``--no-fix`` / ``--fail-threshold`` did nothing.
    """

    def _note_missing_status(self, tmp_path: Path) -> Path:
        return make_note(
            tmp_path,
            "04 - Concepts/No Status.md",
            frontmatter={"related": [], "summary": "No status."},
        )

    def test_explicit_no_fix_beats_the_default(self, tmp_path: Path) -> None:
        note = self._note_missing_status(tmp_path)
        before = note.read_text(encoding="utf-8")
        result = verify(tmp_path, auto_fix=False)
        assert result.auto_fixes_applied == 0
        assert note.read_text(encoding="utf-8") == before

    def test_explicit_no_fix_beats_spec_config(self, tmp_path: Path) -> None:
        note = self._note_missing_status(tmp_path)
        before = note.read_text(encoding="utf-8")
        result = verify(
            tmp_path,
            auto_fix=False,
            spec_processors={"verify": {"auto_fix": True}},
        )
        assert result.auto_fixes_applied == 0
        assert note.read_text(encoding="utf-8") == before

    def test_spec_config_applies_when_no_explicit_arg(self, tmp_path: Path) -> None:
        note = self._note_missing_status(tmp_path)
        before = note.read_text(encoding="utf-8")
        result = verify(tmp_path, spec_processors={"verify": {"auto_fix": False}})
        assert result.auto_fixes_applied == 0
        assert note.read_text(encoding="utf-8") == before

    def test_default_still_fixes_when_nothing_is_specified(
        self, tmp_path: Path
    ) -> None:
        self._note_missing_status(tmp_path)
        assert verify(tmp_path).auto_fixes_applied == 1

    def test_explicit_fail_threshold_beats_spec_config(self, tmp_path: Path) -> None:
        for i in range(10):
            make_note(tmp_path, f"04 - Concepts/N{i}.md", frontmatter={})
        lenient = verify(
            tmp_path,
            auto_fix=False,
            fail_threshold=100.0,
            spec_processors={"verify": {"fail_threshold": 0.01}},
        )
        strict = verify(
            tmp_path,
            auto_fix=False,
            fail_threshold=0.01,
            spec_processors={"verify": {"fail_threshold": 100.0}},
        )
        assert lenient.verdict != "FAIL"
        assert strict.verdict == "FAIL"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_no_fix_flag_leaves_notes_untouched(self, tmp_path: Path) -> None:
        from research_framework.processors.verify import _cli_main

        note = make_note(
            tmp_path,
            "04 - Concepts/No Status.md",
            frontmatter={"related": [], "summary": "No status."},
        )
        before = note.read_text(encoding="utf-8")
        _cli_main([str(tmp_path), "--no-fix"])
        assert note.read_text(encoding="utf-8") == before
