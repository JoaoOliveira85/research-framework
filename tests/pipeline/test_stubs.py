"""Tests for src/research_framework/pipeline/stubs.py.

Principle VIII "Stub-as-Fuel" detection: every note in `data_vault/` that
fails any of the four stub criteria must be surfaced. Under constitution
v1.3.0 the orchestrator uses this list to *keep the cycle loop alive* (so
the next cycle can write or close the stubs); a successful exit requires
the list to be empty along with two other triggers (constitution v1.3.0
§ Principle II). The orchestrator-loop assertions live in
`test_orchestrator.py`; this file just covers the detector itself.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.pipeline.stubs import Stub, _check_note, scan_stubs
from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)


def _spec(vault_dir: Path, min_word_count: int = 200) -> SpecConfig:
    """A minimal spec whose note_type declares the target folder."""
    return SpecConfig(
        name="T",
        location=vault_dir,
        owner="t",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[
            NoteTypeConfig(
                name="concept",
                description="d",
                folder="01 - Concepts",
                min_word_count=min_word_count,
                source_policy="hard",
            )
        ],
        data_sources=[DataSourceConfig(name="Web", type="external", role="domain")],
        search_dimensions=[
            "technical",
            "organizational",
            "domain",
            "market",
            "temporal",
        ],
        coverage_targets=CoverageTargets(
            categories=[CoverageCategory(name="c", note_type="concept", target_count=1)]
        ),
        budget=BudgetConfig(),
    )


def _good_note_body(word_count: int = 250) -> str:
    body = " ".join(["lorem"] * word_count)
    return f"""---
source_urls:
  - https://example.org/article
verifier_status: accepted
status: published
---

{body}
"""


def _write_note(vault: Path, filename: str, body: str) -> Path:
    path = vault / "data_vault" / "01 - Concepts" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Basic passthrough (no stubs)
# ---------------------------------------------------------------------------


class TestNoStubs:
    def test_empty_vault_returns_empty_list(self, tmp_path: Path) -> None:
        spec = _spec(tmp_path)
        assert scan_stubs(tmp_path, spec) == []

    def test_missing_data_vault_returns_empty_list(self, tmp_path: Path) -> None:
        """No data_vault/ yet = nothing to check."""
        spec = _spec(tmp_path)
        assert scan_stubs(tmp_path, spec) == []

    def test_valid_note_is_not_a_stub(self, tmp_path: Path) -> None:
        spec = _spec(tmp_path)
        _write_note(tmp_path, "Good.md", _good_note_body())
        assert scan_stubs(tmp_path, spec) == []


# ---------------------------------------------------------------------------
# Individual stub criteria
# ---------------------------------------------------------------------------


class TestStubCriteria:
    def test_short_body_is_a_stub(self, tmp_path: Path) -> None:
        spec = _spec(tmp_path, min_word_count=200)
        _write_note(tmp_path, "Short.md", _good_note_body(word_count=50))
        stubs = scan_stubs(tmp_path, spec)
        assert len(stubs) == 1
        assert any("word_count" in r for r in stubs[0].reasons)
        assert stubs[0].word_count == 50

    def test_missing_source_urls_is_a_stub(self, tmp_path: Path) -> None:
        spec = _spec(tmp_path)
        body = """---
verifier_status: accepted
status: published
---

""" + " ".join(["word"] * 300)
        _write_note(tmp_path, "NoSource.md", body)
        stubs = scan_stubs(tmp_path, spec)
        assert len(stubs) == 1
        assert any("source_urls empty" in r for r in stubs[0].reasons)

    def test_empty_source_urls_list_is_a_stub(self, tmp_path: Path) -> None:
        """Explicit empty list treated the same as missing key."""
        spec = _spec(tmp_path)
        body = """---
source_urls: []
verifier_status: accepted
status: published
---

""" + " ".join(["word"] * 300)
        _write_note(tmp_path, "EmptySource.md", body)
        stubs = scan_stubs(tmp_path, spec)
        assert len(stubs) == 1

    def test_verifier_pending_is_a_stub(self, tmp_path: Path) -> None:
        spec = _spec(tmp_path)
        body = _good_note_body().replace("accepted", "pending")
        _write_note(tmp_path, "Pending.md", body)
        stubs = scan_stubs(tmp_path, spec)
        assert len(stubs) == 1
        assert any("verifier_status=pending" in r for r in stubs[0].reasons)

    def test_verifier_rejected_is_a_stub(self, tmp_path: Path) -> None:
        spec = _spec(tmp_path)
        body = _good_note_body().replace("accepted", "rejected")
        _write_note(tmp_path, "Rejected.md", body)
        stubs = scan_stubs(tmp_path, spec)
        assert len(stubs) == 1
        assert any("verifier_status=rejected" in r for r in stubs[0].reasons)

    def test_missing_verifier_status_is_a_stub_by_default(self, tmp_path: Path) -> None:
        """Absent ``verifier_status`` is a stub when settings default (verifier enabled).

        Since spec 004 wired the verifier stage, the default behaviour is
        stages.verifier.enabled=True — a note that reaches scan_stubs without
        a verifier stamp was skipped by the verifier, which is a problem.
        Pass settings with enabled=False explicitly to get the old neutral
        behaviour (tested separately in TestVerifierEnabledGate).
        """
        spec = _spec(tmp_path)
        body = """---
source_urls: [https://example.org]
status: published
---

""" + " ".join(["word"] * 300)
        _write_note(tmp_path, "NoVerifier.md", body)
        stubs = scan_stubs(tmp_path, spec)
        assert len(stubs) == 1
        assert any("verifier_status=" in r for r in stubs[0].reasons)

    def test_pending_verifier_status_is_a_stub(self, tmp_path: Path) -> None:
        """Explicit ``verifier_status: pending`` still blocks exit."""
        spec = _spec(tmp_path)
        body = """---
source_urls: [https://example.org]
status: published
verifier_status: pending
---

""" + " ".join(["word"] * 300)
        _write_note(tmp_path, "PendingVerifier.md", body)
        stubs = scan_stubs(tmp_path, spec)
        assert len(stubs) == 1
        assert any("verifier_status=pending" in r for r in stubs[0].reasons)

    def test_rejected_verifier_status_is_a_stub(self, tmp_path: Path) -> None:
        """Explicit ``verifier_status: rejected`` still blocks exit."""
        spec = _spec(tmp_path)
        body = """---
source_urls: [https://example.org]
status: published
verifier_status: rejected
---

""" + " ".join(["word"] * 300)
        _write_note(tmp_path, "RejectedVerifier.md", body)
        stubs = scan_stubs(tmp_path, spec)
        assert len(stubs) == 1
        assert any("verifier_status=rejected" in r for r in stubs[0].reasons)

    def test_draft_status_is_a_stub(self, tmp_path: Path) -> None:
        spec = _spec(tmp_path)
        body = _good_note_body().replace("published", "draft")
        _write_note(tmp_path, "Draft.md", body)
        stubs = scan_stubs(tmp_path, spec)
        assert len(stubs) == 1
        assert any("status=draft" in r for r in stubs[0].reasons)

    def test_multiple_reasons_collected_on_one_note(self, tmp_path: Path) -> None:
        """A truly broken note should surface every reason it fails."""
        spec = _spec(tmp_path, min_word_count=200)
        body = """---
status: draft
verifier_status: pending
---

short body here
"""
        _write_note(tmp_path, "Broken.md", body)
        stubs = scan_stubs(tmp_path, spec)
        assert len(stubs) == 1
        reasons = stubs[0].reasons
        assert any("word_count" in r for r in reasons)
        assert any("source_urls empty" in r for r in reasons)
        assert any("verifier_status=pending" in r for r in reasons)
        assert any("status=draft" in r for r in reasons)


# ---------------------------------------------------------------------------
# Walking / filtering
# ---------------------------------------------------------------------------


class TestScanWalking:
    def test_underscore_files_skipped(self, tmp_path: Path) -> None:
        """`_index.md` and friends are not notes in the Quality-Bar sense."""
        spec = _spec(tmp_path)
        _write_note(tmp_path, "_index.md", "short, no frontmatter")
        assert scan_stubs(tmp_path, spec) == []

    def test_folders_outside_note_types_ignored(self, tmp_path: Path) -> None:
        """A junk file in a non-declared folder must not trigger stubs."""
        spec = _spec(tmp_path)
        stray = tmp_path / "data_vault" / "99 - Junk"
        stray.mkdir(parents=True)
        (stray / "whatever.md").write_text("short garbage")
        assert scan_stubs(tmp_path, spec) == []

    def test_a_custom_corpus_dir_is_scanned(self, tmp_path: Path) -> None:
        """The spec names the corpus folder (``vault.corpus_dir``).

        The scan looked under ``data_vault/`` whatever the spec said, found no
        such folder in a vault that keeps its notes elsewhere, and reported no
        stubs: the stub-free exit was met without one note being read.
        """
        spec = _spec(tmp_path)
        spec.vault_corpus_dir = "notes"
        stub = tmp_path / "notes" / "01 - Concepts" / "Thin.md"
        stub.parent.mkdir(parents=True)
        stub.write_text("short, no frontmatter", encoding="utf-8")

        assert [s.path for s in scan_stubs(tmp_path, spec)] == [stub]

    def test_results_sorted_by_path(self, tmp_path: Path) -> None:
        """Deterministic output — a/b/c order regardless of filesystem."""
        spec = _spec(tmp_path)
        for name in ["Charlie.md", "Alpha.md", "Bravo.md"]:
            _write_note(tmp_path, name, "x")
        stubs = scan_stubs(tmp_path, spec)
        names = [s.path.name for s in stubs]
        assert names == ["Alpha.md", "Bravo.md", "Charlie.md"]

    def test_nested_subfolders_walked(self, tmp_path: Path) -> None:
        spec = _spec(tmp_path)
        nested = tmp_path / "data_vault" / "01 - Concepts" / "subtopic" / "Nested.md"
        nested.parent.mkdir(parents=True)
        nested.write_text("short")
        stubs = scan_stubs(tmp_path, spec)
        assert len(stubs) == 1
        assert stubs[0].path == nested


# ---------------------------------------------------------------------------
# Stub.describe
# ---------------------------------------------------------------------------


class TestStubDescribe:
    def test_describe_uses_relative_path(self, tmp_path: Path) -> None:
        stub = Stub(
            path=tmp_path / "data_vault" / "01 - Concepts" / "X.md",
            note_type="concept",
            reasons=["word_count 10 < min 200"],
        )
        desc = stub.describe(tmp_path)
        assert desc.startswith("data_vault/01 - Concepts/X.md [concept]:")
        assert "word_count 10" in desc

    def test_describe_falls_back_to_absolute_path_when_outside_vault(
        self, tmp_path: Path
    ) -> None:
        """If the note lives outside the vault (shouldn't happen, but…) the
        describe() output still reads sensibly — no ValueError propagated."""
        stub = Stub(
            path=Path("/elsewhere/foo.md"),
            note_type="concept",
            reasons=["test"],
        )
        desc = stub.describe(tmp_path)
        assert "/elsewhere/foo.md" in desc


# ---------------------------------------------------------------------------
# Malformed input resilience
# ---------------------------------------------------------------------------


class TestMalformedInput:
    def test_note_without_frontmatter_is_a_stub(self, tmp_path: Path) -> None:
        """No frontmatter at all — obviously a stub, never an error."""
        spec = _spec(tmp_path)
        _write_note(tmp_path, "Plain.md", "Just a paragraph of plain prose.")
        stubs = scan_stubs(tmp_path, spec)
        assert len(stubs) == 1

    def test_malformed_yaml_frontmatter_is_a_stub(self, tmp_path: Path) -> None:
        """Broken YAML falls through to empty frontmatter → stub, not crash."""
        spec = _spec(tmp_path)
        body = "---\nfield: [unclosed list\n---\n\nbody"
        _write_note(tmp_path, "Broken.md", body)
        stubs = scan_stubs(tmp_path, spec)
        assert len(stubs) == 1

    def test_dashes_inside_a_value_do_not_end_the_frontmatter(
        self, tmp_path: Path
    ) -> None:
        """A `---` inside a value is not the closing delimiter.

        The split was on the first `---` substring, so a slug URL ended the
        frontmatter there: `verifier_status` and `status` below it were lost
        and a finished, verified note was a stub again every cycle.
        """
        spec = _spec(tmp_path)
        words = " ".join(["lorem"] * 250)
        _write_note(
            tmp_path,
            "Kafka.md",
            "---\n"
            "source_urls:\n"
            "  - https://example.org/kafka---a-guide\n"
            "verifier_status: accepted\n"
            "status: published\n"
            "---\n"
            "\n"
            f"{words}\n",
        )

        assert scan_stubs(tmp_path, spec) == []


# ---------------------------------------------------------------------------
# Verifier-enabled gate (T018 / T019)
# ---------------------------------------------------------------------------


def _note_type() -> NoteTypeConfig:
    from research_framework.spec.schema import NoteTypeConfig

    return NoteTypeConfig(
        name="concept",
        description="d",
        folder="01 - Concepts",
        min_word_count=10,
        source_policy="hard",
    )


def _minimal_note_path(tmp_path: Path, verifier_status: str | None = None) -> Path:
    """Write a note that passes all criteria except possibly verifier_status."""
    fm_lines = [
        "---",
        "source_urls:",
        "  - https://example.org/article",
        "status: published",
    ]
    if verifier_status is not None:
        fm_lines.append(f"verifier_status: {verifier_status}")
    fm_lines.append("---")
    body = " ".join(["word"] * 50)
    content = "\n".join(fm_lines) + "\n\n" + body
    path = tmp_path / "note.md"
    path.write_text(content, encoding="utf-8")
    return path


def test_empty_verifier_status_is_stub_when_verifier_enabled(tmp_path: Path) -> None:
    """Empty/absent verifier_status is a failing reason when verifier is enabled."""
    nt = _note_type()
    settings = {"stages": {"verifier": {"enabled": True}}}
    # Note with no verifier_status key at all
    note = _minimal_note_path(tmp_path)
    stub = _check_note(note, nt, settings=settings)
    assert stub is not None, "Expected stub when verifier enabled and status absent"
    assert any("verifier_status=" in r for r in stub.reasons)


def test_empty_verifier_status_not_stub_when_verifier_disabled(tmp_path: Path) -> None:
    """Absent verifier_status is neutral when verifier is disabled (back-compat)."""
    nt = _note_type()
    settings = {"stages": {"verifier": {"enabled": False}}}
    note = _minimal_note_path(tmp_path)
    stub = _check_note(note, nt, settings=settings)
    assert stub is None, "Expected no stub when verifier disabled and status absent"


def test_rejected_verifier_status_is_always_stub(tmp_path: Path) -> None:
    """verifier_status: rejected blocks exit regardless of settings."""
    nt = _note_type()
    for settings in [
        {"stages": {"verifier": {"enabled": True}}},
        {"stages": {"verifier": {"enabled": False}}},
        None,
    ]:
        note_dir = tmp_path / str(id(settings))
        note_dir.mkdir()
        note = note_dir / "note.md"
        content = (
            "---\n"
            "source_urls:\n  - https://example.org/article\n"
            "status: published\n"
            "verifier_status: rejected\n"
            "---\n\n" + " ".join(["word"] * 50)
        )
        note.write_text(content, encoding="utf-8")
        stub = _check_note(note, nt, settings=settings)
        assert stub is not None, (
            f"Expected stub for rejected status with settings={settings}"
        )
        assert any("verifier_status=rejected" in r for r in stub.reasons)


# ---------------------------------------------------------------------------
# Orchestrator integration
#
# Constitution v1.3.0 reframed Principle VIII: stubs are continuation fuel
# for the cycle loop, NOT a Phase-3 termination gate. The previous
# `_exit_if_stub_free` wrapper has been removed. The orchestrator's
# continuation logic is exercised in tests/pipeline/test_orchestrator.py
# (the `TestRunCyclesContinuation` class). What stays here is just the
# stub *detector* tested above — `scan_stubs` is still the canonical
# stub-criteria checker, even though its output is now used to keep the
# loop alive rather than to abort it.
# ---------------------------------------------------------------------------
