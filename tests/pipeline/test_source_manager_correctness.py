"""Spec 029 — source-manager correctness regression locks.

Two silent production bugs + their fixes are pinned here:

* **Bug 1 (US1)** — ``notify_required_source_degraded`` called ``mark_degraded``
  with 2 args against a 3-arg signature, so ``_pipeline/source-incidents.md``
  was never written (the ``TypeError`` was swallowed by a broad ``except``).
* **Bug 2 (US2)** — ``record_cycle`` counted ``notes_generated`` by substring-
  matching a source URL/name against note *file paths* instead of each note's
  frontmatter ``source_urls`` — corrupting ``consecutive_empty_cycles`` and
  triggering premature auto-archival.

T001: post-049 home of the helper is
``research_framework.pipeline._helpers.source_signals``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml

from research_framework.pipeline import source_manager as sm
from research_framework.pipeline._helpers.cycle_state import CycleRuntimeState
from research_framework.pipeline._helpers.source_signals import (
    notify_required_source_degraded,
)
from research_framework.spec.schema import (
    BudgetConfig,
    CoverageTargets,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)


def _seed_sources(vault: Path, sources: list[dict]) -> None:
    """Create sources.db (schema + tables) and add active, url'd sources."""
    (vault / "_pipeline").mkdir(parents=True, exist_ok=True)
    spec = SpecConfig(
        name="t",
        location=vault,
        owner="t",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[
            NoteTypeConfig(name="concept", description="", folder="01 - Concepts")
        ],
        data_sources=[],
        search_dimensions=[],
        coverage_targets=CoverageTargets(),
        budget=BudgetConfig(),
    )
    sm.seed(vault, spec)
    sm.append_discovered(vault, sources)


def _write_note(vault: Path, filename: str, source_urls) -> None:
    folder = vault / "data_vault" / "01 - Concepts"
    folder.mkdir(parents=True, exist_ok=True)
    fm: dict = {"type": "concept"}
    if source_urls is not None:
        fm["source_urls"] = source_urls
    body = "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n\n# " + filename + "\n"
    (folder / filename).write_text(body, encoding="utf-8")


def _notes_generated(vault: Path, cycle: int) -> dict[str, int]:
    conn = sqlite3.connect(vault / "_pipeline" / "sources.db")
    try:
        rows = conn.execute(
            "SELECT name, notes_generated FROM source_cycles WHERE cycle=?",
            (cycle,),
        ).fetchall()
    finally:
        conn.close()
    return {name: gen for name, gen in rows}


def _empty_cycles(vault: Path, name: str) -> int:
    conn = sqlite3.connect(vault / "_pipeline" / "sources.db")
    try:
        row = conn.execute(
            "SELECT consecutive_empty_cycles FROM sources WHERE name=?", (name,)
        ).fetchone()
    finally:
        conn.close()
    return int(row[0])


# --------------------------------------------------------------------------- #
# US1 — source degradation incidents are durably recorded
# --------------------------------------------------------------------------- #
class TestSourceIncidentsDurability:
    def test_notify_writes_markdown_and_sidecar(self, tmp_path: Path) -> None:
        """FR-001/001a/006: the real path writes BOTH md log + JSON sidecar."""
        vault = tmp_path / "v"
        (vault / "_pipeline").mkdir(parents=True)
        notify_required_source_degraded(
            vault,
            "BrokenFeed",
            role="domain",
            reason="HTTP 503",
            runtime_state=CycleRuntimeState(),
        )
        md = vault / "_pipeline" / "source-incidents.md"
        assert md.is_file(), "source-incidents.md must be written end-to-end"
        text = md.read_text(encoding="utf-8")
        assert "`BrokenFeed` degraded" in text
        assert "HTTP 503" in text
        sidecars = list(
            (vault / "_pipeline" / "cycles").glob("cycle-*-source-incidents.json")
        )
        assert sidecars, "the per-cycle JSON sidecar must still be written (FR-001a)"

    def test_enrichment_role_not_counted(self, tmp_path: Path) -> None:
        vault = tmp_path / "v"
        (vault / "_pipeline").mkdir(parents=True)
        rc = notify_required_source_degraded(
            vault,
            "RssX",
            role="enrichment",
            reason="down",
            runtime_state=CycleRuntimeState(),
        )
        assert rc is None
        assert not (vault / "_pipeline" / "source-incidents.md").exists()

    def test_resolved_line_appended_on_recovery(self, tmp_path: Path) -> None:
        """FR-007: recovery APPENDS a resolved line; the degraded line stays."""
        vault = tmp_path / "v"
        (vault / "_pipeline").mkdir(parents=True)
        sm.mark_degraded("BrokenFeed", "HTTP 503", vault)
        sm.mark_resolved("BrokenFeed", vault)
        text = (vault / "_pipeline" / "source-incidents.md").read_text(encoding="utf-8")
        assert "`BrokenFeed` degraded" in text
        assert "`BrokenFeed` resolved" in text
        assert text.index("degraded") < text.index("resolved"), (
            "append-only: the degraded line must be preserved before the resolved line"
        )

    def test_arity_bug_surfaces_not_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SC-004: mark_degraded is called WITH vault_dir; a signature mismatch
        now raises instead of being swallowed by a broad except."""
        vault = tmp_path / "v"
        (vault / "_pipeline").mkdir(parents=True)

        seen: list[tuple] = []

        def spy(name: str, reason: str, vault_dir: Path) -> None:
            seen.append((name, reason, vault_dir))

        monkeypatch.setattr(sm, "mark_degraded", spy, raising=True)
        notify_required_source_degraded(
            vault,
            "BrokenFeed",
            role="domain",
            reason="HTTP 503",
            runtime_state=CycleRuntimeState(),
        )
        assert len(seen) == 1, "mark_degraded must be invoked once with 3 args"
        assert seen[0][0] == "BrokenFeed"
        assert seen[0][2] == vault, "the in-scope vault_dir must be passed"

        def two_arg(name: str, reason: str) -> None:  # pragma: no cover - must raise
            raise AssertionError("unreachable: 2-arg signature under a 3-arg call")

        monkeypatch.setattr(sm, "mark_degraded", two_arg, raising=True)
        with pytest.raises(TypeError):
            notify_required_source_degraded(
                vault,
                "Other",
                role="domain",
                reason="y",
                runtime_state=CycleRuntimeState(),
            )


# --------------------------------------------------------------------------- #
# US2 — URL normalization helper (contract §1)
# --------------------------------------------------------------------------- #
class TestNormalizeSourceUrl:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://Example.com/Feed/", "https://example.com/Feed"),
            ("http://example.com/a#section", "http://example.com/a"),
            (
                "https://learning.oreilly.com/search/?q=rust",
                "https://learning.oreilly.com/search?q=rust",
            ),
            ("https://youtube.com/watch?v=abc#t=10", "https://youtube.com/watch?v=abc"),
            ("https://example.com", "https://example.com"),
            ("Anthropic", "anthropic"),
            ("", ""),
            # IPv6 literal — brackets must survive normalization (Copilot review).
            ("http://[::1]:8080/a/", "http://[::1]:8080/a"),
        ],
    )
    def test_normalize(self, raw: str, expected: str) -> None:
        assert sm.normalize_source_url(raw) == expected

    def test_none_is_empty(self) -> None:
        assert sm.normalize_source_url(None) == ""


# --------------------------------------------------------------------------- #
# US2 — shared citation predicate (contract §2)
# --------------------------------------------------------------------------- #
class TestNoteCitesSource:
    @pytest.mark.parametrize(
        ("source_urls", "name", "url", "expected"),
        [
            (["https://example.com/feed"], "Ex", "https://example.com/feed/", True),
            (["https://x.io/a#intro"], "X", "https://x.io/a", True),
            (["https://o.io/search?q=go"], "O", "https://o.io/search?q=rust", False),
            (["Anthropic blog"], "Anthropic", "https://anthropic.com", True),
            ("https://example.com/feed", "Ex", "https://example.com/feed", True),
            (None, "Ex", "https://example.com/feed", False),
            ([None, 123], "X", "https://nope.example", False),
            ([None, 123], "12", "https://nope.example", True),
        ],
    )
    def test_predicate(self, source_urls, name, url, expected) -> None:
        fm = {} if source_urls is None else {"source_urls": source_urls}
        assert sm._note_cites_source(fm, name, url) is expected

    def test_missing_field_is_false(self) -> None:
        assert sm._note_cites_source({"type": "concept"}, "Ex", "https://x") is False


# --------------------------------------------------------------------------- #
# US2 — record_cycle attribution from frontmatter
# --------------------------------------------------------------------------- #
class TestRecordCycleAttribution:
    def test_notes_generated_from_frontmatter(self, tmp_path: Path) -> None:
        vault = tmp_path / "v"
        _seed_sources(
            vault,
            [
                {
                    "name": "A",
                    "type": "external",
                    "role": "domain",
                    "url": "https://a.example.com/feed",
                },
                {
                    "name": "B",
                    "type": "external",
                    "role": "domain",
                    "url": "https://b.example.com/feed",
                },
                {
                    "name": "C",
                    "type": "external",
                    "role": "domain",
                    "url": "https://c.example.com/feed",
                },
            ],
        )
        _write_note(vault, "n1.md", ["https://a.example.com/feed"])
        _write_note(vault, "n2.md", ["https://b.example.com/feed"])
        _write_note(vault, "n3.md", ["https://c.example.com/feed"])
        _write_note(
            vault, "n4.md", ["https://a.example.com/feed", "https://b.example.com/feed"]
        )
        _write_note(vault, "n5.md", None)
        report = {
            "notes_created": [
                "n1.md",
                "data_vault/01 - Concepts/n2.md",
                "n3.md",
                "n4.md",
                "n5.md",
            ],
            "discovered_sources": [],
        }
        sm.record_cycle(vault, 1, report)
        counts = _notes_generated(vault, cycle=1)
        assert counts.get("A") == 2
        assert counts.get("B") == 2
        assert counts.get("C") == 1

    def test_empty_streak_increments_then_resets(self, tmp_path: Path) -> None:
        vault = tmp_path / "v"
        _seed_sources(
            vault,
            [
                {
                    "name": "A",
                    "type": "external",
                    "role": "domain",
                    "url": "https://a.example.com/feed",
                }
            ],
        )
        _write_note(vault, "n1.md", ["https://a.example.com/feed"])
        sm.record_cycle(
            vault, 1, {"notes_created": ["n1.md"], "discovered_sources": []}
        )
        assert _empty_cycles(vault, "A") == 0
        sm.record_cycle(vault, 2, {"notes_created": [], "discovered_sources": []})
        assert _empty_cycles(vault, "A") == 1
        sm.record_cycle(
            vault, 3, {"notes_created": ["n1.md"], "discovered_sources": []}
        )
        assert _empty_cycles(vault, "A") == 0

    def test_placeholder_note_counts_for_no_source(self, tmp_path: Path) -> None:
        vault = tmp_path / "v"
        _seed_sources(
            vault,
            [
                {
                    "name": "A",
                    "type": "external",
                    "role": "domain",
                    "url": "https://a.example.com/feed",
                }
            ],
        )
        _write_note(vault, "placeholder.md", None)
        sm.record_cycle(
            vault, 1, {"notes_created": ["placeholder.md"], "discovered_sources": []}
        )
        assert _notes_generated(vault, cycle=1).get("A", 0) == 0

    def test_embedded_dashes_in_frontmatter_do_not_truncate(
        self, tmp_path: Path
    ) -> None:
        """Closing fence is line-anchored (``\\n---``): a ``---`` inside a YAML
        value must not truncate the frontmatter before ``source_urls`` is read
        (Copilot review hardening)."""
        vault = tmp_path / "v"
        _seed_sources(
            vault,
            [
                {
                    "name": "A",
                    "type": "external",
                    "role": "domain",
                    "url": "https://a.example.com/feed",
                }
            ],
        )
        folder = vault / "data_vault" / "01 - Concepts"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "dash.md").write_text(
            "---\n"
            'title: "an em---dash in a value"\n'
            "source_urls:\n"
            "  - https://a.example.com/feed\n"
            "---\n\n# dash\n",
            encoding="utf-8",
        )
        sm.record_cycle(
            vault, 1, {"notes_created": ["dash.md"], "discovered_sources": []}
        )
        assert _notes_generated(vault, cycle=1).get("A") == 1
