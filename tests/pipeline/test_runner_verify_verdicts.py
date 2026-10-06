"""What the verify phase does with each verdict, and what it tells verify
(issues #228, #229).

**#229** — no test in the suite exercised ``_drive_verify``'s FAIL path.
Every ``VerifyResult`` fixture in ``tests/pipeline/test_runner.py`` carried
``verdict='PASS'``, so the exact live failure mode — FAIL verdict → phase
FAILED, with what error content, and rc 1 — was unpinned. The failure that hit
seven of eight live vaults on 2026-09-01 would have stayed green forever, and
that is precisely why the empty-``errors`` defect survived to be filed as #218.

**#228** — ``_drive_verify`` called ``verify()`` with no ``spec_processors``,
so a vault that sets ``processors.verify.fail_threshold`` in its own spec had
that setting ignored by the one phase that reads it. ``verify.py``'s docstring
had claimed the field was honoured since the processors moved into the
framework.

The mocked classes here pin the verdict → status → rc → errors mapping; the
unmocked class at the bottom drives the real processor over a real vault, so a
mock cannot hide a processor-side regression again.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from research_framework.pipeline.runner import (
    DONE,
    FAILED,
    _blank_state,
    _drive_verify,
)
from research_framework.processors.verify import VerifyResult
from tests._helpers.vault_factory import build_minimal_vault

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(verdict: str, **overrides) -> VerifyResult:
    fields: dict = {
        "files_processed": 12,
        "notes_checked": 10,
        "auto_fixes_applied": 0,
        "structural_flags": 0,
        "malformed_count": 0,
        "verdict": verdict,
        "report": {"verdict": verdict, "results": [], "flags_by_check": {}},
        "errors": (),
        "fail_threshold": 0.20,
        "content_flags": 0,
        "tooling_flags": 0,
    }
    fields.update(overrides)
    return VerifyResult(**fields)


def _run(vault: Path, result: VerifyResult | None = None, exc: Exception | None = None):
    """Drive the verify phase, optionally against a stubbed processor."""
    state = _blank_state("2026-09-07-1200", "2026-09-07T12:00:00Z")
    if result is None and exc is None:
        rc = _drive_verify(vault, state, quiet=True)
        return rc, state, None
    with patch(
        "research_framework.processors.verify.verify",
        side_effect=exc,
        **({} if exc else {"return_value": result}),
    ) as spy:
        rc = _drive_verify(vault, state, quiet=True)
    return rc, state, spy


def _phase(state: dict) -> dict:
    return state["phases"]["verify"]


# ---------------------------------------------------------------------------
# #229 — every verdict, and what it costs
# ---------------------------------------------------------------------------

THRESHOLD_SENTENCE = (
    "FAIL: 30 content flag(s) across 10 note(s) = 300.0%, over the 20% "
    "fail_threshold (44 structural flag(s) in total; 14 tooling flag(s) did "
    "not count toward the verdict)."
)


class TestFailVerdict:
    def _fail(self, tmp_path: Path):
        vault = build_minimal_vault(tmp_path)
        return _run(
            vault,
            _result(
                "FAIL",
                structural_flags=44,
                content_flags=30,
                tooling_flags=14,
                errors=(THRESHOLD_SENTENCE,),
            ),
        )

    def test_a_fail_verdict_fails_the_phase(self, tmp_path: Path) -> None:
        _rc, state, _ = self._fail(tmp_path)

        assert _phase(state)["status"] == FAILED

    def test_a_fail_verdict_exits_non_zero(self, tmp_path: Path) -> None:
        rc, _state, _ = self._fail(tmp_path)

        assert rc == 1

    def test_a_fail_verdict_records_a_reason(self, tmp_path: Path) -> None:
        """#218's defect was a FAIL persisted with ``errors: []``."""
        _rc, state, _ = self._fail(tmp_path)

        assert _phase(state)["errors"] == [THRESHOLD_SENTENCE]

    def test_the_summary_carries_the_flag_split(self, tmp_path: Path) -> None:
        """A verdict driven by content flags is not diagnosable from a total."""
        _rc, state, _ = self._fail(tmp_path)
        summary = _phase(state)["summary"]

        assert summary["content_flags"] == 30
        assert summary["tooling_flags"] == 14
        assert summary["structural_flags"] == 44
        assert summary["fail_threshold"] == 0.20


class TestWarnVerdict:
    def test_a_warn_verdict_completes_the_phase(self, tmp_path: Path) -> None:
        """WARN is the verdict a lightly-linked vault now earns instead of
        FAIL. It must not stop the run."""
        vault = build_minimal_vault(tmp_path)

        rc, state, _ = _run(
            vault, _result("WARN", structural_flags=14, tooling_flags=14)
        )

        assert rc == 0
        assert _phase(state)["status"] == DONE
        assert _phase(state)["summary"]["verdict"] == "WARN"


class TestPassVerdict:
    def test_a_pass_verdict_completes_the_phase(self, tmp_path: Path) -> None:
        vault = build_minimal_vault(tmp_path)

        rc, state, _ = _run(vault, _result("PASS"))

        assert rc == 0
        assert _phase(state)["status"] == DONE


class TestProcessorError:
    def test_a_raising_processor_is_an_error_verdict(self, tmp_path: Path) -> None:
        vault = build_minimal_vault(tmp_path)

        rc, state, _ = _run(vault, exc=RuntimeError("corpus vanished"))

        assert rc == 1
        assert _phase(state)["status"] == FAILED
        assert _phase(state)["summary"]["verdict"] == "ERROR"

    def test_the_exception_text_reaches_errors(self, tmp_path: Path) -> None:
        """An ERROR with no message is the #218 defect wearing a hat."""
        vault = build_minimal_vault(tmp_path)

        _rc, state, _ = _run(vault, exc=RuntimeError("corpus vanished"))

        assert any("corpus vanished" in e for e in _phase(state)["errors"])


# ---------------------------------------------------------------------------
# #228 — the phase tells verify what the vault declared
# ---------------------------------------------------------------------------


class TestSpecConfigReachesTheProcessor:
    def _vault_declaring(self, tmp_path: Path, processors: dict) -> Path:
        vault = build_minimal_vault(tmp_path)
        parse_path = vault / "_pipeline" / "spec-parse.json"
        doc = json.loads(parse_path.read_text(encoding="utf-8"))
        doc["processors"] = processors
        parse_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        return vault

    def test_the_specs_processors_section_is_passed_down(self, tmp_path: Path) -> None:
        vault = self._vault_declaring(
            tmp_path, {"verify": {"fail_threshold": 0.55, "auto_fix": True}}
        )

        _rc, _state, spy = _run(vault, _result("PASS"))

        assert spy.call_args.kwargs["spec_processors"] == {
            "verify": {"fail_threshold": 0.55, "auto_fix": True}
        }

    def test_the_declared_threshold_actually_grades_the_run(
        self, tmp_path: Path
    ) -> None:
        """End to end, no mock: a lenient spec threshold must change the
        verdict of a vault that would otherwise fail."""
        vault = self._vault_declaring(tmp_path, {"verify": {"fail_threshold": 50.0}})
        note = vault / "data_vault" / "01 - Concepts" / "Lonely.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text("---\ntitle: Lonely\n---\n\nNo links.\n", encoding="utf-8")

        rc, state, _ = _run(vault)

        assert _phase(state)["summary"]["fail_threshold"] == 50.0
        assert _phase(state)["summary"]["verdict"] != "FAIL"
        assert rc == 0

    def test_no_mutation_beats_a_spec_that_asks_for_auto_fix(
        self, tmp_path: Path
    ) -> None:
        """A phase named "verify" reports. ``auto_fix=False`` stays an explicit
        argument so it wins the precedence ladder over spec config."""
        vault = self._vault_declaring(tmp_path, {"verify": {"auto_fix": True}})
        note = vault / "data_vault" / "01 - Concepts" / "Lonely.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        original = "---\ntitle: Lonely\n---\n\nNo links.\n"
        note.write_text(original, encoding="utf-8")

        _rc, state, _ = _run(vault)

        assert note.read_text(encoding="utf-8") == original
        assert _phase(state)["summary"]["auto_fixes_applied"] == 0

    def test_a_vault_with_no_processors_section_still_runs(
        self, tmp_path: Path
    ) -> None:
        vault = build_minimal_vault(tmp_path)

        _rc, _state, spy = _run(vault, _result("PASS"))

        assert spy.call_args.kwargs["spec_processors"] == {}

    def test_the_declared_note_types_reach_the_processor(self, tmp_path: Path) -> None:
        """The MOC-consistency check needs the vault's folders, or it grades a
        generated vault against another vault's taxonomy (#226)."""
        vault = build_minimal_vault(tmp_path)

        _rc, _state, spy = _run(vault, _result("PASS"))

        folders = {nt["folder"] for nt in spy.call_args.kwargs["spec_note_types"] or []}
        assert folders == {"01 - Concepts"}


# ---------------------------------------------------------------------------
# The real processor, over a real vault (#229's "no mock may hide this")
# ---------------------------------------------------------------------------


class TestTheRealProcessorFailsTheRealPhase:
    def _failing_vault(self, tmp_path: Path) -> Path:
        vault = build_minimal_vault(tmp_path)
        note = vault / "data_vault" / "01 - Concepts" / "Broken.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text("---\ntitle: [unclosed\n---\n\nBody.\n", encoding="utf-8")
        return vault

    def test_a_real_fail_fails_the_phase_with_a_reason(self, tmp_path: Path) -> None:
        vault = self._failing_vault(tmp_path)

        rc, state, _ = _run(vault)

        assert rc == 1
        assert _phase(state)["status"] == FAILED
        assert _phase(state)["summary"]["verdict"] == "FAIL"
        assert _phase(state)["errors"], "a FAIL with no reason is the #218 bug"

    def test_the_flagged_note_reaches_the_persisted_report(
        self, tmp_path: Path
    ) -> None:
        vault = self._failing_vault(tmp_path)

        _rc, state, _ = _run(vault)

        report_path = Path(_phase(state)["summary"]["report_path"])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        flagged = {r["file"] for r in report["results"]}
        assert "01 - Concepts/Broken.md" in flagged
