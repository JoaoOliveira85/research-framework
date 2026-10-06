"""A verify FAIL must carry its own reason (issue #218).

``verify()`` computed a verdict from ``malformed_count`` / ``structural_flags``
and never appended a single string to the ``errors`` list it declared, so
``VerifyResult.errors`` was ``()`` for every FAIL the framework has ever
produced.  On 2026-09-01 seven of eight real vaults failed verify and the
recorded reason was, in each case, the empty list.

These pin the reason itself — not the verdict, which was never in doubt.
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
    return _note(
        vault,
        rel,
        "---\nstatus: evergreen\nrelated: []\nsummary: A note.\n---\n\n" + body + "\n",
    )


def _broken_note(vault: Path, rel: str) -> Path:
    return _note(vault, rel, "---\ntitle: [unclosed\n---\n\nBody.\n")


# ---------------------------------------------------------------------------
# malformed frontmatter
# ---------------------------------------------------------------------------


class TestMalformedFrontmatterIsReported:
    def test_the_offending_file_is_named_in_errors(self, tmp_path: Path) -> None:
        _broken_note(tmp_path, "04 - Concepts/Broken.md")

        result = verify(tmp_path, auto_fix=False)

        assert result.verdict == "FAIL"
        assert result.errors, "a FAIL with no reason is the #218 bug"
        joined = "\n".join(result.errors)
        assert "04 - Concepts/Broken.md" in joined

    def test_the_parse_error_travels_with_the_filename(self, tmp_path: Path) -> None:
        """``report['results']`` held the parse detail and was discarded; the
        reason has to carry enough to act on without re-running the processor."""
        _broken_note(tmp_path, "04 - Concepts/Broken.md")

        result = verify(tmp_path, auto_fix=False)

        detail = next(e for e in result.errors if "Broken.md" in e)
        assert "malformed" in detail.lower()
        assert "YAML parse error" in detail
        # One line per reason: these land in pipeline-state.json, and the
        # loader's own message is a five-line caret diagram.
        assert "\n" not in detail

    def test_many_malformed_notes_are_summarised_not_dumped(
        self, tmp_path: Path
    ) -> None:
        """A vault with hundreds of broken notes must not put hundreds of
        strings into ``pipeline-state.json``."""
        for i in range(40):
            _broken_note(tmp_path, f"04 - Concepts/Broken{i:02d}.md")

        result = verify(tmp_path, auto_fix=False)

        assert len(result.errors) < 40
        assert any("40" in e for e in result.errors)


# ---------------------------------------------------------------------------
# threshold FAIL
# ---------------------------------------------------------------------------


class TestThresholdFailIsReported:
    def _flag_heavy_vault(self, tmp_path: Path) -> None:
        # Notes with no frontmatter at all: each earns missing_related,
        # missing_status, missing_summary and orphan.
        for i in range(6):
            _note(tmp_path, f"04 - Concepts/Bare{i}.md", "Just a body.\n")

    def test_the_threshold_sentence_states_flags_notes_and_threshold(
        self, tmp_path: Path
    ) -> None:
        self._flag_heavy_vault(tmp_path)

        result = verify(tmp_path, auto_fix=False, fail_threshold=0.20)

        assert result.verdict == "FAIL"
        joined = "\n".join(result.errors)
        assert str(result.structural_flags) in joined
        assert str(result.notes_checked) in joined
        assert "0.2" in joined or "20" in joined

    def test_the_dominant_flag_families_are_named(self, tmp_path: Path) -> None:
        """Ratios are arithmetic; a named flag family is a thing to go and fix."""
        self._flag_heavy_vault(tmp_path)

        result = verify(tmp_path, auto_fix=False, fail_threshold=0.20)

        joined = "\n".join(result.errors)
        assert "missing_summary" in joined

    def test_the_resolved_threshold_is_carried_on_the_result(
        self, tmp_path: Path
    ) -> None:
        """The runner cannot report the threshold it was graded against unless
        the processor says which one it resolved."""
        self._flag_heavy_vault(tmp_path)

        result = verify(tmp_path, auto_fix=False, fail_threshold=0.05)

        assert result.fail_threshold == 0.05

    def test_flags_are_broken_down_by_check_in_the_report(self, tmp_path: Path) -> None:
        self._flag_heavy_vault(tmp_path)

        result = verify(tmp_path, auto_fix=False)

        breakdown = result.report["flags_by_check"]
        assert breakdown["missing_summary"] == 6
        assert sum(breakdown.values()) == result.structural_flags


# ---------------------------------------------------------------------------
# the quiet path stays quiet
# ---------------------------------------------------------------------------


class TestPassAndWarnStaySilent:
    def test_a_passing_vault_reports_no_errors(self, tmp_path: Path) -> None:
        _clean_note(tmp_path, "04 - Concepts/NoteA.md", "See [[NoteB]].")
        _clean_note(tmp_path, "04 - Concepts/NoteB.md", "See [[NoteA]].")

        result = verify(tmp_path, auto_fix=False)

        assert result.verdict == "PASS"
        assert result.errors == ()

    def test_an_empty_vault_reports_no_errors(self, tmp_path: Path) -> None:
        result = verify(tmp_path, auto_fix=False)

        assert result.verdict == "PASS"
        assert result.errors == ()
