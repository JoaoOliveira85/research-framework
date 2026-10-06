"""Spec 063 US3 (T015) — authority (053) + credibility (055) citation grading.

- A note grounded only off-trunk is counted in ``authority_inversions``.
- Credibility tiers + ``coi`` are surfaced (counted), never auto-failed.
- A journal-first vault is graded against its *own* derived trunk, never an
  assumed code trunk (the edge case).
"""

from __future__ import annotations

from pathlib import Path

from research_framework.cli import acceptance

_JOURNAL_SPEC = """---
name: journal-first
owner: tests
location: /tmp/journal-first
scope:
  domain: Journal-first vault (derived trunk is the journal, not code)
  organization: Tests
  boundaries: [Fixture-only]
  out_of_scope: []
note_types:
  - name: concept
    description: Concept
    folder: "03 - Concepts"
    required_sections: ["Overview"]
    min_word_count: 10
    template_version: "1.0.0"
data_sources:
  - name: Engineering Journal
    type: external
    role: experience
    description: The lab journal — highest authority here.
    priority: 1
    required: true
  - name: GitHub
    type: code
    role: behaviour
    description: Supporting code.
    priority: 2
    required: false
    repos:
      - org: example
        url: https://github.com/example/repo
search_dimensions: [technical]
coverage_targets:
  categories:
    - name: concepts
      note_type: concept
      target_count: 1
      met_count: 0
      priority: 90
---
"""


def _journal_note(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                "title: Lab Result",
                "type: concept",
                "verifier_status: approved",
                "summary: A finding grounded in the journal.",
                "source_urls:",
                "  - url: https://journal.example.com/entry/42",
                "    credibility: primary",
                "---",
                "",
                "## Overview",
                "",
                "Body.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _make_journal_vault(root: Path) -> Path:
    (root / "data_vault" / "03 - Concepts").mkdir(parents=True, exist_ok=True)
    (root / "research.spec.md").write_text(_JOURNAL_SPEC, encoding="utf-8")
    _journal_note(root / "data_vault" / "03 - Concepts" / "Lab Result.md")
    return root


# --- snapshot grading -------------------------------------------------------


def test_authority_inversion_flagged(snapshot_vault):
    grading = acceptance.build_citation_grading(snapshot_vault)
    assert grading["derived_trunk_role"] == "behaviour"
    # "Roadmap Bet" cites only intent/vendor sources, never the code trunk.
    assert grading["authority_inversions"] >= 1


def test_credibility_and_coi_surfaced(snapshot_vault):
    grading = acceptance.build_citation_grading(snapshot_vault)
    # Roadmap Bet's two citations have no credibility tier.
    assert grading["credibility_ungraded"] >= 2
    # Its vendor-blog citation is coi: true.
    assert grading["coi_flagged"] >= 1


def test_clean_twin_is_well_grounded(clean_vault):
    grading = acceptance.build_citation_grading(clean_vault)
    assert grading["authority_inversions"] == 0
    assert grading["credibility_ungraded"] == 0
    assert grading["coi_flagged"] == 0


# --- journal-first edge case ------------------------------------------------


def test_journal_first_graded_against_own_trunk(tmp_path):
    vault = _make_journal_vault(tmp_path / "journal")
    grading = acceptance.build_citation_grading(vault)
    # The derived trunk is the journal's role, NOT an assumed "behaviour"/code.
    assert grading["derived_trunk_role"] == "experience"
    # The trunk role isn't code/module-resolvable, so notes are NOT punished as
    # authority inversions just for not citing code.
    assert grading["authority_inversions"] == 0
