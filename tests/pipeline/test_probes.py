"""RED tests (T087): queryability probes — generation, rubric, score, trajectory.

Imports are **inside** tests so collection succeeds before `probes.py` (T089).
Trajectory bucketing matches task 017 wording (5pp strict threshold):
  - current - previous > 5  → ``improving``
  - previous - current > 5  → ``regressing``
  - else (incl. exactly 5pp deltas) → ``stable``
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)


def _probes_module():
    import research_framework.pipeline.probes as p

    return p


def _minimal_probe_spec() -> SpecConfig:
    scope = ScopeConfig(
        domain="d",
        organization="o",
        boundaries=["edge-auth"],
        contextual_questions=["What runs first?"],
    )
    return SpecConfig(
        name="probe-vault",
        location=Path("."),
        owner="t",
        scope=scope,
        note_types=[
            NoteTypeConfig(
                name="concept",
                description="c",
                folder="c/",
                required_sections=["Overview"],
                contextual_questions=["How does caching work?"],
            ),
        ],
        data_sources=[DataSourceConfig(name="s", type="external", priority=2)],
        search_dimensions=["x"],
        coverage_targets=CoverageTargets(
            categories=[
                CoverageCategory(
                    name="n", note_type="concept", target_count=1, met_count=0
                )
            ]
        ),
        budget=BudgetConfig(),
    )


def test_generate_probes_is_deterministic() -> None:
    p = _probes_module()
    spec = _minimal_probe_spec()
    a = p.generate_probes(spec)
    b = p.generate_probes(spec)
    ids_a = [x.probe_id for x in sorted(a, key=lambda z: z.probe_id)]
    ids_b = [x.probe_id for x in sorted(b, key=lambda z: z.probe_id)]
    assert ids_a == ids_b
    assert a == b


def test_score_candidates_rubric_three_binary_checks(tmp_path: Path) -> None:
    """Rubric (task T087): presence in candidates, top-K (K=3), frontmatter key match."""
    p = _probes_module()
    vault = tmp_path / "vscore"
    notes = vault / "data_vault" / "c"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "answer.md").write_text(
        "---\n"
        'title: "Ans"\n'
        "type: concept\n"
        'coverage_category: "n"\n'
        'summary: "Explains redis pooling for operators."\n'
        "---\n\n"
        "## Overview\n\n"
        "Short.\n",
        encoding="utf-8",
    )

    probe = p.QueryabilityProbe(
        probe_id="rx",
        kind="coverage",
        question="What is redis pooling?",
        keywords=["redis"],
        source_category="n",
        source_field="contextual_questions",
    )
    in_top3 = [
        p.CandidateNote(filename="noise_a.md", confidence="low"),
        p.CandidateNote(filename="answer.md", confidence="high"),
        p.CandidateNote(filename="noise_b.md", confidence="medium"),
    ]
    res = p.score_candidates(probe, in_top3, vault_dir=vault)
    assert res.answered is True
    sc_answer = dict(res.scored_candidates)["answer.md"]
    assert sc_answer == 3

    not_in_list = [
        p.CandidateNote(filename="other.md", confidence="high"),
    ]
    res_miss = p.score_candidates(probe, not_in_list, vault_dir=vault)
    assert res_miss.answered is False

    ranked_outside_k = [
        p.CandidateNote(filename="a.md", confidence="high"),
        p.CandidateNote(filename="b.md", confidence="high"),
        p.CandidateNote(filename="c.md", confidence="high"),
        p.CandidateNote(filename="answer.md", confidence="high"),
    ]
    res_k = p.score_candidates(probe, ranked_outside_k, vault_dir=vault)
    assert res_k.answered is False


def test_run_cycle_probes_percent_score(tmp_path: Path) -> None:
    p = _probes_module()
    spec = _minimal_probe_spec()
    (tmp_path / "_pipeline").mkdir(parents=True, exist_ok=True)
    (tmp_path / "_pipeline" / "spec-parse.json").write_text(
        json.dumps(spec.to_dict(), indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    score, trajectory = p.run_cycle_probes(
        vault_dir=tmp_path,
        spec=spec,
        cycle_number=1,
    )
    assert trajectory in ("improving", "stable", "regressing")
    assert 0 <= score <= 100


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (40, 46, "improving"),
        (40, 45, "stable"),
        (50, 44, "regressing"),
        (50, 45, "stable"),
        (0, 6, "improving"),
        (10, 4, "regressing"),
    ],
)
def test_trajectory_bucket_five_point_boundary(
    previous: int, current: int, expected: str
) -> None:
    p = _probes_module()
    assert p.trajectory_bucket(current, previous) == expected


def test_a_candidate_filename_is_matched_as_a_name_not_as_a_glob(
    tmp_path: Path,
) -> None:
    """Candidate filenames are whatever the retrieval agent returned. Handing
    one to ``rglob`` made it a pattern: ``*.md`` resolved to some arbitrary
    note, which was then scored in its place, and a real note with ``[`` in
    its name was never found."""
    from research_framework.pipeline.probes import _find_note_file

    corpus = tmp_path / "data_vault" / "topics"
    corpus.mkdir(parents=True)
    (corpus / "unrelated.md").write_text("# Unrelated\n", encoding="utf-8")
    bracketed = corpus / "Kafka [v2].md"
    bracketed.write_text("# Kafka\n", encoding="utf-8")

    assert _find_note_file(tmp_path, "data_vault", "*.md") is None
    assert _find_note_file(tmp_path, "data_vault", "unrelate?.md") is None
    assert _find_note_file(tmp_path, "data_vault", "Kafka [v2].md") == bracketed
