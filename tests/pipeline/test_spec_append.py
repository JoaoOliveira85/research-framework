"""Spec 073 — a query that finds new ground records it in the spec.

Every acceptance criterion in `specs/073-query-driven-spec-append/spec.md` gets
a test here, plus the two promises that make the design safe: nothing above the
begin-marker is ever touched, and a malformed region is refused rather than
reconstructed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.pipeline.spec_append import (
    BEGIN_MARKER,
    END_MARKER,
    DiscoveredSource,
    Discovery,
    SpecRegionError,
    append_discovery,
    declared_hosts,
    split_region,
    topic_slug,
)

HUMAN_SPEC = """---
name: "Regional Tech"
owner: "test"
topic: |
  People and communities.
---

# Regional Tech

## Scope

Careful prose that was argued over once and must survive.

- out_of_scope: marketing
"""


@pytest.fixture
def spec_file(tmp_path: Path) -> Path:
    p = tmp_path / "research.spec.md"
    p.write_text(HUMAN_SPEC, encoding="utf-8")
    return p


def _region(path: Path) -> str:
    return split_region(path.read_text(encoding="utf-8"))[1]


def _discovery(**kw) -> Discovery:
    kw.setdefault("asked", "which agencies do I enrol with for contract work")
    return Discovery(**kw)


# --------------------------------------------------------------------------
# Acceptance: one entry, with the question that caused it
# --------------------------------------------------------------------------


def test_undeclared_domain_leaves_one_entry_with_its_question(spec_file: Path) -> None:
    changed = append_discovery(
        spec_file,
        _discovery(sources=[DiscoveredSource("https://www.prodata.dk/", "bureau")]),
        today="2026-08-28",
    )
    assert changed is True
    body = _region(spec_file)
    assert body.count("### 2026-08-28") == 1
    assert "which agencies do I enrol with" in body
    assert "www.prodata.dk" in body


def test_a_discovered_source_is_recorded_unassessed(spec_file: Path) -> None:
    """§4: nobody has judged it, so it must not silently earn a tier."""
    append_discovery(
        spec_file,
        _discovery(sources=[DiscoveredSource("https://www.prodata.dk/")]),
        today="2026-08-28",
    )
    body = _region(spec_file)
    assert "unassessed" in body
    for tier in ("primary", "corroborated", "commentary"):
        assert tier not in body


# --------------------------------------------------------------------------
# Acceptance: idempotence (§5)
# --------------------------------------------------------------------------


def test_asking_the_same_question_twice_leaves_one_entry(spec_file: Path) -> None:
    d = _discovery(sources=[DiscoveredSource("https://www.prodata.dk/")])
    assert append_discovery(spec_file, d, today="2026-08-28") is True
    assert append_discovery(spec_file, d, today="2026-08-29") is False
    assert _region(spec_file).count("**asked:**") == 1


def test_a_different_question_about_a_known_source_adds_nothing(
    spec_file: Path,
) -> None:
    """The source is the new ground; a second question about it is not."""
    append_discovery(
        spec_file,
        _discovery(sources=[DiscoveredSource("https://www.prodata.dk/")]),
        today="2026-08-28",
    )
    assert (
        append_discovery(
            spec_file,
            _discovery(
                asked="what do bureaus pay",
                sources=[DiscoveredSource("https://www.prodata.dk/deep/path")],
            ),
            today="2026-08-29",
        )
        is False
    )


def test_a_genuinely_new_source_does_append(spec_file: Path) -> None:
    append_discovery(
        spec_file,
        _discovery(sources=[DiscoveredSource("https://www.prodata.dk/")]),
        today="2026-08-28",
    )
    append_discovery(
        spec_file,
        _discovery(
            asked="who else places contractors",
            sources=[DiscoveredSource("https://www.ework.dk/")],
        ),
        today="2026-08-29",
    )
    body = _region(spec_file)
    assert body.count("### ") == 2
    assert "ework.dk" in body


def test_repeated_topic_is_not_recorded_twice(spec_file: Path) -> None:
    d1 = _discovery(topic="contract-and-consultancy channel")
    d2 = Discovery(
        asked="phrased differently", topic="Contract and Consultancy Channel"
    )
    assert append_discovery(spec_file, d1, today="2026-08-28") is True
    assert append_discovery(spec_file, d2, today="2026-08-29") is False


# --------------------------------------------------------------------------
# Acceptance: the region promise
# --------------------------------------------------------------------------


def test_everything_above_the_marker_is_byte_identical(spec_file: Path) -> None:
    """The whole promise of append-only, asserted."""
    before = spec_file.read_text(encoding="utf-8")
    append_discovery(
        spec_file,
        _discovery(sources=[DiscoveredSource("https://www.prodata.dk/")]),
        today="2026-08-28",
    )
    after = spec_file.read_text(encoding="utf-8")
    prefix_after = after[: after.index(BEGIN_MARKER)]
    assert before.rstrip("\n") == prefix_after.rstrip("\n")


def test_second_append_also_leaves_the_prefix_untouched(spec_file: Path) -> None:
    append_discovery(
        spec_file,
        _discovery(sources=[DiscoveredSource("https://a.example/")]),
        today="2026-08-28",
    )
    prefix_1 = spec_file.read_text(encoding="utf-8").split(BEGIN_MARKER)[0]
    append_discovery(
        spec_file,
        _discovery(asked="another", sources=[DiscoveredSource("https://b.example/")]),
        today="2026-08-29",
    )
    prefix_2 = spec_file.read_text(encoding="utf-8").split(BEGIN_MARKER)[0]
    assert prefix_1 == prefix_2


def test_a_spec_with_no_region_gains_exactly_one(spec_file: Path) -> None:
    append_discovery(
        spec_file,
        _discovery(sources=[DiscoveredSource("https://a.example/")]),
        today="2026-08-28",
    )
    text = spec_file.read_text(encoding="utf-8")
    assert text.count(BEGIN_MARKER) == 1
    assert text.count(END_MARKER) == 1


def test_a_spec_with_a_region_gains_no_second(spec_file: Path) -> None:
    for i, host in enumerate(("a.example", "b.example", "c.example")):
        append_discovery(
            spec_file,
            _discovery(asked=f"q{i}", sources=[DiscoveredSource(f"https://{host}/")]),
            today="2026-08-28",
        )
    text = spec_file.read_text(encoding="utf-8")
    assert text.count(BEGIN_MARKER) == 1


def test_deleting_the_region_by_hand_is_safe(spec_file: Path) -> None:
    append_discovery(
        spec_file,
        _discovery(sources=[DiscoveredSource("https://a.example/")]),
        today="2026-08-28",
    )
    spec_file.write_text(HUMAN_SPEC, encoding="utf-8")  # operator deleted it
    assert (
        append_discovery(
            spec_file,
            _discovery(sources=[DiscoveredSource("https://a.example/")]),
            today="2026-08-29",
        )
        is True
    )
    assert spec_file.read_text(encoding="utf-8").count(BEGIN_MARKER) == 1


# --------------------------------------------------------------------------
# Acceptance: a malformed region fails loudly
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "broken",
    [
        HUMAN_SPEC + BEGIN_MARKER + "\nno end\n",
        HUMAN_SPEC + END_MARKER + "\n",
        HUMAN_SPEC + END_MARKER + "\nx\n" + BEGIN_MARKER + "\n",
        HUMAN_SPEC + BEGIN_MARKER + "\n" + BEGIN_MARKER + "\n" + END_MARKER + "\n",
    ],
    ids=["begin-only", "end-only", "reversed", "duplicate-begin"],
)
def test_malformed_region_is_refused_not_rewritten(tmp_path: Path, broken: str) -> None:
    p = tmp_path / "research.spec.md"
    p.write_text(broken, encoding="utf-8")
    with pytest.raises(SpecRegionError):
        append_discovery(p, _discovery(), today="2026-08-28")
    assert p.read_text(encoding="utf-8") == broken, "must not touch a file it refuses"


# --------------------------------------------------------------------------
# Acceptance: appending is not adopting (§3)
# --------------------------------------------------------------------------


def test_appended_source_does_not_become_a_data_source(spec_file: Path) -> None:
    """The load-bearing decision: a record, not an adoption."""
    from research_framework.cli import load_spec

    append_discovery(
        spec_file,
        _discovery(sources=[DiscoveredSource("https://www.prodata.dk/")]),
        today="2026-08-28",
    )
    spec = load_spec(spec_file, location=spec_file.parent)
    assert "prodata.dk" not in declared_hosts(spec)
    assert all("prodata" not in (ds.name or "").lower() for ds in spec.data_sources)


def test_the_spec_still_parses_after_an_append(spec_file: Path) -> None:
    from research_framework.cli import load_spec

    append_discovery(
        spec_file,
        _discovery(sources=[DiscoveredSource("https://www.prodata.dk/")]),
        today="2026-08-28",
    )
    assert load_spec(spec_file, location=spec_file.parent) is not None


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def test_declared_hosts_covers_every_locator_shape() -> None:
    from research_framework.spec.schema import DataSourceConfig, RepoEnumeration

    class _Spec:
        data_sources = [
            DataSourceConfig(name="a", type="external", url="https://one.example/"),
            DataSourceConfig(name="b", type="external", urls=["https://two.example/"]),
            DataSourceConfig(
                name="c",
                type="internal",
                repos=[RepoEnumeration(name="r", url="https://github.com/x/y")],
            ),
        ]

    assert declared_hosts(_Spec()) == {"one.example", "two.example", "github.com"}


def test_topic_slug_is_punctuation_and_case_insensitive() -> None:
    assert topic_slug("Contract & Consultancy!") == topic_slug("contract-consultancy")


def test_nothing_new_means_no_write(spec_file: Path) -> None:
    """A question with neither a new source nor a new topic is provenance only."""
    changed = append_discovery(
        spec_file, Discovery(asked="just asking"), today="2026-08-28"
    )
    assert changed is False
    assert spec_file.read_text(encoding="utf-8") == HUMAN_SPEC


# --------------------------------------------------------------------------
# #258 — spec 073 §2: a `topic` is appended only when "a query asked for an
# area no coverage_target covers". record_query_discoveries never read
# coverage_targets, so every --target-topics cycle appended, even for an
# already-covered topic with no undeclared source.
# --------------------------------------------------------------------------


def _spec_with_coverage(categories, spec_path: Path):
    from research_framework.spec.schema import CoverageTargets

    class _Spec:
        data_sources = []
        coverage_targets = CoverageTargets(categories=categories)

    return _Spec()


def test_covered_topic_with_no_undeclared_source_leaves_spec_untouched(
    spec_file: Path, monkeypatch
) -> None:
    from research_framework.pipeline import spec_append
    from research_framework.spec.schema import CoverageCategory

    spec = _spec_with_coverage(
        [
            CoverageCategory(
                name="regional-engineering-consultancies",
                note_type="concept",
                target_count=1,
            )
        ],
        spec_file,
    )
    monkeypatch.setattr(spec_append, "cited_hosts_for_cycle", lambda v, c: [])
    before = spec_file.read_text(encoding="utf-8")

    changed = spec_append.record_query_discoveries(
        spec_file.parent, spec, 1, ["Regional engineering consultancies"]
    )

    assert changed is False
    assert spec_file.read_text(encoding="utf-8") == before


def test_uncovered_topic_is_still_appended(spec_file: Path, monkeypatch) -> None:
    from research_framework.pipeline import spec_append
    from research_framework.spec.schema import CoverageCategory

    spec = _spec_with_coverage(
        [
            CoverageCategory(
                name="unrelated-category", note_type="concept", target_count=1
            )
        ],
        spec_file,
    )
    monkeypatch.setattr(spec_append, "cited_hosts_for_cycle", lambda v, c: [])

    changed = spec_append.record_query_discoveries(
        spec_file.parent, spec, 1, ["Regional engineering consultancies"]
    )

    assert changed is True
    text = spec_file.read_text(encoding="utf-8")
    assert "regional engineering consultancies" in text.lower()


def test_topic_covered_by_display_name_is_not_appended(
    spec_file: Path, monkeypatch
) -> None:
    from research_framework.pipeline import spec_append
    from research_framework.spec.schema import CoverageCategory

    spec = _spec_with_coverage(
        [
            CoverageCategory(
                name="misc",
                note_type="concept",
                target_count=1,
                display_name="Regional Engineering Consultancies",
            )
        ],
        spec_file,
    )
    monkeypatch.setattr(spec_append, "cited_hosts_for_cycle", lambda v, c: [])
    before = spec_file.read_text(encoding="utf-8")

    changed = spec_append.record_query_discoveries(
        spec_file.parent, spec, 1, ["regional engineering consultancies"]
    )

    assert changed is False
    assert spec_file.read_text(encoding="utf-8") == before


def test_topic_covered_by_expected_filename_is_not_appended(
    spec_file: Path, monkeypatch
) -> None:
    from research_framework.pipeline import spec_append
    from research_framework.spec.schema import CoverageCategory

    spec = _spec_with_coverage(
        [
            CoverageCategory(
                name="misc",
                note_type="concept",
                target_count=1,
                expected_filenames=["Regional-Engineering-Consultancies.md"],
            )
        ],
        spec_file,
    )
    monkeypatch.setattr(spec_append, "cited_hosts_for_cycle", lambda v, c: [])
    before = spec_file.read_text(encoding="utf-8")

    changed = spec_append.record_query_discoveries(
        spec_file.parent, spec, 1, ["Regional Engineering Consultancies"]
    )

    assert changed is False
    assert spec_file.read_text(encoding="utf-8") == before


def test_undeclared_source_still_recorded_when_topic_is_covered(
    spec_file: Path, monkeypatch
) -> None:
    """A covered topic must not suppress an otherwise-undeclared source (#258
    only narrows the `topic` field — sources used are unaffected)."""
    from research_framework.pipeline import spec_append
    from research_framework.spec.schema import CoverageCategory

    spec = _spec_with_coverage(
        [
            CoverageCategory(
                name="regional-engineering-consultancies",
                note_type="concept",
                target_count=1,
            )
        ],
        spec_file,
    )
    monkeypatch.setattr(
        spec_append,
        "cited_hosts_for_cycle",
        lambda v, c: [
            spec_append.DiscoveredSource("https://www.prodata.dk/", "cited by note.md")
        ],
    )

    changed = spec_append.record_query_discoveries(
        spec_file.parent, spec, 1, ["Regional engineering consultancies"]
    )

    assert changed is True
    text = spec_file.read_text(encoding="utf-8")
    assert "www.prodata.dk" in text
    assert "- **topic:**" not in text


# ---------------------------------------------------------------------------
# cited_hosts_for_cycle — the notes a cycle created, found in the vault's corpus
# ---------------------------------------------------------------------------


def _vault_with_one_cited_note(tmp_path: Path, corpus: str) -> Path:
    """A vault whose cycle 1 created ``kafka.md``, reported by bare file name."""
    vault = tmp_path / "vault"
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    (cycles / "cycle-001-research.json").write_text(
        '{"notes_created": ["kafka.md"]}', encoding="utf-8"
    )
    note = vault / corpus / "01 - Concepts" / "kafka.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\ntitle: Kafka\nsource_urls:\n"
        "  - https://kafka.apache.org/documentation/\n---\n\nBody.\n",
        encoding="utf-8",
    )
    return vault


def test_cited_hosts_finds_a_note_reported_by_name(tmp_path: Path) -> None:
    from research_framework.pipeline.spec_append import cited_hosts_for_cycle

    vault = _vault_with_one_cited_note(tmp_path, "data_vault")

    assert cited_hosts_for_cycle(vault, 1) == [
        DiscoveredSource(
            url="https://kafka.apache.org/documentation/", note="cited by kafka.md"
        )
    ]


def test_cited_hosts_looks_in_a_custom_corpus_dir(tmp_path: Path) -> None:
    """The by-name lookup searched ``data_vault/`` whatever the vault declared
    (``vault.corpus_dir``), so a vault keeping its notes elsewhere recorded no
    discovered source for any note reported by bare file name."""
    from research_framework.pipeline.spec_append import cited_hosts_for_cycle

    vault = _vault_with_one_cited_note(tmp_path, "notes")
    (vault / "_pipeline" / "spec-parse.json").write_text(
        '{"vault_corpus_dir": "notes"}', encoding="utf-8"
    )

    assert cited_hosts_for_cycle(vault, 1) == [
        DiscoveredSource(
            url="https://kafka.apache.org/documentation/", note="cited by kafka.md"
        )
    ]
