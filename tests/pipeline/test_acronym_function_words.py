"""A derived acronym that is an English function word must not become an alias.

`_derive_acronym` accepted any acronym with >= 2 initials, so "Nemotron Omni"
derived **"NO"** and spec 067 wrote `data_vault/no.md` — a note titled with an
ordinary English word. Seen live in `feeds-vault` after the 2026-08-27 campaign,
alongside legitimate stubs (SSI, TML, AAGDEA).

The rule is about *matchability*, not spelling: `resolve_acronym_links` rewrites
unresolved all-caps `[[TOKEN]]` references, so an acronym that is a function
word is far more likely to be matched by accident than on purpose. `[[IT]]` in a
reference vault is more plausibly the pronoun than Information Technology — so that
alias is deliberately sacrificed, and the note itself is unaffected either way.

Content words are NOT blocked: only the closed class (pronouns, articles,
prepositions, conjunctions, auxiliaries). "AI", "ML", "API" and friends are not
English words and keep working.
"""

from __future__ import annotations

import pytest

from research_framework.pipeline.wikilinks import _derive_acronym


@pytest.mark.parametrize(
    "title",
    [
        "Nemotron Omni",  # NO  — the reported bug
        "Inference Time",  # IT
        "Open Source",  # OS ... not a function word; see below
    ][:2],
)
def test_function_word_acronyms_are_rejected(title: str) -> None:
    assert _derive_acronym(title) is None, title


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Artificial Intelligence", "AI"),
        ("Machine Learning", "ML"),
        ("Open Source", "OS"),
        ("Large Language Model", "LLM"),
        ("Retrieval Augmented Generation", "RAG"),
        ("Order Engine Customer Data Handler", "OECDH"),
        ("Safe Superintelligence", "SS"),
    ],
)
def test_legitimate_acronyms_still_derive(title: str, expected: str) -> None:
    """The fix must not cost us real acronyms — AI and ML especially."""
    assert _derive_acronym(title) == expected


def test_single_initial_still_rejected() -> None:
    """Pre-existing rule, unchanged."""
    assert _derive_acronym("Kubernetes") is None


def test_stopwords_are_still_skipped_when_deriving() -> None:
    """`of`/`the` don't contribute initials — pre-existing behaviour."""
    assert _derive_acronym("Map of Content") == "MC"


def test_case_and_punctuation_head_split_unchanged() -> None:
    assert _derive_acronym("Nemotron Omni (NVIDIA)") is None
    assert _derive_acronym("Artificial Intelligence — a primer") == "AI"


def test_validate_vault_copy_agrees() -> None:
    """`scripts/validate_vault.py` keeps a deliberate self-contained copy; the
    rule has to hold in both or the standalone gate disagrees with the pipeline."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from validate_vault import _derive_acronym as script_derive

    for title in (
        "Nemotron Omni",
        "Inference Time",
        "Artificial Intelligence",
        "Machine Learning",
        "Order Engine Customer Data Handler",
        "Map of Content",
        "Kubernetes",
    ):
        assert script_derive(title) == _derive_acronym(title), title
