"""Spec 062 FR3 — title-derived acronym links resolve.

A vault whose note titles imply acronyms yields resolvable ``[[ACRONYM]]``
references (rewritten to the canonical stem AND backed by a redirect stub).
Ambiguous acronyms (two notes ⇒ same acronym) are dropped — never wrong-linked.
Resolution is deterministic (title-derived), not LLM-driven.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.pipeline.wikilinks import (
    _write_redirect_stub,
    build_acronym_map,
    resolve_acronym_links,
)

# rc7 baseline (self-documenting regression record, 067 T002): before this spec,
# the ambiguity-emergence timeline below produced this exact corruption in
# ``CAP Theorem.md`` — the note's own ``[[CAP]]`` was rewritten to the sibling
# ``cache-aside pattern`` expansion, renaming the note's subject.
RC7_CORRUPTED_BODY = "The [[cache-aside pattern]] Theorem states..."
RC7_CORRUPTED_STUB = "cap.md → cache-aside pattern"


def _note(vault: Path, stem: str, title: str, *, body: str = "", **extra) -> Path:
    data = vault / "data_vault"
    data.mkdir(parents=True, exist_ok=True)
    fm = [f"title: {title}", "type: concept"]
    for k, v in extra.items():
        fm.append(f"{k}: {v}")
    p = data / f"{stem}.md"
    p.write_text(
        "---\n" + "\n".join(fm) + "\n---\n" + (body or "Body.\n"), encoding="utf-8"
    )
    return p


def _build_cap_timeline(vault: Path) -> Path:
    """The rc7 CAP corruption *timeline* (067 T001).

    Cycle A: only ``cache-aside pattern`` (derives ``CAP``). Cycle B adds
    ``CAP Theorem`` (own subject acronym ``CAP``) carrying a body ``[[CAP]]`` —
    the exact ambiguity-emergence sequence that produced the rc7 corruption.
    Returns the ``CAP Theorem.md`` note path.
    """
    _note(vault, "cache-aside-pattern", "Cache-Aside Pattern")  # cycle A
    return _note(  # cycle B
        vault,
        "cap-theorem",
        "CAP Theorem",
        body="The [[CAP]] Theorem says you can't have all three.\n",
    )


def test_title_derives_acronym(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    _note(
        vault,
        "order-engine-customer-data-handler",
        "Order Engine Customer Data Handler",
    )
    acronym_map, ambiguous = build_acronym_map(vault)
    assert acronym_map.get("OECDH") == "order-engine-customer-data-handler"
    assert ambiguous == []


def test_unresolved_acronym_link_rewritten_to_stem(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    _note(
        vault,
        "order-engine-customer-data-handler",
        "Order Engine Customer Data Handler",
    )
    consumer = _note(
        vault, "risk", "Risk Register", body="Depends on [[OECDH]] heavily.\n"
    )
    resolve_acronym_links(vault)
    text = consumer.read_text(encoding="utf-8")
    assert "[[order-engine-customer-data-handler]]" in text
    assert "[[OECDH]]" not in text


def test_redirect_stub_generated_and_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    _note(
        vault,
        "order-engine-customer-data-handler",
        "Order Engine Customer Data Handler",
    )
    n1 = resolve_acronym_links(vault)
    stub = vault / "data_vault" / "oecdh.md"
    assert stub.exists(), "a redirect stub must be generated for OECDH"
    body = stub.read_text(encoding="utf-8")
    assert "note_type: alias" in body
    assert "redirect_to: order-engine-customer-data-handler" in body
    assert "verifier_status: exempt" in body
    # Idempotent: a second pass on the now-clean vault writes nothing.
    n2 = resolve_acronym_links(vault)
    assert n1 >= 1 and n2 == 0


def test_ambiguous_acronym_is_dropped(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    _note(vault, "shared-processing-and-control", "Shared Processing And Control")
    _note(vault, "system-process-control", "System Process Control")
    acronym_map, ambiguous = build_acronym_map(vault)
    # Both derive "SPC" (stopword "And" dropped) → ambiguous, never linked.
    assert "SPC" not in acronym_map
    assert "SPC" in ambiguous


def test_explicit_aliases_honoured_additively(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    _note(
        vault,
        "kafka-event-bus",
        "Kafka Event Bus",
        aliases="[KEB, MessageBus]",
    )
    acronym_map, _ = build_acronym_map(vault)
    assert acronym_map.get("KEB") == "kafka-event-bus"
    assert acronym_map.get("MESSAGEBUS") == "kafka-event-bus"


def test_an_alias_never_replaces_a_real_note_with_a_stub(tmp_path: Path) -> None:
    """``aliases: [Kubernetes]`` on one note maps ``KUBERNETES`` to it, and the
    stub path is ``kubernetes.md`` — the real note of that name, which the stub
    writer used to overwrite with a redirect, every cycle."""
    vault = tmp_path / "v"
    real = _note(vault, "kubernetes", "Kubernetes", body="The real note.\n")
    before = real.read_text(encoding="utf-8")
    _note(
        vault,
        "container-orchestration",
        "Container Orchestration",
        aliases="[Kubernetes]",
    )

    resolve_acronym_links(vault)

    assert real.read_text(encoding="utf-8") == before


def test_an_acronym_that_is_a_real_note_is_not_remapped(tmp_path: Path) -> None:
    """``[[CAP]]`` resolves to ``cap.md``; a sibling whose title spells CAP must
    not capture it.

    The map skipped an acronym only when one of the notes CLAIMING it had that
    stem. ``cap.md`` ("CAP Theorem" derives CT) does not claim CAP —
    ``cache-aside-pattern.md`` does — so every valid ``[[CAP]]`` in the vault
    was rewritten to ``[[cache-aside-pattern]]``.
    """
    vault = tmp_path / "v"
    _note(vault, "cap", "CAP Theorem")
    _note(vault, "cache-aside-pattern", "Cache-Aside Pattern")
    linking = _note(
        vault,
        "databases",
        "Distributed Databases",
        body="See [[CAP]] for the trade-off.\n",
        related="['[[CAP]]']",
    )
    before = linking.read_text(encoding="utf-8")

    acronym_map, ambiguous = build_acronym_map(vault)
    resolve_acronym_links(vault)

    assert "CAP" not in acronym_map
    assert "CAP" not in ambiguous
    assert linking.read_text(encoding="utf-8") == before


def test_an_acronym_that_is_a_real_note_is_not_ambiguous_either(
    tmp_path: Path,
) -> None:
    """Two claimants make CAP ambiguous, and an ambiguous ``[[CAP]]`` is reduced
    to plain text — which would unlink the valid link to ``cap.md``."""
    vault = tmp_path / "v"
    _note(vault, "cap", "CAP Theorem")
    _note(vault, "cache-aside-pattern", "Cache-Aside Pattern")
    _note(vault, "cost-allocation-policy", "Cost Allocation Policy")
    linking = _note(
        vault,
        "databases",
        "Distributed Databases",
        body="See [[CAP]] for the trade-off.\n",
    )
    before = linking.read_text(encoding="utf-8")

    acronym_map, ambiguous = build_acronym_map(vault)
    resolve_acronym_links(vault)

    assert "CAP" not in acronym_map
    assert "CAP" not in ambiguous
    assert linking.read_text(encoding="utf-8") == before


def test_a_redirect_stub_does_not_count_as_a_real_note(tmp_path: Path) -> None:
    """The acronym's own ``note_type: alias`` stub must not take it off the map,
    or the second run would stop resolving what the first run set up."""
    vault = tmp_path / "v"
    _note(vault, "cache-aside-pattern", "Cache-Aside Pattern")
    resolve_acronym_links(vault)
    assert (vault / "data_vault" / "cap.md").is_file()

    acronym_map, _ = build_acronym_map(vault)

    assert acronym_map.get("CAP") == "cache-aside-pattern"


def test_an_alias_with_a_path_separator_writes_no_stub_outside_its_folder(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "v"
    _note(vault, "escape-hatch", "Escape Hatch", aliases='["../../outside"]')

    resolve_acronym_links(vault)

    assert not (tmp_path / "outside.md").exists()
    assert not (vault / "outside.md").exists()


def test_no_acronyms_is_noop(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    _note(vault, "kafka", "Kafka")  # single significant word → no acronym
    assert resolve_acronym_links(vault) == 0


# ---------------------------------------------------------------------------
# 067 FR1 — single-expansion-only mapping (contract C1-a)
# ---------------------------------------------------------------------------


def test_ambiguous_acronym_no_map_no_stub(tmp_path: Path) -> None:
    """C1-a: an acronym claimed by 2 titles is absent from ``mapping``, present in
    ``ambiguous``, and ``_write_redirect_stub`` is a no-op for it."""
    vault = tmp_path / "v"
    _note(vault, "shared-processing-and-control", "Shared Processing And Control")
    _note(vault, "system-process-control", "System Process Control")
    acronym_map, ambiguous = build_acronym_map(vault)
    assert "SPC" not in acronym_map
    assert "SPC" in ambiguous
    # The stub writer must refuse an ambiguous acronym even if asked directly.
    wrote = _write_redirect_stub(
        vault, "SPC", "system-process-control", ambiguous=frozenset({"SPC"})
    )
    assert wrote is False
    assert not (vault / "data_vault" / "spc.md").exists()


# ---------------------------------------------------------------------------
# 067 FR2 — self-title protection + stale re-evaluation (contracts C2-a / C2-b)
# ---------------------------------------------------------------------------


def test_rc7_cap_timeline_keeps_self_title(tmp_path: Path) -> None:
    """C2-a: the rc7 CAP timeline must NOT rewrite ``CAP Theorem``'s own
    ``[[CAP]]`` to the sibling ``cache-aside pattern`` expansion."""
    vault = tmp_path / "v"
    cap = _build_cap_timeline(vault)
    resolve_acronym_links(vault)
    text = cap.read_text(encoding="utf-8")
    assert "[[cache-aside-pattern]]" not in text
    assert "[[cache-aside pattern]]" not in text
    assert "The CAP Theorem says" in text


def test_rc7_expanded_self_title_link_reverse_mapped(tmp_path: Path) -> None:
    """C2-a (retroactive heal): the corruption that ACTUALLY shipped in rc7 was the
    acronym already expanded in full — ``[[cache-aside pattern]] Theorem`` rather
    than ``[[CAP]] Theorem``. A bare ``[[phrase]]`` whose derived acronym is the
    note's own title-acronym but points at a sibling note must reverse-map back to
    the plain acronym (``CAP``), healing pre-existing rc7 vaults the sweep can't
    catch via the all-caps ``[[CAP]]`` path."""
    vault = tmp_path / "v"
    _note(vault, "cache-aside pattern", "Cache-Aside Pattern")
    cap = _note(
        vault,
        "cap-theorem",
        "CAP Theorem",
        body=(
            "The [[cache-aside pattern]] Theorem says you can't have all three.\n\n"
            "PACELC extends [[cache-aside pattern]]: even absent a partition.\n"
        ),
    )
    resolve_acronym_links(vault)
    text = cap.read_text(encoding="utf-8")
    assert "[[cache-aside pattern]]" not in text
    assert "The CAP Theorem says" in text
    assert "PACELC extends CAP:" in text


def test_self_title_acronym_never_sibling_links(tmp_path: Path) -> None:
    """C2-b: a note whose own title-acronym has a single-claim sibling plain-texts
    its own ``[[A]]`` rather than linking to the sibling."""
    vault = tmp_path / "v"
    _note(
        vault, "application-programming-interface", "Application Programming Interface"
    )
    note = _note(
        vault,
        "api-first",
        "API First",
        body="An [[API]] First design starts at the contract.\n",
    )
    resolve_acronym_links(vault)
    text = note.read_text(encoding="utf-8")
    assert "[[application-programming-interface]]" not in text
    assert "An API First design" in text


def test_now_ambiguous_body_link_plaintexted(tmp_path: Path) -> None:
    """C2 re-eval: a body ``[[TOKEN]]`` whose acronym became ambiguous is reduced
    to plain text (a stale auto-link must not survive as a wrong link)."""
    vault = tmp_path / "v"
    _note(vault, "shared-processing-and-control", "Shared Processing And Control")
    _note(vault, "system-process-control", "System Process Control")
    consumer = _note(vault, "ops", "Ops Guide", body="We rely on [[SPC]] heavily.\n")
    resolve_acronym_links(vault)
    text = consumer.read_text(encoding="utf-8")
    assert "[[SPC]]" not in text
    assert "We rely on SPC heavily." in text


def test_now_ambiguous_stub_is_orphaned(tmp_path: Path) -> None:
    """C2 re-eval: a pre-existing alias stub whose acronym is now ambiguous is
    deleted (it can only point at one of ≥2 claimants)."""
    vault = tmp_path / "v"
    data = vault / "data_vault"
    data.mkdir(parents=True, exist_ok=True)
    _note(vault, "shared-processing-and-control", "Shared Processing And Control")
    _note(vault, "system-process-control", "System Process Control")
    stub = data / "spc.md"
    stub.write_text(
        "---\ntitle: SPC\nnote_type: alias\nredirect_to: system-process-control\n"
        "verifier_status: exempt\n---\nSee [[system-process-control]].\n",
        encoding="utf-8",
    )
    resolve_acronym_links(vault)
    assert not stub.exists()
