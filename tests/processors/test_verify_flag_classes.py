"""Not every structural flag is the vault's fault (issues #225, #227).

``verify()`` counted every ``structural_flag`` equally: ``structural_flags /
notes_checked > fail_threshold`` was the whole FAIL rule, and an **orphan** —
a note with zero incoming wikilinks — weighed exactly as much as a note whose
frontmatter will not parse.  A young or lightly-linked vault therefore failed
verify by construction, which is the most plausible generalised cause of the
2026-09-01 incident in which seven of eight live vaults failed at once.

Two separate defects produced that:

* **#225** — no severity or class term in the verdict.  A measurement on a
  committed fixture: ``tests/fixtures/quality/tech-lite`` scored 18 notes /
  32 flags, of which 14 were orphans, and 32/18 > 0.20 → FAIL.
* **#227** — verify ignored the exemptions and aliases the vault format
  already defines (``verifier_status: exempt``, the ``note_type: alias``
  redirect stubs ``pipeline.wikilinks`` writes) and compared wikilinks
  case-sensitively, against ADR-0005, which decided that ``[[Cassandra]]``
  and ``cassandra.md`` are the same node.  Every one of those became a flag,
  and every flag fed the FAIL ratio.

The rule these pin: a **content** flag is the vault author's problem and
drives the verdict; a **tooling** flag is the framework's own graph
bookkeeping — reported, never fatal.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.processors.verify import verify

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _note(vault: Path, rel: str, text: str) -> Path:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _clean_note(vault: Path, rel: str, body: str = "Body.") -> Path:
    """A note that satisfies every per-note check — so only graph-shaped
    checks (orphan, moc_gap) can flag it."""
    return _note(
        vault,
        rel,
        "---\nstatus: evergreen\nrelated: []\nsummary: A note.\n---\n\n" + body + "\n",
    )


def _checks(result, check: str) -> list[dict]:
    return [r for r in result.report["results"] if r.get("check") == check]


# ---------------------------------------------------------------------------
# #225 — orphans alone must not fail a vault
# ---------------------------------------------------------------------------


class TestOrphansDoNotFailAVault:
    def _lonely_vault(self, tmp_path: Path, count: int = 10) -> None:
        for i in range(count):
            _clean_note(tmp_path, f"04 - Concepts/Lonely{i}.md")

    def test_orphans_alone_do_not_fail(self, tmp_path: Path) -> None:
        """10 notes, 10 orphans, ratio 1.0 — five times the threshold."""
        self._lonely_vault(tmp_path)

        result = verify(tmp_path, auto_fix=False)

        assert len(_checks(result, "orphan")) == 10
        assert result.verdict != "FAIL"

    def test_orphans_alone_warn(self, tmp_path: Path) -> None:
        """Not fatal is not the same as invisible."""
        self._lonely_vault(tmp_path)

        assert verify(tmp_path, auto_fix=False).verdict == "WARN"

    def test_a_content_flag_still_fails(self, tmp_path: Path) -> None:
        """The weighting must not make verify unable to fail anything."""
        for i in range(10):
            _note(tmp_path, f"04 - Concepts/Bare{i}.md", "Just a body.\n")

        assert verify(tmp_path, auto_fix=False).verdict == "FAIL"

    def test_missing_status_and_related_are_not_content(self, tmp_path: Path) -> None:
        """Anything verify can fix by itself is not the author's failure."""
        for i in range(10):
            _note(
                tmp_path,
                f"04 - Concepts/N{i}.md",
                f"---\nsummary: Note {i}.\n---\n\nSee [[N{(i + 1) % 10}]].\n",
            )

        result = verify(tmp_path, auto_fix=False)

        assert len(_checks(result, "missing_status")) == 10
        assert len(_checks(result, "missing_related")) == 10
        assert result.content_flags == 0
        assert result.verdict != "FAIL"


class TestFlagClassesAreOnTheResult:
    def test_the_two_classes_partition_the_flags(self, tmp_path: Path) -> None:
        _note(tmp_path, "04 - Concepts/Bare.md", "Body with [[Nowhere]].\n")
        _clean_note(tmp_path, "04 - Concepts/Lonely.md")

        result = verify(tmp_path, auto_fix=False)

        assert result.content_flags + result.tooling_flags == result.structural_flags
        assert result.content_flags > 0
        assert result.tooling_flags > 0

    def test_every_flag_carries_its_class(self, tmp_path: Path) -> None:
        _note(tmp_path, "04 - Concepts/Bare.md", "Body with [[Nowhere]].\n")

        result = verify(tmp_path, auto_fix=False)
        flags = [r for r in result.report["results"] if r["type"] == "structural_flag"]

        assert flags
        assert {r.get("class") for r in flags} <= {"content", "tooling"}
        assert all(r.get("class") for r in flags)

    def test_the_report_carries_both_counts(self, tmp_path: Path) -> None:
        _note(tmp_path, "04 - Concepts/Bare.md", "Body.\n")

        report = verify(tmp_path, auto_fix=False).report

        assert (
            report["content_flags"] + report["tooling_flags"]
            == (report["structural_flags"])
        )

    def test_template_artifact_links_are_tooling(self, tmp_path: Path) -> None:
        """``[[Note Name]]`` is template residue, not a claim about the world."""
        _clean_note(tmp_path, "04 - Concepts/A.md", body="Residue: [[Note Name]].")

        result = verify(tmp_path, auto_fix=False)

        broken = _checks(result, "broken_wikilink")
        assert broken and all(r["class"] == "tooling" for r in broken)

    def test_a_real_broken_link_is_content(self, tmp_path: Path) -> None:
        _clean_note(tmp_path, "04 - Concepts/A.md", body="See [[Nowhere At All]].")

        result = verify(tmp_path, auto_fix=False)

        broken = _checks(result, "broken_wikilink")
        assert broken and all(r["class"] == "content" for r in broken)


class TestTheReasonNamesWhatCounted:
    def test_the_threshold_sentence_is_about_content_flags(
        self, tmp_path: Path
    ) -> None:
        for i in range(6):
            _note(tmp_path, f"04 - Concepts/Bare{i}.md", "Just a body.\n")

        result = verify(tmp_path, auto_fix=False)
        joined = "\n".join(result.errors)

        assert result.verdict == "FAIL"
        assert "content flag" in joined
        assert str(result.content_flags) in joined
        # The operator still needs to know how much noise was set aside.
        assert str(result.tooling_flags) in joined
        assert "tooling" in joined


# ---------------------------------------------------------------------------
# #227 — exemptions, alias stubs, wikilink case
# ---------------------------------------------------------------------------

EXEMPT_NOTE = """---
title: Exempt
verifier_status: exempt
---

Deliberately outside the grader.
"""

ALIAS_STUB = """---
title: OMS
note_type: alias
redirect_to: case-based-reasoning
---

See [[case-based-reasoning]].
"""


class TestExemptNotesAreHonoured:
    def test_an_exempt_note_is_counted_but_never_flagged(self, tmp_path: Path) -> None:
        _note(tmp_path, "04 - Concepts/Exempt.md", EXEMPT_NOTE)

        result = verify(tmp_path, auto_fix=False)

        assert result.notes_checked == 1
        assert result.structural_flags == 0
        assert result.verdict == "PASS"

    def test_an_exempt_note_is_never_auto_fixed(self, tmp_path: Path) -> None:
        note = _note(tmp_path, "04 - Concepts/Exempt.md", EXEMPT_NOTE)

        result = verify(tmp_path, auto_fix=True)

        assert result.auto_fixes_applied == 0
        assert note.read_text(encoding="utf-8") == EXEMPT_NOTE

    def test_an_exempt_note_is_still_a_link_source(self, tmp_path: Path) -> None:
        """Exempting a note from grading must not orphan what it links to."""
        _note(
            tmp_path,
            "04 - Concepts/Exempt.md",
            EXEMPT_NOTE.replace("Deliberately", "See [[Target]]. Deliberately"),
        )
        _clean_note(tmp_path, "04 - Concepts/Target.md")

        result = verify(tmp_path, auto_fix=False)

        assert not _checks(result, "orphan")


class TestAliasStubsAreNotOrphans:
    def test_the_stub_itself_is_not_flagged(self, tmp_path: Path) -> None:
        _note(tmp_path, "04 - Concepts/oms.md", ALIAS_STUB)
        _clean_note(tmp_path, "04 - Concepts/case-based-reasoning.md")

        result = verify(tmp_path, auto_fix=False)

        assert not _checks(result, "orphan")
        assert result.structural_flags == 0

    def test_the_stub_redirect_target_resolves(self, tmp_path: Path) -> None:
        _note(tmp_path, "04 - Concepts/oms.md", ALIAS_STUB)
        _clean_note(tmp_path, "04 - Concepts/case-based-reasoning.md")

        result = verify(tmp_path, auto_fix=False)

        assert not _checks(result, "broken_wikilink")


class TestWikilinkCaseIsFolded:
    """ADR-0005 decided ``[[Cassandra]]`` and ``cassandra.md`` are one node."""

    def _case_split_vault(self, tmp_path: Path) -> None:
        _clean_note(tmp_path, "04 - Concepts/cassandra.md", body="A store.")
        _clean_note(
            tmp_path, "04 - Concepts/wide-columns.md", body="Built on [[Cassandra]]."
        )

    def test_a_case_variant_link_is_not_broken(self, tmp_path: Path) -> None:
        self._case_split_vault(tmp_path)

        assert not _checks(verify(tmp_path, auto_fix=False), "broken_wikilink")

    def test_a_case_variant_link_defeats_the_orphan_check(self, tmp_path: Path) -> None:
        self._case_split_vault(tmp_path)

        orphans = [
            r["file"] for r in _checks(verify(tmp_path, auto_fix=False), "orphan")
        ]

        assert not any("cassandra" in o for o in orphans)
